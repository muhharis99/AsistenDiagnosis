"""Mapping SATUSEHAT dan preflight sandbox lokal; modul ini tidak melakukan HTTP."""
from __future__ import annotations

import os
import re
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from rme.models import Consent, Diagnosis, Patient, ResumeMedical, SATUSEHATIdMapping, User, Visit, utc_now
from rme.security import append_audit, require_permission


ALLOWED_RESOURCE_TYPES = {"Patient", "Practitioner", "Organization", "Location", "Encounter"}
SANDBOX_BASE_URL = "https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1"
SANDBOX_TOKEN_URL = "https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken"
EXTERNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
IHS_ORG_PATTERN = re.compile(r"^[0-9]{6,20}$")


class MappingWorkflowError(ValueError):
    """Aturan mapping atau preflight sandbox tidak terpenuhi."""


def is_safe_external_id(value: str) -> bool:
    candidate = (value or "").strip()
    lowered = candidate.casefold()
    if not EXTERNAL_ID_PATTERN.fullmatch(candidate):
        return False
    if "demo" in lowered or "example" in lowered or ".invalid" in lowered:
        return False
    return True


def location_local_key(visit: Visit) -> str:
    """Key lokal yang stabil untuk mapping poli dalam sebuah fasyankes demo."""
    return f"{visit.facility_id}:{(visit.poli or '').strip().casefold()}"


def upsert_satusehat_mapping(
    session: Session,
    user: User,
    *,
    resource_type: str,
    local_key: str,
    external_id: str,
    source: str,
) -> SATUSEHATIdMapping:
    """Create/update mapping as unverified; any changed ID invalidates prior verification."""
    require_permission(user, "satusehat:mapping:manage")
    kind = (resource_type or "").strip()
    key = (local_key or "").strip()
    ext_id = (external_id or "").strip()
    source_value = (source or "").strip()
    if kind not in ALLOWED_RESOURCE_TYPES:
        raise MappingWorkflowError("Resource type mapping tidak didukung.")
    if not key or len(key) > 180:
        raise MappingWorkflowError("Kunci lokal wajib 1–180 karakter.")
    if not is_safe_external_id(ext_id):
        raise MappingWorkflowError("ID eksternal kosong, berformat tidak sah, atau masih berupa placeholder demo.")
    if len(source_value) < 10 or len(source_value) > 500:
        raise MappingWorkflowError("Sumber mapping wajib diisi (10–500 karakter).")
    row = session.scalar(
        select(SATUSEHATIdMapping).where(
            SATUSEHATIdMapping.resource_type == kind,
            SATUSEHATIdMapping.local_key == key,
            SATUSEHATIdMapping.environment == "sandbox",
        )
    )
    changed = row is not None and row.external_id != ext_id
    if row is None:
        row = SATUSEHATIdMapping(
            resource_type=kind, local_key=key, external_id=ext_id,
            environment="sandbox", source=source_value, verified=False,
            created_by=user.id, updated_by=user.id, is_demo=True,
        )
        session.add(row)
        session.flush()
        action = "satusehat.mapping_created"
    else:
        row.external_id = ext_id
        row.source = source_value
        row.updated_by = user.id
        row.updated_at = utc_now()
        if changed:
            row.verified = False
            row.verified_by = None
            row.verified_at = None
            row.verification_note = None
        action = "satusehat.mapping_updated"
    append_audit(
        session, user, action, "SATUSEHATIdMapping", row.id,
        {"resource_type": kind, "environment": "sandbox", "verified": bool(row.verified),
         "external_id_recorded": True, "verification_reset": changed},
    )
    session.commit()
    session.refresh(row)
    return row


def verify_satusehat_mapping(
    session: Session, user: User, mapping_id: int, verification_note: str
) -> SATUSEHATIdMapping:
    require_permission(user, "satusehat:mapping:manage")
    row = session.get(SATUSEHATIdMapping, mapping_id)
    if row is None or not row.is_demo or row.environment != "sandbox":
        raise MappingWorkflowError("Mapping sandbox tidak ditemukan.")
    if not is_safe_external_id(row.external_id):
        raise MappingWorkflowError("ID eksternal merupakan placeholder atau formatnya tidak valid.")
    note = (verification_note or "").strip()
    if len(note) < 10 or len(note) > 2000:
        raise MappingWorkflowError("Catatan verifikasi wajib 10–2.000 karakter.")
    if len((row.source or "").strip()) < 10:
        raise MappingWorkflowError("Sumber mapping wajib dicatat sebelum verifikasi.")
    row.verified = True
    row.verification_note = note
    row.verified_by = user.id
    row.verified_at = utc_now()
    row.updated_by = user.id
    row.updated_at = utc_now()
    append_audit(
        session, user, "satusehat.mapping_verified", "SATUSEHATIdMapping", row.id,
        {"resource_type": row.resource_type, "environment": row.environment, "verified": True,
         "note_length": len(note)},
    )
    session.commit()
    session.refresh(row)
    return row


def list_satusehat_mappings(session: Session, user) -> list[SATUSEHATIdMapping]:
    require_permission(user, "satusehat:mapping:read")
    rows = session.scalars(
        select(SATUSEHATIdMapping).where(SATUSEHATIdMapping.is_demo.is_(True))
        .order_by(SATUSEHATIdMapping.resource_type, SATUSEHATIdMapping.local_key)
        .limit(1000)
    ).all()
    append_audit(session, user, "satusehat.mapping_list_read", "SATUSEHATIdMapping", "list", {"count": len(rows)})
    session.commit()
    return rows


def sandbox_configuration_checks(env: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    """Check presence and allow-listed staging endpoints; never returns secret values."""
    values = os.environ if env is None else env
    mode = (values.get("SATUSEHAT_MODE") or "mock").strip().lower()
    app_mode = (values.get("APP_MODE") or "demo").strip().lower()
    client_id = (values.get("SATUSEHAT_CLIENT_ID") or "").strip()
    client_secret = (values.get("SATUSEHAT_CLIENT_SECRET") or "").strip()
    org_ihs = (values.get("SATUSEHAT_ORG_IHS_ID") or "").strip()
    base_url = (values.get("SATUSEHAT_BASE_URL") or "").strip().rstrip("/")
    token_url = (values.get("SATUSEHAT_TOKEN_URL") or "").strip().rstrip("/")
    tls_verify = (values.get("SATUSEHAT_TLS_VERIFY") or "true").strip().lower()

    return [
        {"item": "Mode integrasi sandbox", "passed": mode == "sandbox",
         "detail": "SATUSEHAT_MODE harus sandbox; mode mock tidak memenuhi preflight." if mode != "sandbox" else "Mode sandbox dipilih."},
        {"item": "APP_MODE aplikasi", "passed": app_mode == "demo",
         "detail": "Aplikasi harus tetap pada mode prototipe demo; mode lain ditolak." if app_mode != "demo" else "Aplikasi tetap pada mode demo terkunci."},
        {"item": "Client ID tersedia", "passed": bool(client_id),
         "detail": "Tersedia." if client_id else "SATUSEHAT_CLIENT_ID belum diisi."},
        {"item": "Client secret tersedia", "passed": bool(client_secret),
         "detail": "Tersedia; nilainya tidak ditampilkan." if client_secret else "SATUSEHAT_CLIENT_SECRET belum diisi."},
        {"item": "IHS organisasi induk", "passed": bool(IHS_ORG_PATTERN.fullmatch(org_ihs)),
         "detail": "Format identifier organisasi memenuhi pemeriksaan lokal." if IHS_ORG_PATTERN.fullmatch(org_ihs) else "SATUSEHAT_ORG_IHS_ID kosong atau bukan pola angka yang diharapkan."},
        {"item": "FHIR base URL staging", "passed": base_url == SANDBOX_BASE_URL,
         "detail": "Cocok dengan URL staging yang diizinkan." if base_url == SANDBOX_BASE_URL else "Isi URL staging resmi yang diizinkan; URL bebas tidak diterima."},
        {"item": "Token URL staging", "passed": token_url == SANDBOX_TOKEN_URL,
         "detail": "Cocok dengan endpoint token staging yang diizinkan." if token_url == SANDBOX_TOKEN_URL else "Isi endpoint token staging resmi yang diizinkan."},
        {"item": "Verifikasi TLS aktif", "passed": tls_verify in {"true", "1", "yes"},
         "detail": "Verifikasi TLS aktif." if tls_verify in {"true", "1", "yes"} else "TLS verification tidak boleh dinonaktifkan."},
    ]


def _latest_consent_granted(session: Session, patient_id: int) -> bool:
    row = session.scalar(
        select(Consent).where(Consent.patient_id == patient_id, Consent.consent_type == "data_sharing")
        .order_by(Consent.id.desc()).limit(1)
    )
    return bool(row and row.granted)


def build_visit_sandbox_preflight(
    session: Session, user: User, visit_id: int, env: Mapping[str, str] | None = None
) -> dict[str, object]:
    """Read-only checklist. Passing this preflight still does not send or post resources."""
    require_permission(user, "satusehat:read")
    checks = sandbox_configuration_checks(env)
    visit = session.get(Visit, visit_id)
    if visit is None or not visit.is_demo:
        checks.append({"item": "Kunjungan demo", "passed": False, "detail": "Kunjungan demo tidak ditemukan."})
        return {"ready": False, "checks": checks, "network_calls_enabled": False,
                "notice": "Pemeriksaan ini lokal saja; tidak ada request jaringan."}

    patient = session.get(Patient, visit.patient_id)
    resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit.id))
    diagnosis = session.scalar(
        select(Diagnosis).where(
            Diagnosis.visit_id == visit.id,
            Diagnosis.status == "confirmed",
            Diagnosis.code_verified.is_(True),
        ).limit(1)
    )
    consent_granted = bool(patient and _latest_consent_granted(session, patient.id))
    checks.extend([
        {"item": "Kunjungan finished", "passed": visit.status == "finished",
         "detail": "Status selesai." if visit.status == "finished" else "Selesaikan kunjungan terlebih dahulu."},
        {"item": "Resume final", "passed": bool(resume and resume.status == "final" and resume.finalized_at),
         "detail": "Resume final tersedia." if resume and resume.status == "final" and resume.finalized_at else "Resume final belum tersedia."},
        {"item": "Consent pembukaan/pemanfaatan data", "passed": consent_granted,
         "detail": "Consent terakhir aktif." if consent_granted else "Consent terakhir belum aktif."},
        {"item": "Diagnosis dan coding", "passed": diagnosis is not None,
         "detail": "Ada diagnosis confirmed dengan kode diverifikasi." if diagnosis else "Diagnosis confirmed dengan kode terverifikasi belum tersedia."},
        {"item": "DPJP ditetapkan", "passed": visit.dpjp_user_id is not None,
         "detail": "DPJP terhubung ke kunjungan." if visit.dpjp_user_id is not None else "Kunjungan belum memiliki DPJP."},
    ])

    required = [
        ("Patient", str(visit.patient_id), "Mapping Patient/IHS dari MPI"),
        ("Encounter", str(visit.id), "Mapping Encounter ID dari respons SATUSEHAT"),
        ("Practitioner", str(visit.dpjp_user_id) if visit.dpjp_user_id is not None else "", "Mapping Practitioner/IHS dari MNI"),
        ("Organization", str(visit.facility_id), "Mapping Organization/IHS fasilitas induk"),
        ("Location", location_local_key(visit), "Mapping Location ID untuk poli/lokasi layanan"),
    ]
    values = env if env is not None else os.environ
    org_ihs = (values.get("SATUSEHAT_ORG_IHS_ID") or "").strip()
    for kind, key, label in required:
        row = None
        if key:
            row = session.scalar(
                select(SATUSEHATIdMapping).where(
                    SATUSEHATIdMapping.resource_type == kind,
                    SATUSEHATIdMapping.local_key == key,
                    SATUSEHATIdMapping.environment == "sandbox",
                    SATUSEHATIdMapping.verified.is_(True),
                    SATUSEHATIdMapping.is_demo.is_(True),
                )
            )
        passed = bool(row and is_safe_external_id(row.external_id))
        detail = "Mapping sandbox sudah diverifikasi." if passed else f"{label} belum ada atau belum diverifikasi."
        if passed and kind == "Organization" and org_ihs and row.external_id != org_ihs:
            passed = False
            detail = "IHS mapping organisasi tidak cocok dengan SATUSEHAT_ORG_IHS_ID."
        checks.append({"item": f"Mapping {kind}", "passed": passed, "detail": detail})

    ready = all(bool(item["passed"]) for item in checks)
    append_audit(session, user, "satusehat.sandbox_preflight", "Visit", visit.id,
                 {"ready": ready, "checks": len(checks), "network_calls_enabled": False})
    session.commit()
    return {
        "ready": ready,
        "checks": checks,
        "network_calls_enabled": False,
        "notice": "Preflight hanya memeriksa konfigurasi dan mapping. Belum ada OAuth, POST, atau transmisi resource.",
    }
