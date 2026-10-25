"""Use-case diagnosis dokter dan verifikasi ICD-10 oleh Perekam Medis."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from rme.models import Diagnosis, Visit, utc_now
from rme.security import append_audit, require_permission
from rme.terminology import get_verified_icd10_term, verified_icd10_terms


class DiagnosisWorkflowError(ValueError):
    """Aturan diagnosis atau coding belum terpenuhi."""


def available_icd10_terms():
    return verified_icd10_terms()


def list_visit_diagnoses(session: Session, user, visit_id: int) -> list[Diagnosis]:
    require_permission(user, "diagnosis:read")
    visit = session.get(Visit, visit_id)
    if visit is None or not visit.is_demo:
        raise DiagnosisWorkflowError("Kunjungan demo tidak ditemukan.")
    rows = session.scalars(
        select(Diagnosis).where(Diagnosis.visit_id == visit_id).order_by(Diagnosis.created_at, Diagnosis.id)
    ).all()
    append_audit(session, user, "diagnosis.list_read", "Visit", visit_id, {"count": len(rows)})
    session.commit()
    return rows


def create_doctor_diagnosis(
    session: Session,
    user,
    visit_id: int,
    *,
    clinical_label: str,
    icd10_code: str,
    confirmed: bool,
) -> Diagnosis:
    """Create a new manual diagnosis. AI suggestion records are not accepted as input."""
    require_permission(user, "diagnosis:create")
    if not user.role or user.role.code != "dokter":
        raise DiagnosisWorkflowError("Diagnosis hanya dapat ditetapkan oleh dokter DPJP.")
    text = (clinical_label or "").strip()
    if len(text) < 3 or len(text) > 2000:
        raise DiagnosisWorkflowError("Diagnosis klinis harus berisi 3–2.000 karakter.")
    visit = session.get(Visit, visit_id)
    if visit is None or not visit.is_demo:
        raise DiagnosisWorkflowError("Kunjungan demo tidak ditemukan.")
    if visit.status != "in-progress":
        raise DiagnosisWorkflowError("Diagnosis hanya bisa dicatat saat kunjungan in-progress.")
    if visit.dpjp_user_id is not None and visit.dpjp_user_id != user.id:
        raise DiagnosisWorkflowError("Hanya DPJP kunjungan yang dapat menetapkan diagnosis.")
    term = get_verified_icd10_term(icd10_code)
    if term is None:
        raise DiagnosisWorkflowError("Kode tidak ada dalam registry ICD-10 edisi 2010 berstatus source-verified.")
    existing = session.scalar(
        select(Diagnosis).where(Diagnosis.visit_id == visit_id, Diagnosis.icd10_code == term.code)
    )
    if existing:
        raise DiagnosisWorkflowError("Kode ICD-10 tersebut sudah tercatat pada kunjungan ini.")
    row = Diagnosis(
        visit_id=visit_id,
        clinical_label=text,
        icd10_code=term.code,
        icd10_display=term.display,
        icd10_edition=term.edition,
        status="confirmed" if confirmed else "provisional",
        diagnosis_set_by=user.id,
        code_verified=False,
        is_demo=True,
    )
    session.add(row)
    session.flush()
    append_audit(
        session, user, "diagnosis.created", "Diagnosis", row.id,
        {"visit_id": visit_id, "icd10_code": row.icd10_code, "status": row.status,
         "source": "manual_doctor_entry", "ai_suggestion_linked": False},
    )
    session.commit()
    session.refresh(row)
    return row


def verify_diagnosis_code(session: Session, user, diagnosis_id: int, note: str) -> Diagnosis:
    """The medical-record coder independently confirms code-to-documentation appropriateness."""
    require_permission(user, "icd:verify")
    if not user.role or user.role.code != "perekam_medis":
        raise DiagnosisWorkflowError("Verifikasi kode memerlukan peran Perekam Medis.")
    rationale = (note or "").strip()
    if len(rationale) < 5 or len(rationale) > 2000:
        raise DiagnosisWorkflowError("Catatan verifikasi wajib 5–2.000 karakter.")
    row = session.get(Diagnosis, diagnosis_id)
    if row is None or not row.is_demo:
        raise DiagnosisWorkflowError("Diagnosis demo tidak ditemukan.")
    if row.status != "confirmed":
        raise DiagnosisWorkflowError("Diagnosis provisional belum dapat diverifikasi atau dikirim.")
    term = get_verified_icd10_term(row.icd10_code)
    if term is None or term.display != row.icd10_display or term.edition != row.icd10_edition:
        raise DiagnosisWorkflowError("Kode atau edisi tidak cocok dengan registry sumber yang ditinjau.")
    row.code_verified = True
    row.code_verified_by = user.id
    row.code_verified_at = utc_now()
    row.code_verification_note = rationale
    row.updated_at = utc_now()
    append_audit(
        session, user, "diagnosis.icd10_verified", "Diagnosis", row.id,
        {"icd10_code": row.icd10_code, "edition": row.icd10_edition, "verified": True,
         "note_length": len(rationale)},
    )
    session.commit()
    session.refresh(row)
    return row
