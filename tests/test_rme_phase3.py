"""Tes fase 3 untuk penetapan diagnosis, coding dan outbox mock tanpa jaringan."""
from __future__ import annotations

from datetime import date
import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import joinedload

os.environ.setdefault("APP_MODE", "demo")
os.environ.setdefault("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from rme.db import build_engine, initialize_database, session_factory
from rme.models import Diagnosis, OutboxSync, Patient, ResumeMedical, User, Visit
from rme.schemas import PatientCreate, ResumeInput, VisitCreate
from rme.security import SensitiveFieldCipher, require_permission
from rme.services import create_patient, create_visit, ensure_reference_data, finalize_resume, save_resume_draft, transition_visit
from rme.bootstrap import seed_users
from rme.diagnosis_service import DiagnosisWorkflowError, create_doctor_diagnosis, verify_diagnosis_code
from rme.integrations.satusehat.fhir import build_condition, build_composition, validate_fhir_resource
from rme.integrations.satusehat.service import MockIntegrationError, list_outbox, process_mock_outbox, queue_visit_for_mock
from rme.terminology import get_verified_icd10_term, load_icd10_terms, verified_icd10_terms


@pytest.fixture()
def context():
    engine = build_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = session_factory(engine)
    with factory() as session:
        ensure_reference_data(session)
        seed_users(session)
    with factory() as session:
        users = {u.username: u for u in session.scalars(select(User).options(joinedload(User.role))).all()}
    yield factory, SensitiveFieldCipher(os.environ["PII_ENCRYPTION_KEY"]), users
    engine.dispose()


def prepare_visit(context, *, data_consent=True, ai_consent=False):
    factory, cipher, users = context
    with factory() as session:
        patient = create_patient(
            session, users["pendaftaran_demo"], cipher,
            PatientCreate(
                name="Pasien Fiktif Fase Tiga", nik="3276010101901277",
                birth_date=date(1990, 1, 1), sex="Perempuan",
                occupation="Demo", education="Demo", religion="Belum diisi",
                marital_status="Belum diisi", allergies="Belum dikaji", is_demo=True,
            ),
            general_consent=True, data_consent=data_consent, ai_consent=ai_consent,
        )
        visit = create_visit(
            session, users["pendaftaran_demo"],
            VisitCreate(patient_id=patient.id, poli="Poli Umum", dpjp_user_id=users["dokter_demo"].id),
        )
        visit_id = visit.id
    with factory() as session:
        transition_visit(session, users["dokter_demo"], visit_id, "in-progress")
        diagnosis = create_doctor_diagnosis(
            session, users["dokter_demo"], visit_id,
            clinical_label="Diagnosis demo yang ditetapkan dokter",
            icd10_code="A41.9", confirmed=True,
        )
        diagnosis_id = diagnosis.id
    with factory() as session:
        verify_diagnosis_code(session, users["rekam_medis_demo"], diagnosis_id,
                              "Kode cocok dengan dokumentasi demo.")
    with factory() as session:
        resume = save_resume_draft(
            session, users["dokter_demo"], visit_id,
            ResumeInput(subjective="Keluhan demo.", objective="Pemeriksaan demo.",
                        assessment="Diagnosis demo.", plan="Rencana demo.", follow_up="Kontrol demo."),
        )
        resume_id = resume.id
        finalize_resume(session, users["dokter_demo"], resume_id)
        transition_visit(session, users["dokter_demo"], visit_id, "finished")
    return visit_id, diagnosis_id


def test_registry_is_explicit_about_edition_and_unverified_terms():
    terms = load_icd10_terms()
    assert terms
    assert all(term.edition == "2010" for term in terms)
    assert get_verified_icd10_term("A41.9") is not None
    assert get_verified_icd10_term("UNKNOWN") is None
    assert all(term.verified_source for term in verified_icd10_terms())


def test_only_manual_doctor_diagnosis_and_known_code_are_accepted(context):
    factory, _, users = context
    finished_visit_id, _ = prepare_visit(context)
    with factory() as session:
        finished = session.get(Visit, finished_visit_id)
        active = create_visit(
            session, users["pendaftaran_demo"],
            VisitCreate(patient_id=finished.patient_id, poli="Poli Umum", dpjp_user_id=users["dokter_demo"].id),
        )
        active_visit_id = active.id
    with factory() as session:
        transition_visit(session, users["dokter_demo"], active_visit_id, "in-progress")
    with factory() as session:
        with pytest.raises(PermissionError):
            create_doctor_diagnosis(session, users["perawat_demo"], active_visit_id,
                                    clinical_label="Diagnosis salah peran", icd10_code="A41.9", confirmed=True)
        with pytest.raises(DiagnosisWorkflowError):
            create_doctor_diagnosis(session, users["dokter_demo"], active_visit_id,
                                    clinical_label="Kode tidak dikenal", icd10_code="Z99.9", confirmed=True)
        rows = session.scalars(select(Diagnosis).where(Diagnosis.visit_id == active_visit_id)).all()
        assert len(rows) == 0

def test_coder_requires_note_and_only_confirmed_diagnosis_is_verifiable(context):
    factory, _, users = context
    finished_visit_id, diagnosis_id = prepare_visit(context)
    with factory() as session:
        with pytest.raises(DiagnosisWorkflowError):
            verify_diagnosis_code(session, users["rekam_medis_demo"], diagnosis_id, "no")
        assert session.get(Diagnosis, diagnosis_id).code_verified is True
        finished = session.get(Visit, finished_visit_id)
        active = create_visit(
            session, users["pendaftaran_demo"],
            VisitCreate(patient_id=finished.patient_id, poli="Poli Umum", dpjp_user_id=users["dokter_demo"].id),
        )
        active_visit_id = active.id
    with factory() as session:
        transition_visit(session, users["dokter_demo"], active_visit_id, "in-progress")
        provisional = create_doctor_diagnosis(
            session, users["dokter_demo"], active_visit_id, clinical_label="Hipotesis demo sementara",
            icd10_code="C47.0", confirmed=False,
        )
        with pytest.raises(DiagnosisWorkflowError):
            verify_diagnosis_code(session, users["rekam_medis_demo"], provisional.id,
                                  "Belum dikonfirmasi dokter.")

def test_mock_outbox_requires_data_sharing_consent_and_finalized_coded_visit(context):
    factory, _, users = context
    visit_id, _ = prepare_visit(context, data_consent=False)
    with factory() as session:
        with pytest.raises(MockIntegrationError, match="Persetujuan"):
            queue_visit_for_mock(session, users["rekam_medis_demo"], visit_id)
        assert session.scalar(select(OutboxSync.id)) is None


def test_mock_fhir_resources_are_validated_and_never_sent_to_network(context):
    factory, _, users = context
    visit_id, diagnosis_id = prepare_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        patient = session.get(Patient, visit.patient_id)
        resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit_id))
        diagnosis = session.get(Diagnosis, diagnosis_id)
        condition = build_condition(patient, visit, diagnosis)
        composition = build_composition(patient, visit, resume, [diagnosis])
        validate_fhir_resource(condition)
        validate_fhir_resource(composition)
        assert condition["resourceType"] == "Condition"
        assert condition["code"]["coding"][0]["system"] == "http://hl7.org/fhir/sid/icd-10"
        assert condition["subject"]["reference"].startswith("Patient/demo-")
        assert composition["status"] == "final"
        queued = queue_visit_for_mock(session, users["rekam_medis_demo"], visit_id)
        assert {row.resource_type for row in queued} == {"Condition", "Composition"}
        assert all(row.status == "queued" for row in queued)
        result = process_mock_outbox(session, users["rekam_medis_demo"], queued[0].id)
        assert result.status == "mock_accepted"
        assert "tidak ada request jaringan" in result.response_summary.lower()
        rows = list_outbox(session, users["rekam_medis_demo"])
        assert len(rows) == 2


def test_mock_outbox_idempotency_prevents_duplicate_payloads(context):
    factory, _, users = context
    visit_id, _ = prepare_visit(context)
    with factory() as session:
        first = queue_visit_for_mock(session, users["rekam_medis_demo"], visit_id)
    with factory() as session:
        second = queue_visit_for_mock(session, users["rekam_medis_demo"], visit_id)
        actual = session.scalars(select(OutboxSync).where(OutboxSync.visit_id == visit_id)).all()
        assert len(first) == 2 and len(second) == 2
        assert len(actual) == 2
        assert len({row.idempotency_key for row in actual}) == 2


def test_system_admin_has_no_default_clinical_or_satusehat_payload_access(context):
    _, _, users = context
    for permission in ("diagnosis:read", "satusehat:read", "satusehat:manage"):
        with pytest.raises(PermissionError):
            require_permission(users["admin_sistem_demo"], permission)
    # System administration remains available without clinical-data privileges.
    require_permission(users["admin_sistem_demo"], "registry:manage")
