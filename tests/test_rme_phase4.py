"""Tests for fail-closed SATUSEHAT sandbox preparation and identity mapping."""
from __future__ import annotations

from datetime import date
import os
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import joinedload

os.environ.setdefault("APP_MODE", "demo")
os.environ.setdefault("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from rme.bootstrap import seed_users
from rme.db import build_engine, initialize_database, session_factory
from rme.diagnosis_service import create_doctor_diagnosis, verify_diagnosis_code
from rme.integrations.satusehat.fhir import build_condition, validate_sandbox_resource
from rme.integrations.satusehat.mapping import (
    MappingWorkflowError,
    build_visit_sandbox_preflight,
    sandbox_configuration_checks,
    upsert_satusehat_mapping,
    verify_satusehat_mapping,
)
from rme.models import Diagnosis, Patient, User, Visit
from rme.schemas import PatientCreate, ResumeInput, VisitCreate
from rme.security import SensitiveFieldCipher, require_permission
from rme.services import create_patient, create_visit, ensure_reference_data, finalize_resume, save_resume_draft, transition_visit


GOOD_ENV = {
    "APP_MODE": "demo",
    "SATUSEHAT_MODE": "sandbox",
    "SATUSEHAT_CLIENT_ID": "sandbox-client",
    "SATUSEHAT_CLIENT_SECRET": "never-print-this-secret",
    "SATUSEHAT_ORG_IHS_ID": "100000004",
    "SATUSEHAT_BASE_URL": "https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1",
    "SATUSEHAT_TOKEN_URL": "https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken",
    "SATUSEHAT_TLS_VERIFY": "true",
}


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


def create_ready_visit(context):
    factory, cipher, users = context
    with factory() as session:
        patient = create_patient(
            session, users["pendaftaran_demo"], cipher,
            PatientCreate(
                name="Pasien Fiktif Fase Empat", nik="3276010101901285",
                birth_date=date(1990, 1, 1), sex="Laki-laki", occupation="Demo",
                education="Demo", religion="Belum diisi", marital_status="Belum diisi",
                allergies="Belum dikaji", is_demo=True,
            ),
            general_consent=True, data_consent=True, ai_consent=False,
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
        verify_diagnosis_code(session, users["rekam_medis_demo"], diagnosis.id,
                              "Diperiksa terhadap dokumentasi demo.")
        resume = save_resume_draft(
            session, users["dokter_demo"], visit_id,
            ResumeInput(subjective="Keluhan demo.", objective="Temuan demo.",
                        assessment="Asesmen dokter demo.", plan="Rencana demo.", follow_up="Kontrol demo."),
        )
        finalize_resume(session, users["dokter_demo"], resume.id)
        transition_visit(session, users["dokter_demo"], visit_id, "finished")
    return visit_id


def add_mapping(session, admin, *, resource_type, local_key, external_id):
    row = upsert_satusehat_mapping(
        session, admin, resource_type=resource_type, local_key=str(local_key),
        external_id=external_id, source="Dokumentasi resmi atau respons API sandbox.",
    )
    return verify_satusehat_mapping(
        session, admin, row.id,
        "ID dibandingkan kembali dengan sumber sandbox yang berwenang.",
    )


def test_sandbox_config_fails_closed_and_never_echoes_secret():
    checks = sandbox_configuration_checks({"SATUSEHAT_MODE": "mock", "SATUSEHAT_CLIENT_SECRET": "hidden"})
    assert not all(item["passed"] for item in checks)
    rendered = " ".join(str(item["detail"]) for item in checks)
    assert "hidden" not in rendered
    assert "never-print-this-secret" not in rendered


def test_configuration_accepts_only_allowlisted_staging_endpoints():
    checks = sandbox_configuration_checks(GOOD_ENV)
    assert all(item["passed"] for item in checks)
    bad = dict(GOOD_ENV, SATUSEHAT_BASE_URL="https://example.org/fhir")
    assert not next(item for item in sandbox_configuration_checks(bad) if item["item"] == "FHIR base URL staging")["passed"]
    bad_tls = dict(GOOD_ENV, SATUSEHAT_TLS_VERIFY="false")
    assert not next(item for item in sandbox_configuration_checks(bad_tls) if item["item"] == "Verifikasi TLS aktif")["passed"]


def test_mapping_is_permissioned_unverified_by_default_and_verification_is_a_separate_step(context):
    factory, _, users = context
    with factory() as session:
        with pytest.raises(PermissionError):
            upsert_satusehat_mapping(session, users["dokter_demo"], resource_type="Patient",
                                     local_key="1", external_id="100000030009",
                                     source="Dokumentasi resmi sandbox mapping.")
        saved = upsert_satusehat_mapping(
            session, users["admin_sistem_demo"], resource_type="Patient", local_key="1",
            external_id="100000030009", source="Dokumentasi resmi sandbox mapping.",
        )
        assert saved.verified is False
        with pytest.raises(MappingWorkflowError):
            verify_satusehat_mapping(session, users["admin_sistem_demo"], saved.id, "pendek")
        verified = verify_satusehat_mapping(
            session, users["admin_sistem_demo"], saved.id,
            "ID dicocokkan dengan output master Patient sandbox.",
        )
        assert verified.verified is True


def test_updating_a_mapping_invalidates_its_verification(context):
    factory, _, users = context
    with factory() as session:
        row = add_mapping(session, users["admin_sistem_demo"], resource_type="Patient",
                          local_key="9", external_id="100000030009")
        updated = upsert_satusehat_mapping(
            session, users["admin_sistem_demo"], resource_type="Patient", local_key="9",
            external_id="100000030010", source="Dokumentasi resmi sandbox terbaru.",
        )
        assert updated.id == row.id
        assert updated.verified is False
        assert updated.verified_by is None


@pytest.mark.parametrize("external_id", ["demo-patient-1", "abc.example", "foo.invalid", "bad id", ""])
def test_mapping_rejects_demo_or_malformed_ids(context, external_id):
    factory, _, users = context
    with factory() as session:
        with pytest.raises(MappingWorkflowError):
            upsert_satusehat_mapping(
                session, users["admin_sistem_demo"], resource_type="Patient", local_key="1",
                external_id=external_id, source="Dokumentasi resmi sandbox mapping.",
            )


def test_preflight_blocks_when_mappings_are_missing_and_never_enables_network(context):
    factory, _, users = context
    visit_id = create_ready_visit(context)
    with factory() as session:
        result = build_visit_sandbox_preflight(session, users["rekam_medis_demo"], visit_id, GOOD_ENV)
        assert result["ready"] is False
        assert result["network_calls_enabled"] is False
        assert any(not item["passed"] for item in result["checks"])
        assert "tidak ada" in result["notice"].lower()


def test_preflight_passes_only_when_all_configuration_clinical_and_mapping_checks_pass(context):
    factory, _, users = context
    visit_id = create_ready_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        add_mapping(session, users["admin_sistem_demo"], resource_type="Patient",
                    local_key=visit.patient_id, external_id="100000030009")
        add_mapping(session, users["admin_sistem_demo"], resource_type="Encounter",
                    local_key=visit.id, external_id=str(uuid.uuid4()))
        add_mapping(session, users["admin_sistem_demo"], resource_type="Practitioner",
                    local_key=visit.dpjp_user_id, external_id="N10000001")
        add_mapping(session, users["admin_sistem_demo"], resource_type="Organization",
                    local_key=visit.facility_id, external_id=GOOD_ENV["SATUSEHAT_ORG_IHS_ID"])
        add_mapping(session, users["admin_sistem_demo"], resource_type="Location",
                    local_key=f"{visit.facility_id}:{visit.poli.casefold()}", external_id=str(uuid.uuid4()))
    with factory() as session:
        result = build_visit_sandbox_preflight(session, users["rekam_medis_demo"], visit_id, GOOD_ENV)
        assert result["ready"] is True
        assert result["network_calls_enabled"] is False
        assert all(item["passed"] for item in result["checks"])


def test_organization_id_mapping_must_match_configured_parent_ihs(context):
    factory, _, users = context
    visit_id = create_ready_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        add_mapping(session, users["admin_sistem_demo"], resource_type="Organization",
                    local_key=visit.facility_id, external_id="1000000999")
    with factory() as session:
        result = build_visit_sandbox_preflight(session, users["rekam_medis_demo"], visit_id, GOOD_ENV)
        assert not next(item for item in result["checks"] if item["item"] == "Mapping Organization")["passed"]


def test_admin_system_can_manage_mapping_but_not_clinical_or_outbox_payload_access(context):
    _, _, users = context
    require_permission(users["admin_sistem_demo"], "satusehat:mapping:manage")
    with pytest.raises(PermissionError):
        require_permission(users["admin_sistem_demo"], "satusehat:read")
    with pytest.raises(PermissionError):
        require_permission(users["admin_sistem_demo"], "diagnosis:read")


def test_sandbox_fhir_guard_rejects_phase3_mock_payload(context):
    factory, cipher, users = context
    visit_id = create_ready_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        diagnosis = session.scalar(select(Diagnosis).where(Diagnosis.visit_id == visit_id))
        patient = session.get(Patient, visit.patient_id)
        mock_payload = build_condition(patient, visit, diagnosis)
        with pytest.raises(ValueError, match="placeholder"):
            validate_sandbox_resource(mock_payload)
