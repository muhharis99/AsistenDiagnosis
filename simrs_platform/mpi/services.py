from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
from datetime import date
from typing import Any
from cryptography.fernet import Fernet
from django.db import transaction
from django.utils import timezone

from mpi.models import DuplicateReview, Patient, PatientMergeEvent
from platform_core.audit import record_audit_event

class DuplicatePatientCandidate(Exception):
    def __init__(self, candidate_ids: list[str]) -> None:
        super().__init__("Ada kandidat pasien serupa; verifikasi manual wajib.")
        self.candidate_ids = candidate_ids

def _fernet() -> Fernet:
    key = os.getenv("MPI_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("MPI_ENCRYPTION_KEY wajib dikonfigurasi untuk operasi MPI.")
    return Fernet(key.encode("ascii"))

def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")

def decrypt_value(value: str) -> str:
    return _fernet().decrypt(value.encode("ascii")).decode("utf-8")

def _hmac_key() -> bytes:
    key = os.getenv("MPI_HMAC_KEY", "").encode("utf-8")
    if len(key) < 32:
        raise RuntimeError("MPI_HMAC_KEY harus minimal 32 byte.")
    return key

def fingerprint(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    normalized = re.sub(r"\s+", " ", normalized)
    return hmac.new(_hmac_key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()

def normalize_nik(nik: str) -> str:
    digits = re.sub(r"\D", "", nik)
    if digits and len(digits) != 16:
        raise ValueError("NIK yang diisi harus 16 digit.")
    return digits

def find_duplicate_candidates(*, full_name: str, birth_date: date | None, nik: str = "") -> list[Patient]:
    active = Patient.objects.filter(status=Patient.Status.ACTIVE)
    normalized_nik = normalize_nik(nik) if nik else ""
    if normalized_nik:
        exact = active.filter(nik_fingerprint=fingerprint(normalized_nik))
        if exact.exists():
            return list(exact[:10])
    name_matches = active.filter(name_fingerprint=fingerprint(full_name), birth_date=birth_date)
    return list(name_matches[:10])

@transaction.atomic
def create_patient(*, full_name: str, birth_date: date | None, administrative_sex: str,
                   nik: str = "", actor: Any = None) -> Patient:
    name = " ".join(full_name.split())
    if len(name) < 2 or len(name) > 200:
        raise ValueError("Nama wajib diisi (2–200 karakter).")
    normalized_nik = normalize_nik(nik) if nik else ""
    candidates = find_duplicate_candidates(full_name=name, birth_date=birth_date, nik=normalized_nik)
    if candidates:
        raise DuplicatePatientCandidate([str(patient.id) for patient in candidates])
    nik_fp = fingerprint(normalized_nik) if normalized_nik else None
    patient = Patient.objects.create(
        full_name_ciphertext=encrypt_value(name),
        name_fingerprint=fingerprint(name),
        birth_date=birth_date,
        administrative_sex=administrative_sex,
        nik_ciphertext=encrypt_value(normalized_nik) if normalized_nik else "",
        nik_fingerprint=nik_fp,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    record_audit_event(
        actor=actor, event_type="mpi.patient.created", subject_type="Patient",
        subject_id=str(patient.id), metadata={"mrn": patient.mrn, "has_nik": bool(normalized_nik)},
    )
    return patient

@transaction.atomic
def record_duplicate_review(*, patient: Patient, candidate: Patient, status: str,
                            actor: Any, reason: str = "") -> DuplicateReview:
    if patient.pk == candidate.pk:
        raise ValueError("Pasien tidak dapat menjadi kandidat dirinya sendiri.")
    if status not in {DuplicateReview.Status.CONFIRMED, DuplicateReview.Status.REJECTED}:
        raise ValueError("Status review harus CONFIRMED atau REJECTED.")
    review, _ = DuplicateReview.objects.update_or_create(
        patient=patient, candidate=candidate,
        defaults={"status": status, "reviewed_by": actor, "reason": reason[:240], "reviewed_at": timezone.now()},
    )
    record_audit_event(actor=actor, event_type="mpi.duplicate.reviewed", subject_type="Patient",
                       subject_id=str(patient.id), metadata={"candidate_id": str(candidate.id), "decision": status})
    return review

@transaction.atomic
def merge_patients(*, source_id: str, target_id: str, actor: Any, reason: str) -> Patient:
    if not reason.strip():
        raise ValueError("Alasan merge wajib dicatat.")
    rows = {str(p.id): p for p in Patient.objects.select_for_update().filter(id__in=[source_id, target_id])}
    if source_id == target_id or source_id not in rows or target_id not in rows:
        raise ValueError("Pasangan pasien untuk merge tidak valid.")
    source, target = rows[source_id], rows[target_id]
    if source.status != Patient.Status.ACTIVE or target.status != Patient.Status.ACTIVE:
        raise ValueError("Hanya pasien aktif yang bisa diproses; tinjau riwayat terlebih dahulu.")
    PatientMergeEvent.objects.create(source=source, target=target, merged_by=actor, reason=reason.strip()[:500])
    source.status = Patient.Status.MERGED
    source.merged_into = target
    source.version += 1
    source.save(update_fields=["status", "merged_into", "version", "updated_at"])
    record_audit_event(actor=actor, event_type="mpi.patient.merged", subject_type="Patient",
                       subject_id=str(source.id), metadata={"target_id": str(target.id), "reason_recorded": True})
    return target
