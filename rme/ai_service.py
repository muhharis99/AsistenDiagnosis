"""Layanan Asisten Diagnosis dalam alur RME; AI hanya menyimpan saran."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import SYMPTOM_METADATA_PATH, SYMPTOM_MODEL_PATH
from explain import explain_symptom_candidates, insufficient_information, ordered_topk, suggest_followup_symptoms
from rme import __version__ as RME_CODE_VERSION
from rme.models import AISuggestion, AISuggestionReview, AuditLog, Consent, ModelRegistry, Patient, User, Visit
from rme.schemas import AISuggestionReviewInput
from rme.security import append_audit, require_permission
from safety import detect_red_flags, load_safety_config


class AIWorkflowError(ValueError):
    """Aturan alur AI atau kesiapan model tidak terpenuhi."""


class AIConsentRequired(AIWorkflowError):
    """Persetujuan penggunaan AI-assist belum diberikan atau tidak aktif."""


def ai_consent_granted(session: Session, patient_id: int) -> bool:
    """Ambil persetujuan AI-assist terakhir; persetujuan terakhir yang ditolak mengalahkan yang lama."""
    consent = session.scalar(
        select(Consent)
        .where(Consent.patient_id == patient_id, Consent.consent_type == "ai_assist")
        .order_by(Consent.id.desc())
        .limit(1)
    )
    return bool(consent and consent.granted)


def read_symptom_metadata(path: Path | None = None) -> dict[str, Any]:
    """Baca metadata model tanpa menjalankan inferensi."""
    metadata_path = path or SYMPTOM_METADATA_PATH
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _hash_training_data(bundle: dict[str, Any]) -> str:
    """Hash kanonis untuk fitur dan label train yang ikut disimpan dalam bundle model."""
    if "X_train" not in bundle or "y_train" not in bundle:
        raise AIWorkflowError(
            "Bundle model tidak menyimpan X_train/y_train, sehingga hash data latih tidak dapat diverifikasi. "
            "Latih ulang model gejala dengan versi proyek saat ini."
        )
    frame = pd.DataFrame(bundle["X_train"]).reset_index(drop=True).copy()
    target = pd.Series(bundle["y_train"]).astype(str).reset_index(drop=True)
    if len(frame) != len(target):
        raise AIWorkflowError("Fitur dan label training pada bundle tidak seimbang.")
    frame["__target__"] = target
    canonical = frame.to_csv(
        index=False, na_rep="<NA>", float_format="%.17g", lineterminator="\n"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _age_on(birth_date: date, today: date | None = None) -> int:
    current = today or date.today()
    return current.year - birth_date.year - ((current.month, current.day) < (birth_date.month, birth_date.day))


def _load_bundle(model_path: Path, metadata_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Muat hanya artefak model lokal yang telah ditempatkan pengelola proyek."""
    if not model_path.is_file():
        raise AIWorkflowError(
            "Artefak model gejala belum ditemukan. Jalankan python train_symptom.py terlebih dahulu."
        )
    try:
        bundle = joblib.load(model_path)
    except Exception as exc:
        raise AIWorkflowError("Artefak model gejala gagal dimuat; periksa versi library dan latih ulang.") from exc
    if not isinstance(bundle, dict) or "model" not in bundle or "feature_names" not in bundle:
        raise AIWorkflowError("Format bundle model gejala tidak dikenali.")
    metadata = read_symptom_metadata(metadata_path)
    return bundle, metadata


def _assert_doctor_visit(session: Session, user: User, visit_id: int) -> tuple[Visit, Patient]:
    """Pastikan aktor adalah dokter berizin dan kunjungan masih aktif."""
    require_permission(user, "ai:review")
    if not user.role or user.role.code != "dokter":
        raise AIWorkflowError("Panel Asisten Diagnosis hanya tersedia untuk peran Dokter (DPJP).")
    visit = session.get(Visit, visit_id)
    if visit is None:
        raise AIWorkflowError("Kunjungan tidak ditemukan.")
    if visit.status != "in-progress":
        raise AIWorkflowError("Saran AI hanya dapat diminta selama kunjungan in-progress.")
    if visit.dpjp_user_id is not None and visit.dpjp_user_id != user.id:
        raise AIWorkflowError("Kunjungan ini ditugaskan kepada DPJP lain.")
    patient = session.get(Patient, visit.patient_id)
    if patient is None or not patient.is_demo or not visit.is_demo:
        raise AIWorkflowError("Fase 2 hanya mengizinkan kunjungan dan pasien fiktif.")
    return visit, patient


def request_symptom_suggestion(
    session: Session,
    user: User,
    visit_id: int,
    selected_symptoms: Iterable[str],
    *,
    explicit_red_flags: Iterable[str] | None = None,
    special_groups: Iterable[str] | None = None,
    model_path: Path | None = None,
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    """Buat saran statistik setelah consent dan pemeriksaan keselamatan; tidak membuat diagnosis resmi."""
    visit, patient = _assert_doctor_visit(session, user, visit_id)
    symptoms = list(dict.fromkeys(str(item).strip() for item in (selected_symptoms or []) if str(item).strip()))
    safety_config = load_safety_config()

    # Red flag diperiksa sebelum ML. Alert yang sudah tercatat tetap memblokir inferensi pada kunjungan ini.
    current_flags = detect_red_flags(symptoms, explicit_red_flags, safety_config)
    prior_logs = session.scalars(
        select(AuditLog).where(
            AuditLog.action == "ai.red_flag_blocked",
            AuditLog.entity_type == "Visit",
            AuditLog.entity_id == str(visit.id),
        ).order_by(AuditLog.id.asc())
    ).all()
    prior_ids: set[str] = set()
    for log in prior_logs:
        try:
            prior_ids.update(str(x) for x in json.loads(log.details_json).get("red_flag_ids", []))
        except (json.JSONDecodeError, TypeError):
            continue
    current_ids = {str(item.get("id")) for item in current_flags}
    all_ids = prior_ids | current_ids
    red_flag_catalog = {str(item.get("id")): item for item in safety_config.get("red_flags", [])}
    red_flags = [dict(red_flag_catalog[item]) for item in sorted(all_ids) if item in red_flag_catalog]
    if red_flags:
        append_audit(
            session, user, "ai.red_flag_blocked", "Visit", visit.id,
            {"red_flag_ids": [item.get("id") for item in red_flags], "symptom_count": len(symptoms), "model_called": False},
        )
        session.commit()
        return {
            "status": "red_flag_blocked",
            "message": "Gejala gawat darurat tercatat pada kunjungan ini. Jangan menunggu hasil AI; segera ke IGD atau hubungi 112 / 119. Inferensi tetap diblokir untuk kunjungan ini.",
            "red_flags": red_flags,
        }

    # Peringatan kelompok khusus juga memblokir model sebelum pemuatan/inferensi.
    actual_age = _age_on(patient.birth_date)
    blocked_groups = list(dict.fromkeys(str(x) for x in (special_groups or []) if str(x).strip()))
    if actual_age < 18:
        blocked_groups.append("Bayi/anak kecil")
    if actual_age >= 65:
        blocked_groups.append("Lansia")
    if blocked_groups:
        append_audit(
            session, user, "ai.special_population_blocked", "Visit", visit.id,
            {"groups": sorted(set(blocked_groups)), "model_called": False},
        )
        session.commit()
        return {
            "status": "special_population_blocked",
            "groups": sorted(set(blocked_groups)),
            "message": "Model tidak divalidasi untuk kelompok ini. Hasil ditahan; konsultasikan langsung ke dokter/fasilitas kesehatan.",
        }

    if not ai_consent_granted(session, patient.id):
        append_audit(session, user, "ai.consent_denied", "Visit", visit.id, {"consent_type": "ai_assist", "model_called": False})
        session.commit()
        raise AIConsentRequired(
            "Persetujuan AI-assist belum aktif. Catat persetujuan pasien melalui alur pendaftaran sebelum menggunakan panel AI."
        )

    if len(symptoms) < 3:
        append_audit(
            session, user, "ai.insufficient_symptoms", "Visit", visit.id,
            {"symptom_count": len(symptoms), "model_called": False},
        )
        session.commit()
        return {
            "status": "insufficient_information",
            "message": "Belum cukup informasi. Pilih sedikitnya tiga gejala yang benar-benar dialami; jangan menebak atau menambah gejala.",
            "followup_questions": [],
        }

    model_path = model_path or SYMPTOM_MODEL_PATH
    metadata_path = metadata_path or SYMPTOM_METADATA_PATH
    try:
        bundle, metadata = _load_bundle(model_path, metadata_path)
        feature_names = [str(name) for name in bundle["feature_names"]]
        unknown = sorted(set(symptoms).difference(feature_names))
        if unknown:
            raise AIWorkflowError("Ada ID gejala yang tidak dikenal model. Muat ulang daftar gejala lalu coba lagi.")
        if "X_train" not in bundle or "y_train" not in bundle:
            raise AIWorkflowError("Statistik training untuk penjelasan tidak tersedia; latih ulang model gejala.")
        artifact_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        training_hash = _hash_training_data(bundle)
        model = bundle["model"]
        row = pd.DataFrame(
            [[1 if feature in set(symptoms) else 0 for feature in feature_names]],
            columns=feature_names,
        )
        probabilities = np.asarray(model.predict_proba(row)[0], dtype=float)
        classes = list(getattr(model, "classes_", bundle.get("classes", [])))
        if len(classes) != len(probabilities) or not np.isfinite(probabilities).all() or probabilities.sum() <= 0:
            raise AIWorkflowError("Keluaran probabilitas model tidak valid; saran tidak dibuat.")
        probabilities = probabilities / probabilities.sum()
        top = ordered_topk(probabilities, classes, k=3)
        if not top:
            raise AIWorkflowError("Model tidak menghasilkan kandidat.")
        threshold = float(bundle.get("confidence_threshold", metadata.get("confidence_threshold", 0.0)))
        hold, hold_reason = insufficient_information(symptoms, top[0]["probability"], threshold)
        status = "insufficient_information" if hold else "generated"
        explanations = explain_symptom_candidates(bundle["X_train"], bundle["y_train"], symptoms, top)
        followup = suggest_followup_symptoms(
            bundle["X_train"], bundle["y_train"], top, symptoms, n_questions=3
        )
        model_name = str(bundle.get("model_name", metadata.get("model", "symptom-model")))
        trained_at = str(metadata.get("trained_at_utc", "legacy-metadata"))
        model_version = f"{model_name}@{trained_at}"
        is_demo = bool(bundle.get("is_demo", metadata.get("is_demo", True)))
        if not is_demo:
            # Prototipe RME selalu data fiktif; model non-demo tetap perlu ditinjau secara eksplisit.
            # Non-demo model tidak otomatis dianggap tervalidasi.
            model_status = "UNVALIDATED"
        else:
            model_status = "DEMO_UNVALIDATED"
    except AIWorkflowError:
        raise
    except Exception as exc:
        raise AIWorkflowError("Inferensi atau penjelasan model gagal; tidak ada diagnosis resmi yang diubah.") from exc

    payload_candidates = json.dumps(top, ensure_ascii=False, sort_keys=True)
    payload_explanations = json.dumps(explanations, ensure_ascii=False, sort_keys=True)
    payload_followup = json.dumps(followup, ensure_ascii=False, sort_keys=True)
    record = AISuggestion(
        visit_id=visit.id,
        requested_by=user.id,
        model_name=model_name,
        model_version=model_version,
        model_artifact_sha256=artifact_hash,
        training_data_sha256=training_hash,
        code_version=RME_CODE_VERSION + "+" + os.getenv("GIT_COMMIT_SHA", "local-or-unspecified"),
        input_symptom_ids_json=json.dumps(symptoms, ensure_ascii=False),
        output_candidates_json=payload_candidates,
        explanations_json=payload_explanations,
        followup_questions_json=payload_followup,
        status=status,
        confidence_threshold=threshold,
        max_probability=float(top[0]["probability"]),
        is_demo=True,
    )
    session.add(record)
    session.flush()

    # Registri model menyimpan asal dan metrik yang tersedia, bukan klaim validasi klinis.
    registry = session.scalar(
        select(ModelRegistry).where(ModelRegistry.name == "symptom-differential", ModelRegistry.version == model_version)
    )
    registry_metrics = metadata.get("selected_test_metrics", {})
    registry_payload = {
        "dataset": metadata.get("dataset", {}),
        "selected_test_metrics": registry_metrics,
        "is_demo": is_demo,
        "clinical_validation": "NOT_VALIDATED",
    }
    if registry is None:
        session.add(ModelRegistry(
            name="symptom-differential", version=model_version, data_hash=training_hash,
            metrics_json=json.dumps(registry_payload, ensure_ascii=False, default=str),
            status=model_status, registered_by=user.id,
        ))
    else:
        registry.data_hash = training_hash
        registry.metrics_json = json.dumps(registry_payload, ensure_ascii=False, default=str)
        registry.status = model_status

    append_audit(
        session, user, "ai.suggestion_created" if status == "generated" else "ai.suggestion_held",
        "AISuggestion", record.id,
        {
            "visit_id": visit.id, "status": status, "model_name": model_name, "model_version": model_version,
            "model_artifact_sha256": artifact_hash, "training_data_sha256": training_hash,
            "code_version": record.code_version, "symptom_count": len(symptoms), "candidate_count": len(top),
            "max_probability": float(top[0]["probability"]),
        },
    )
    session.commit()
    session.refresh(record)
    return {
        "id": record.id,
        "status": status,
        "message": hold_reason if hold else "Saran statistik siap ditinjau dokter; bukan diagnosis resmi.",
        "candidates": top if not hold else [],
        "explanations": explanations if not hold else [],
        "followup_questions": followup,
        "confidence_threshold": threshold,
        "max_probability": float(top[0]["probability"]),
        "model_name": model_name,
        "model_version": model_version,
        "model_artifact_sha256": artifact_hash,
        "training_data_sha256": training_hash,
        "is_demo": is_demo,
    }


def review_ai_suggestion(
    session: Session,
    user: User,
    suggestion_id: int,
    data: AISuggestionReviewInput,
) -> AISuggestionReview:
    """Catat tinjauan dokter sebagai event terpisah; fungsi ini tidak membuat Diagnosis."""
    require_permission(user, "ai:review")
    if not user.role or user.role.code != "dokter":
        raise AIWorkflowError("Hanya dokter yang boleh meninjau saran AI.")
    suggestion = session.get(AISuggestion, suggestion_id)
    if suggestion is None or not suggestion.is_demo:
        raise AIWorkflowError("Saran AI tidak ditemukan.")
    visit = session.get(Visit, suggestion.visit_id)
    if visit is None or visit.status != "in-progress":
        raise AIWorkflowError("Tinjauan saran hanya dapat dicatat selama kunjungan in-progress.")
    if visit.dpjp_user_id is not None and visit.dpjp_user_id != user.id:
        raise AIWorkflowError("Kunjungan ditugaskan kepada DPJP lain.")
    if suggestion.status != "generated":
        raise AIWorkflowError("Saran yang ditahan karena informasi kurang tidak dapat dipilih sebagai kandidat.")

    candidates = json.loads(suggestion.output_candidates_json)
    allowed = {str(item.get("label")) for item in candidates}
    action = data.action
    selected = (data.selected_candidate or "").strip() or None
    modified = (data.modified_candidate or "").strip() or None
    reason = (data.reason or "").strip() or None
    if action == "accepted_as_working_hypothesis" and selected not in allowed:
        raise AIWorkflowError("Kandidat yang dipilih harus berasal dari tiga kandidat saran ini.")
    if action == "modified" and (not modified or len(reason or "") < 5):
        raise AIWorkflowError("Perubahan saran harus menyertakan teks dan alasan minimal 5 karakter.")
    if action == "ignored" and len(reason or "") < 5:
        raise AIWorkflowError("Alasan mengabaikan saran minimal 5 karakter.")
    if action == "ignored":
        selected = None
        modified = None

    review = AISuggestionReview(
        suggestion_id=suggestion.id,
        reviewer_user_id=user.id,
        action=action,
        selected_candidate=selected,
        modified_candidate=modified,
        reason=reason,
        is_demo=True,
    )
    session.add(review)
    session.flush()
    reason_hash = hashlib.sha256(reason.encode("utf-8")).hexdigest() if reason else None
    append_audit(
        session, user, "ai.suggestion_reviewed", "AISuggestionReview", review.id,
        {
            "suggestion_id": suggestion.id, "action": action, "selected_candidate": selected,
            "reason_sha256": reason_hash, "formal_diagnosis_created": False,
        },
    )
    session.commit()
    session.refresh(review)
    return review
