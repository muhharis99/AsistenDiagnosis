"""Tests for opt-in OAuth, MPI search and one-at-a-time sandbox transmission."""
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
from rme.integrations.satusehat.client import SATUSEHATClient, SATUSEHATClientError
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    search_demo_patient_mpi,
    transmit_outbox_item_sandbox,
)
from rme.integrations.satusehat.mapping import upsert_satusehat_mapping, verify_satusehat_mapping
from rme.integrations.satusehat.service import queue_visit_for_mock
from rme.models import AuditLog, OutboxSync, Patient, SATUSEHATTransmission, User, Visit
from rme.schemas import PatientCreate, ResumeInput, VisitCreate
from rme.security import SensitiveFieldCipher
from rme.services import create_patient, create_visit, ensure_reference_data, finalize_resume, save_resume_draft, transition_visit
from rme.diagnosis_service import create_doctor_diagnosis, verify_diagnosis_code


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
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload


class FakeTransport:
    def __init__(self, *, fail_post=False, post_status=201):
        self.calls = []
        self.fail_post = fail_post
        self.post_status = post_status
        self.post_index = 0

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url == GOOD_ENV["SATUSEHAT_TOKEN_URL"]:
            return FakeResponse(200, {
                "access_token": "mock-bearer-token",
                "token_type": "BearerToken",
                "expires_in": 300,
            })
        if method == "GET" and url.endswith("/Patient"):
            return FakeResponse(200, {
                "resourceType": "Bundle", "type": "searchset", "total": 1,
                "entry": [{"resource": {"resourceType": "Patient", "id": "100000030009",
                                       "name": [{"text": "DATA UJI FIKTIF"}]}}],
            })
        if method == "POST":
            self.post_index += 1
            if self.fail_post:
                raise requests.Timeout("transport timeout; do not expose")
            if self.post_status >= 400:
                return FakeResponse(self.post_status, {
                    "resourceType": "OperationOutcome",
                    "issue": [{"severity": "error", "code": "business-rule",
                               "diagnostics": "do not log private diagnostics"}],
                })
            new_id = str(uuid.uuid4())
            return FakeResponse(self.post_status, {"resourceType": url.rsplit("/", 1)[-1], "id": new_id})
        raise AssertionError(f"Unexpected fake request: {method} {url}")


class FakeMPIClient:
    network_enabled = True
    mode = "sandbox"

    def __init__(self):
        self.seen_nik = None

    def search_patient_by_nik(self, nik):
        from rme.integrations.satusehat.client import ApiResponse
        self.seen_nik = nik
        return ApiResponse(200, {
            "resourceType": "Bundle", "type": "searchset", "total": 1,
            "entry": [{"resource": {"resourceType": "Patient", "id": "100000030009"}}],
        }, {})


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


def prepare_outbox(context):
    factory, cipher, users = context
    with factory() as session:
        patient = create_patient(
            session, users["pendaftaran_demo"], cipher,
            PatientCreate(
                name="Pasien Fiktif Fase Lima", nik="3276010101901277",
                birth_date=date(1990, 1, 1), sex="Perempuan", occupation="Demo",
                education="Demo", religion="Belum diisi", marital_status="Belum diisi",
                allergies="Belum dikaji", is_demo=True,
            ),
            general_consent=True, data_consent=True, ai_consent=False,
        )
        patient_id = patient.id
        visit = create_visit(
            session, users["pendaftaran_demo"],
            VisitCreate(patient_id=patient.id, poli="Poli Umum", dpjp_user_id=users["dokter_demo"].id),
        )
        visit_id = visit.id
    with factory() as session:
        transition_visit(session, users["dokter_demo"], visit_id, "in-progress")
        diagnosis = create_doctor_diagnosis(
            session, users["dokter_demo"], visit_id,
            clinical_label="Diagnosis simulasi yang ditetapkan dokter",
            icd10_code="A41.9", confirmed=True,
        )
        verify_diagnosis_code(session, users["rekam_medis_demo"], diagnosis.id,
                              "Kode sesuai dokumentasi simulasi.")
        resume = save_resume_draft(
            session, users["dokter_demo"], visit_id,
            ResumeInput(subjective="Keluhan simulasi.", objective="Temuan simulasi.",
                        assessment="Asesmen simulasi.", plan="Rencana simulasi.", follow_up="Kontrol simulasi."),
        )
        finalize_resume(session, users["dokter_demo"], resume.id)
        transition_visit(session, users["dokter_demo"], visit_id, "finished")
    with factory() as session:
        outbox = queue_visit_for_mock(session, users["rekam_medis_demo"], visit_id)
        outbox_ids = {row.resource_type: row.id for row in outbox}
    return patient_id, visit_id, outbox_ids


def add_verified_mapping(session, admin, resource_type, local_key, external_id):
    row = upsert_satusehat_mapping(
        session, admin, resource_type=resource_type, local_key=str(local_key),
        external_id=external_id, source="Dokumentasi atau respons resmi sandbox.",
    )
    return verify_satusehat_mapping(
        session, admin, row.id, "ID diverifikasi kembali terhadap respons sandbox resmi."
    )


def map_visit(context, visit_id):
    factory, _, users = context
    with factory() as session:
        visit = session.get(Visit, visit_id)
        add_verified_mapping(session, users["admin_sistem_demo"], "Patient", visit.patient_id, "100000030009")
        add_verified_mapping(session, users["admin_sistem_demo"], "Encounter", visit.id, str(uuid.uuid4()))
        add_verified_mapping(session, users["admin_sistem_demo"], "Practitioner", visit.dpjp_user_id, "N10000001")
        add_verified_mapping(session, users["admin_sistem_demo"], "Organization", visit.facility_id, GOOD_ENV["SATUSEHAT_ORG_IHS_ID"])
        add_verified_mapping(session, users["admin_sistem_demo"], "Location",
                             f"{visit.facility_id}:{visit.poli.casefold()}", str(uuid.uuid4()))


def test_client_requires_explicit_sandbox_network_opt_in_and_never_allows_production():
    with pytest.raises(SATUSEHATClientError, match="nonaktif"):
        SATUSEHATClient(dict(GOOD_ENV, SATUSEHAT_ENABLE_NETWORK="false"))
    with pytest.raises(SATUSEHATClientError, match="staging"):
        SATUSEHATClient(dict(GOOD_ENV, SATUSEHAT_BASE_URL="https://api-satusehat.kemkes.go.id/fhir-r4/v1"))
    with pytest.raises(SATUSEHATClientError, match="TLS"):
        SATUSEHATClient(dict(GOOD_ENV, SATUSEHAT_TLS_VERIFY="false"))


def test_oauth_uses_client_credentials_tls_and_no_redirects():
    transport = FakeTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    assert client.obtain_access_token() == "mock-bearer-token"
    assert client.obtain_access_token() == "mock-bearer-token"
    assert len(transport.calls) == 1
    method, url, kwargs = transport.calls[0]
    assert (method, url) == ("POST", GOOD_ENV["SATUSEHAT_TOKEN_URL"])
    assert kwargs["params"] == {"grant_type": "client_credentials"}
    assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
    assert kwargs["data"]["client_secret"] == GOOD_ENV["SATUSEHAT_CLIENT_SECRET"]


def test_mpi_search_uses_documented_identifier_and_only_exposes_patient_ids():
    transport = FakeTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    response = client.search_patient_by_nik("3276010101901277")
    request = next(call for call in transport.calls if call[0] == "GET")
    assert request[1].endswith("/Patient")
    assert request[2]["params"]["identifier"] == "https://fhir.kemkes.go.id/id/nik|3276010101901277"
    assert response.payload["resourceType"] == "Bundle"
    with pytest.raises(SATUSEHATClientError):
        client.search_patient_by_nik("not-a-valid-nik")


def test_mpi_service_requires_demo_consent_and_does_not_audit_nik(context):
    factory, cipher, users = context
    patient_id, _, _ = prepare_outbox(context)
    fake = FakeMPIClient()
    with factory() as session:
        result = search_demo_patient_mpi(
            session, users["rekam_medis_demo"], patient_id, cipher,
            confirmed_demo_only=True, client=fake,
        )
        assert result == {"total": 1, "matches": [{"resourceType": "Patient", "id": "100000030009"}], "ambiguous": False}
    with factory() as session:
        logs = session.scalars(select(AuditLog).where(AuditLog.action == "satusehat.mpi_patient_search")).all()
        assert len(logs) == 1
        assert "3276010101901277" not in logs[0].details_json
    assert fake.seen_nik == "3276010101901277"
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="Konfirmasi"):
            search_demo_patient_mpi(
                session, users["rekam_medis_demo"], patient_id, cipher,
                confirmed_demo_only=False, client=fake,
            )


def test_outbox_condition_then_composition_is_posted_once_and_uses_verified_ids(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = FakeTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)

    with factory() as session:
        condition = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert condition.status == "succeeded"
        assert condition.external_resource_id
        assert condition.http_status == 201
    post_call = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/Condition"))
    condition_payload = post_call[2]["json"]
    assert "id" not in condition_payload
    assert condition_payload["subject"]["reference"] == "Patient/100000030009"
    assert condition_payload["identifier"][0]["system"] == "http://sys-ids.kemkes.go.id/condition/100000004"
    assert post_call[2]["headers"]["Content-Type"] == "application/json"

    with factory() as session:
        composition = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Composition"],
            client=client, confirmed_demo_only=True,
        )
        assert composition.status == "succeeded"
        assert composition.external_resource_id
    composition_call = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/Composition"))
    payload = composition_call[2]["json"]
    assert "id" not in payload
    assert payload["type"]["coding"][0]["code"] == "88645-7"
    assert payload["category"][0]["coding"][0]["code"] == "LP173421-1"
    diagnosis_section = next(section for section in payload["section"] if section["title"] == "Diagnosis")
    assert diagnosis_section["entry"][0]["reference"].startswith("Condition/")
    assert "example.invalid" not in json.dumps(payload)
    # Retrying a completed transmission is idempotent and does not POST again.
    posts_before = len([call for call in transport.calls if call[0] == "POST" and "/fhir-r4/" in call[1]])
    with factory() as session:
        again = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert again.status == "succeeded"
    posts_after = len([call for call in transport.calls if call[0] == "POST" and "/fhir-r4/" in call[1]])
    assert posts_after == posts_before


def test_transport_timeout_is_uncertain_and_not_automatically_retried(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = FakeTransport(fail_post=True)
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    with factory() as session:
        row = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert row.status == "uncertain"
    posts_before = len([call for call in transport.calls if call[0] == "POST" and "/fhir-r4/" in call[1]])
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="rekonsiliasi manual"):
            transmit_outbox_item_sandbox(
                session, users["rekam_medis_demo"], outbox_ids["Condition"],
                client=client, confirmed_demo_only=True,
            )
    posts_after = len([call for call in transport.calls if call[0] == "POST" and "/fhir-r4/" in call[1]])
    assert posts_after == posts_before == 1


def test_http_4xx_operation_outcome_codes_are_recorded_without_diagnostics(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = FakeTransport(post_status=422)
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    with factory() as session:
        row = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert row.status == "failed"
        assert json.loads(row.operation_outcome_codes_json) == ["business-rule"]
        assert "do not log private diagnostics" not in row.response_summary
