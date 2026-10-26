"""Phase 7H contract tests for safe FHIR payloads and failure recovery."""
from __future__ import annotations

import copy

import pytest
import requests

from rme.integrations.satusehat.fhir import validate_sandbox_resource
from rme.integrations.satusehat.client import SATUSEHATClient
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    transmit_outbox_item_sandbox,
)
from rme.models import SATUSEHATTransmission
from sqlalchemy import select

from test_rme_phase5 import (
    GOOD_ENV,
    FakeResponse,
    FakeTransport,
    context,
    map_visit,
    prepare_outbox,
)


PATIENT_REF = "Patient/100000030009"
PRACTITIONER_REF = "Practitioner/N10000001"
ORGANIZATION_REF = "Organization/100000004"
LOCATION_REF = "Location/location-contract-1"
ENCOUNTER_REF = "Encounter/encounter-contract-1"
CONDITION_REF = "Condition/condition-contract-1"
OBSERVATION_REF = "Observation/observation-contract-1"


@pytest.fixture()
def valid_resources():
    """FHIR R4-shaped payloads using synthetic server-style identifiers only."""
    return {
        "Condition": {
            "resourceType": "Condition",
            "identifier": [{
                "use": "official",
                "system": "http://sys-ids.kemkes.go.id/condition/100000004",
                "value": "diagnosis-contract-1",
            }],
            "clinicalStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code": "active",
            }]},
            "verificationStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                "code": "confirmed",
            }]},
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code": "encounter-diagnosis",
            }]}],
            "code": {"coding": [{
                "system": "http://hl7.org/fhir/sid/icd-10",
                "code": "A41.9",
                "display": "Synthetic diagnosis",
            }]},
            "subject": {"reference": PATIENT_REF},
            "encounter": {"reference": ENCOUNTER_REF},
            "recorder": {"reference": PRACTITIONER_REF},
            "recordedDate": "2026-01-01T00:00:00Z",
        },
        "Composition": {
            "resourceType": "Composition",
            "identifier": [{
                "use": "official",
                "system": "http://sys-ids.kemkes.go.id/composition/100000004",
                "value": "resume-contract-1",
            }],
            "status": "final",
            "type": {"coding": [{
                "system": "http://loinc.org",
                "code": "88645-7",
                "display": "Outpatient summary note",
            }]},
            "category": [{"coding": [{
                "system": "http://loinc.org",
                "code": "LP173421-1",
                "display": "Report",
            }]}],
            "subject": {"reference": PATIENT_REF},
            "encounter": {"reference": ENCOUNTER_REF},
            "date": "2026-01-01T00:00:00Z",
            "author": [{"reference": PRACTITIONER_REF}],
            "title": "Synthetic outpatient summary",
            "section": [{
                "title": "Synthetic plan",
                "code": {"coding": [{"system": "http://loinc.org", "code": "18776-5"}]},
            }],
        },
        "Observation": {
            "resourceType": "Observation",
            "identifier": [{
                "use": "official",
                "system": "http://sys-ids.kemkes.go.id/observation/100000004",
                "value": "observation-contract-1",
            }],
            "status": "final",
            "code": {"coding": [{
                "system": "http://loinc.org",
                "code": "85354-9",
                "display": "Blood pressure panel",
            }]},
            "subject": {"reference": PATIENT_REF},
            "encounter": {"reference": ENCOUNTER_REF},
            "effectiveDateTime": "2026-01-01T00:00:00Z",
            "valueQuantity": {"value": 120, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        },
        "ClinicalImpression": {
            "resourceType": "ClinicalImpression",
            "status": "completed",
            "subject": {"reference": PATIENT_REF},
            "encounter": {"reference": ENCOUNTER_REF},
            "assessor": {"reference": PRACTITIONER_REF},
            "date": "2026-01-01T00:00:00Z",
            "effectiveDateTime": "2026-01-01T00:00:00Z",
            "summary": "Synthetic summary for contract testing",
            "investigation": [{"item": [{"reference": OBSERVATION_REF}, {"reference": CONDITION_REF}]}],
        },
        "Encounter": {
            "resourceType": "Encounter",
            "id": "encounter-contract-1",
            "identifier": [{
                "use": "official",
                "system": "http://sys-ids.kemkes.go.id/encounter/100000004",
                "value": "visit-contract-1",
            }],
            "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
            "subject": {"reference": PATIENT_REF},
            "period": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:30:00Z"},
            "participant": [{"individual": {"reference": PRACTITIONER_REF}}],
            "location": [{"location": {"reference": LOCATION_REF}}],
            "serviceProvider": {"reference": ORGANIZATION_REF},
            "statusHistory": [{
                "status": "finished",
                "period": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:30:00Z"},
            }],
            "diagnosis": [{"condition": {"reference": CONDITION_REF}}],
        },
    }


@pytest.mark.parametrize(
    "resource_type",
    ["Condition", "Composition", "Observation", "ClinicalImpression", "Encounter"],
)
def test_supported_sandbox_resource_contracts_accept_synthetic_mapped_payloads(
    valid_resources, resource_type
):
    # These local subset contracts are not a full validator for official profiles.
    validate_sandbox_resource(copy.deepcopy(valid_resources[resource_type]))


def test_contract_rejects_demo_placeholder_reference(valid_resources):
    payload = copy.deepcopy(valid_resources["Condition"])
    payload["subject"]["reference"] = "Patient/demo-patient-42"
    with pytest.raises(ValueError, match="placeholder"):
        validate_sandbox_resource(payload)


def test_contract_rejects_reference_with_wrong_resource_type(valid_resources):
    payload = copy.deepcopy(valid_resources["Observation"])
    payload["subject"]["reference"] = ENCOUNTER_REF
    with pytest.raises(ValueError, match="tipe resource"):
        validate_sandbox_resource(payload)


def test_create_contract_rejects_client_assigned_resource_id(valid_resources):
    payload = copy.deepcopy(valid_resources["Condition"])
    payload["id"] = "condition-contract-client-id"
    with pytest.raises(ValueError, match="biarkan server menetapkan ID"):
        validate_sandbox_resource(payload)


class SuccessWithoutResourceIdTransport(FakeTransport):
    """Simulate a 201 response that cannot identify the created resource."""

    def request(self, method, url, **kwargs):
        if method == "POST" and url.endswith("/Condition"):
            self.calls.append((method, url, kwargs))
            return FakeResponse(201, {"resourceType": "Condition"})
        return super().request(method, url, **kwargs)


def test_http_201_without_resource_id_is_uncertain_and_never_reposted(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = SuccessWithoutResourceIdTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)

    with factory() as session:
        row = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert row.status == "uncertain"
        assert row.external_resource_id is None

    post_count_before = sum(
        1 for method, url, _ in transport.calls
        if method == "POST" and url.endswith("/Condition")
    )
    assert post_count_before == 1

    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="rekonsiliasi manual"):
            transmit_outbox_item_sandbox(
                session, users["rekam_medis_demo"], outbox_ids["Condition"],
                client=client, confirmed_demo_only=True,
            )

    post_count_after = sum(
        1 for method, url, _ in transport.calls
        if method == "POST" and url.endswith("/Condition")
    )
    assert post_count_after == post_count_before == 1
    with factory() as session:
        tx = session.scalar(select(SATUSEHATTransmission).where(
            SATUSEHATTransmission.outbox_id == outbox_ids["Condition"]
        ))
        assert tx.status == "uncertain"
        assert tx.attempt_count == 1


def test_http_5xx_is_uncertain_and_not_automatically_retried(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = FakeTransport(post_status=503)
    client = SATUSEHATClient(GOOD_ENV, transport=transport)

    with factory() as session:
        row = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert row.status == "uncertain"
        assert row.http_status == 503

    post_count_before = sum(
        1 for method, url, _ in transport.calls
        if method == "POST" and url.endswith("/Condition")
    )
    assert post_count_before == 1
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="rekonsiliasi manual"):
            transmit_outbox_item_sandbox(
                session, users["rekam_medis_demo"], outbox_ids["Condition"],
                client=client, confirmed_demo_only=True,
            )
    post_count_after = sum(
        1 for method, url, _ in transport.calls
        if method == "POST" and url.endswith("/Condition")
    )
    assert post_count_after == post_count_before == 1
