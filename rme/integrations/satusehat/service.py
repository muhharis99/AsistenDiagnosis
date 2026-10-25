"""Outbox SATUSEHAT dalam mode mock. Tidak ada pemanggilan jaringan di modul ini."""
from __future__ import annotations

import hashlib
import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from rme.models import Consent, Diagnosis, OutboxSync, Patient, ResumeMedical, Visit, utc_now
from rme.security import append_audit, require_permission
from rme.integrations.satusehat.fhir import build_composition, build_condition, validate_fhir_resource


class MockIntegrationError(ValueError):
    """Integrasi mock belum siap atau aturan pengiriman belum terpenuhi."""


def _latest_consent(session: Session, patient_id: int, consent_type: str) -> bool:
    row = session.scalar(
        select(Consent).where(Consent.patient_id == patient_id, Consent.consent_type == consent_type)
        .order_by(Consent.id.desc()).limit(1)
    )
    return bool(row and row.granted)


def queue_visit_for_mock(session: Session, user, visit_id: int) -> list[OutboxSync]:
    """Build an outbox only after finish, final resume, data-sharing consent and coder verification."""
    require_permission(user, "satusehat:manage")
    visit = session.get(Visit, visit_id)
    if visit is None or not visit.is_demo:
        raise MockIntegrationError("Kunjungan demo tidak ditemukan.")
    if visit.status != "finished":
        raise MockIntegrationError("Kunjungan harus berstatus finished.")
    patient = session.get(Patient, visit.patient_id)
    if patient is None or not patient.is_demo:
        raise MockIntegrationError("Pasien demo tidak ditemukan.")
    if not _latest_consent(session, patient.id, "data_sharing"):
        raise MockIntegrationError("Persetujuan pembukaan/pemanfaatan data belum aktif.")
    resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit.id))
    if resume is None or resume.status != "final" or not resume.finalized_at:
        raise MockIntegrationError("Resume medis harus final sebelum masuk outbox.")
    diagnoses = session.scalars(
        select(Diagnosis).where(
            Diagnosis.visit_id == visit.id,
            Diagnosis.status == "confirmed",
            Diagnosis.code_verified.is_(True),
        ).order_by(Diagnosis.id)
    ).all()
    if not diagnoses:
        raise MockIntegrationError("Minimal satu diagnosis confirmed dengan kode yang diverifikasi Perekam Medis diperlukan.")
    resources = []
    for diagnosis in diagnoses:
        condition = build_condition(patient, visit, diagnosis)
        validate_fhir_resource(condition)
        resources.append(("Condition", condition, f"mock:Condition:visit-{visit.id}:diagnosis-{diagnosis.id}"))
    composition = build_composition(patient, visit, resume, diagnoses)
    validate_fhir_resource(composition)
    resources.append((
        "Composition", composition,
        f"mock:Composition:visit-{visit.id}:resume-{resume.id}:version-{getattr(resume, 'version', 1)}",
    ))
    created: list[OutboxSync] = []
    for resource_type, payload, key in resources:
        existing = session.scalar(select(OutboxSync).where(OutboxSync.idempotency_key == key))
        if existing is not None:
            created.append(existing)
            continue
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row = OutboxSync(
            visit_id=visit.id,
            resource_type=resource_type,
            payload_json=canonical,
            payload_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            idempotency_key=key,
            status="queued",
            attempt_count=0,
            created_by=user.id,
            is_demo=True,
        )
        session.add(row)
        session.flush()
        created.append(row)
    append_audit(
        session, user, "satusehat.mock_outbox_queued", "Visit", visit.id,
        {"resource_types": [kind for kind, _, _ in resources],
         "outbox_count": len(created), "mode": "mock", "network_request": False},
    )
    session.commit()
    for row in created:
        session.refresh(row)
    return created


def process_mock_outbox(session: Session, user, outbox_id: int) -> OutboxSync:
    """Simulate an accepted response; this is deliberately not an HTTP client."""
    require_permission(user, "satusehat:manage")
    row = session.get(OutboxSync, outbox_id)
    if row is None or not row.is_demo:
        raise MockIntegrationError("Record outbox demo tidak ditemukan.")
    if row.status == "mock_accepted":
        return row
    if row.status not in {"queued", "failed"}:
        raise MockIntegrationError("Status outbox tidak dapat diproses dari status saat ini.")
    row.attempt_count += 1
    row.last_attempt_by = user.id
    row.status = "mock_accepted"
    row.response_summary = "MOCK_ACCEPTED — simulasi lokal saja; tidak ada request jaringan."
    row.last_error = None
    row.processed_at = utc_now()
    row.updated_at = utc_now()
    append_audit(
        session, user, "satusehat.mock_outbox_processed", "OutboxSync", row.id,
        {"resource_type": row.resource_type, "status": row.status, "attempt_count": row.attempt_count,
         "mode": "mock", "network_request": False, "payload_sha256": row.payload_sha256},
    )
    session.commit()
    session.refresh(row)
    return row


def list_outbox(session: Session, user) -> list[OutboxSync]:
    require_permission(user, "satusehat:read")
    rows = session.scalars(select(OutboxSync).where(OutboxSync.is_demo.is_(True))
                           .order_by(OutboxSync.created_at.desc(), OutboxSync.id.desc()).limit(200)).all()
    append_audit(session, user, "satusehat.outbox_list_read", "OutboxSync", "list", {"count": len(rows)})
    session.commit()
    return rows
