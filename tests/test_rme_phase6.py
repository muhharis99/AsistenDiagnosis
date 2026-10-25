"""Phase 6: outpatient Encounter, vital-sign Observation, ClinicalImpression, dependencies."""
from __future__ import annotations

from datetime import date
import json
import os
import uuid

import pytest
import requests
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import joinedload

os.environ.setdefault("APP_MODE", "demo")
os.environ.setdefault("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from rme.bootstrap import seed_users
from rme.db import build_engine, initialize_database, session_factory
from rme.diagnosis_service import create_doctor_diagnosis, verify_diagnosis_code
from rme.integrations.satusehat.client import SATUSEHATClient
from rme.integrations.satusehat.fhir import (
    build_clinical_impression, build_encounter_update, build_vital_observations,
    validate_fhir_resource, validate_sandbox_resource,
)
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError, prepare_sandbox_payload, queue_visit_phase6_resources,
    transmit_outbox_item_sandbox,
)
from rme.integrations.satusehat.mapping import upsert_satusehat_mapping, verify_satusehat_mapping
from rme.models import Anamnesis, AuditLog, Diagnosis, OutboxSync, Patient, ResumeMedical, SATUSEHATTransmission, User, Visit, VitalSigns
from rme.schemas import AnamnesisInput, PatientCreate, ResumeInput, VitalSignsInput, VisitCreate
from rme.security import SensitiveFieldCipher
from rme.services import (
    create_patient, create_visit, ensure_reference_data, finalize_resume,
    save_anamnesis, save_resume_draft, save_vitals, transition_visit,
)


GOOD_ENV = {
    "APP_MODE": "demo",
    "SATUSEHAT_MODE": "sandbox",
    "SATUSEHAT_ENABLE_NETWORK": "true",
    "SATUSEHAT_CLIENT_ID": "sandbox-client",
    "SATUSEHAT_CLIENT_SECRET": "not-a-real-secret",
    "SATUSEHAT_ORG_IHS_ID": "100000004",
    "SATUSEHAT_BASE_URL": "https://api-satusehat-stg.dto.kemkes.go.id/fhir-r4/v1",
    "SATUSEHAT_TOKEN_URL": "https://api-satusehat-stg.dto.kemkes.go.id/oauth2/v1/accesstoken",
    "SATUSEHAT_TLS_VERIFY": "true",
}


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code, self.payload, self.headers = status_code, payload, headers or {}
    def json(self):
        return self.payload


class FakeTransport:
    def __init__(self):
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url == GOOD_ENV["SATUSEHAT_TOKEN_URL"]:
            return FakeResponse(200, {"access_token": "fake-token", "token_type": "BearerToken", "expires_in": 300})
        if method == "PUT" and "/Encounter/" in url:
            return FakeResponse(200, {"resourceType": "Encounter", "id": url.rsplit("/", 1)[-1]})
        if method == "POST":
            kind = url.rsplit("/", 1)[-1]
            return FakeResponse(201, {"resourceType": kind, "id": str(uuid.uuid4())})
        raise AssertionError(f"Unexpected fake request: {method} {url}")


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


def create_finished_visit(context):
    factory, cipher, users = context
    with factory() as session:
        patient = create_patient(
            session, users["pendaftaran_demo"], cipher,
            PatientCreate(
                name="Pasien Fiktif Fase Enam", nik="3276010101901293",
                birth_date=date(1990, 1, 1), sex="Perempuan",
                occupation="Demo", education="Demo", religion="Belum diisi",
                marital_status="Belum diisi", allergies="Belum dikaji", is_demo=True,
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
        save_anamnesis(
            session, users["perawat_demo"], visit_id,
            AnamnesisInput(
                chief_complaint="Keluhan sintetis.",
                associated_symptoms="Gejala simulasi.",
                personal_history="Riwayat simulasi.",
                family_history="Tidak dicatat dalam sampel.",
            ),
        )
        save_vitals(
            session, users["perawat_demo"], visit_id,
            VitalSignsInput(
                systolic_mmhg=120, diastolic_mmhg=80, pulse_per_min=78,
                respiration_per_min=16, temperature_c=36.7, spo2_percent=98,
                weight_kg=65.0, height_cm=170.0,
            ),
        )
        diagnosis = create_doctor_diagnosis(
            session, users["dokter_demo"], visit_id,
            clinical_label="Diagnosis fiktif yang ditetapkan dokter",
            icd10_code="A41.9", confirmed=True,
        )
        verify_diagnosis_code(session, users["rekam_medis_demo"], diagnosis.id,
                              "Kode ditinjau sesuai dokumentasi fiktif.")
        resume = save_resume_draft(
            session, users["dokter_demo"], visit_id,
            ResumeInput(subjective="Keluhan sintetis.", objective="Pemeriksaan sintetis.",
                        assessment="Asesmen dokter sintetis.", plan="Rencana sintetis.", follow_up="Kontrol sintetis."),
        )
        finalize_resume(session, users["dokter_demo"], resume.id)
        transition_visit(session, users["dokter_demo"], visit_id, "finished")
    return visit_id


def add_mapping(session, admin, resource_type, local_key, external_id):
    row = upsert_satusehat_mapping(
        session, admin, resource_type=resource_type, local_key=str(local_key),
        external_id=external_id, source="Dokumentasi atau respons resmi sandbox.",
    )
    return verify_satusehat_mapping(
        session, admin, row.id, "ID telah dibandingkan dengan respons sandbox sumber berwenang."
    )


def map_visit(context, visit_id, *, include_vitals_performer=True):
    factory, _, users = context
    with factory() as session:
        visit = session.get(Visit, visit_id)
        patient = session.get(Patient, visit.patient_id)
        vitals = session.scalar(select(VitalSigns).where(VitalSigns.visit_id == visit_id))
        add_mapping(session, users["admin_sistem_demo"], "Patient", patient.id, "100000030009")
        add_mapping(session, users["admin_sistem_demo"], "Encounter", visit.id, str(uuid.uuid4()))
        add_mapping(session, users["admin_sistem_demo"], "Practitioner", visit.dpjp_user_id, "N10000001")
        if include_vitals_performer:
            add_mapping(session, users["admin_sistem_demo"], "Practitioner", vitals.recorded_by, "N10000002")
        add_mapping(session, users["admin_sistem_demo"], "Organization", visit.facility_id, GOOD_ENV["SATUSEHAT_ORG_IHS_ID"])
        add_mapping(session, users["admin_sistem_demo"], "Location",
                    f"{visit.facility_id}:{visit.poli.casefold()}", str(uuid.uuid4()))


def test_vital_observations_use_loinc_and_do_not_include_patient_pii(context):
    factory, _, _ = context
    visit_id = create_finished_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        patient = session.get(Patient, visit.patient_id)
        vitals = session.scalar(select(VitalSigns).where(VitalSigns.visit_id == visit_id))
        observations = build_vital_observations(patient, visit, vitals)
        assert observations
        assert all(item["resourceType"] == "Observation" for item in observations)
        loinc_codes = {
            coding["code"]
            for item in observations
            for coding in (item.get("code", {}).get("coding") or [])
        }
        assert {"85354-9", "8867-4", "9279-1", "8310-5", "59408-5", "29463-7", "8302-2"} <= loinc_codes
        serialized = json.dumps(observations, ensure_ascii=False)
        assert "3276010101901293" not in serialized
        assert patient.name_ciphertext not in serialized
        assert all(item["effectiveDateTime"].endswith("Z") for item in observations)
        for item in observations:
            validate_fhir_resource(item)


def test_phase6_queue_is_idempotent_and_contains_required_resource_types(context):
    factory, _, users = context
    visit_id = create_finished_visit(context)
    with factory() as session:
        first = queue_visit_phase6_resources(session, users["rekam_medis_demo"], visit_id)
    with factory() as session:
        second = queue_visit_phase6_resources(session, users["rekam_medis_demo"], visit_id)
        all_rows = session.scalars(select(OutboxSync).where(
            OutboxSync.idempotency_key.like(f"phase6:%visit-{visit_id}%")
        )).all()
        assert len(first) == len(second) == len(all_rows)
        types = {row.resource_type for row in first}
        assert {"Condition", "Observation", "ClinicalImpression", "Encounter", "Composition"} <= types
        assert all(row.status == "queued" for row in first)
        assert all(row.payload_sha256 and len(row.payload_sha256) == 64 for row in first)
        assert all(row.is_demo for row in first)


def test_observation_blocked_when_vitals_performer_mapping_is_missing(context):
    factory, _, users = context
    visit_id = create_finished_visit(context)
    map_visit(context, visit_id, include_vitals_performer=False)
    with factory() as session:
        rows = queue_visit_phase6_resources(session, users["rekam_medis_demo"], visit_id)
        observation = next(row for row in rows if row.resource_type == "Observation")
        client = SATUSEHATClient(GOOD_ENV, transport=FakeTransport())
        with pytest.raises(SATUSEHATWorkflowError, match="Practitioner"):
            prepare_sandbox_payload(session, users["rekam_medis_demo"], observation.id, client)


def test_phase6_transmits_observations_clinical_impression_and_updates_mapped_encounter(context):
    factory, _, users = context
    visit_id = create_finished_visit(context)
    map_visit(context, visit_id)
    with factory() as session:
        outbox = queue_visit_phase6_resources(session, users["rekam_medis_demo"], visit_id)
        outbox_by_type = {}
        for row in outbox:
            outbox_by_type.setdefault(row.resource_type, []).append(row.id)
    transport = FakeTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    order = ["Condition", "Observation", "ClinicalImpression", "Encounter", "Composition"]
    for resource_type in order:
        with factory() as session:
            ids = outbox_by_type.get(resource_type, [])
            if resource_type == "Observation":
                rows = ids
            else:
                rows = ids[:1]
            for outbox_id in rows:
                sent = transmit_outbox_item_sandbox(
                    session, users["rekam_medis_demo"], outbox_id,
                    client=client, confirmed_demo_only=True,
                )
                assert sent.status == "succeeded", (resource_type, sent.response_summary)

    methods_and_paths = [(method, url) for method, url, _ in transport.calls]
    assert any(method == "PUT" and "/Encounter/" in url for method, url in methods_and_paths)
    assert any(method == "POST" and url.endswith("/Observation") for method, url in methods_and_paths)
    assert any(method == "POST" and url.endswith("/ClinicalImpression") for method, url in methods_and_paths)
    encounter_call = next(call for call in transport.calls if call[0] == "PUT" and "/Encounter/" in call[1])
    payload = encounter_call[2]["json"]
    assert payload["id"] == encounter_call[1].rsplit("/", 1)[-1]
    assert payload["diagnosis"][0]["condition"]["reference"].startswith("Condition/")
    composition_call = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/Composition"))
    composition = composition_call[2]["json"]
    physical = next(section for section in composition["section"] if section["title"] == "Pemeriksaan Fisik")
    assert any(entry["reference"].startswith("Observation/") for entry in physical.get("entry", []))
    history = next(section for section in composition["section"] if section["title"] == "Anamnesis")
    assert any(entry["reference"].startswith("ClinicalImpression/") for entry in history.get("entry", []))
    assert "example.invalid" not in json.dumps([payload, composition])


def test_clinical_impression_is_based_on_clinician_text_not_ai_suggestion(context):
    factory, _, _ = context
    visit_id = create_finished_visit(context)
    with factory() as session:
        visit = session.get(Visit, visit_id)
        patient = session.get(Patient, visit.patient_id)
        resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit_id))
        anamnesis = session.scalar(select(Anamnesis).where(Anamnesis.visit_id == visit_id))
        vitals = session.scalar(select(VitalSigns).where(VitalSigns.visit_id == visit_id))
        diagnoses = session.scalars(select(Diagnosis).where(Diagnosis.visit_id == visit_id)).all()
        observations = build_vital_observations(patient, visit, vitals)
        impression = build_clinical_impression(patient, visit, anamnesis, resume, diagnoses, observations)
        assert impression["resourceType"] == "ClinicalImpression"
        assert "Keluhan utama: Keluhan sintetis." in impression["summary"]
        assert impression["finding"][0]["itemCodeableConcept"]["coding"][0]["code"] == "A41.9"
        assert not any("AI" in str(value) for value in impression.values())
        validate_fhir_resource(impression)
