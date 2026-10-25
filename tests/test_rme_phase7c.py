"""Regression tests for strict SATUSEHAT FHIR references in sandbox payloads."""
from __future__ import annotations

import copy

import pytest

from rme.integrations.satusehat.fhir import validate_sandbox_resource


def condition_payload():
    return {
        "resourceType": "Condition",
        "identifier": [{
            "use": "official",
            "system": "http://sys-ids.kemkes.go.id/condition/100000004",
            "value": "diagnosis-42",
        }],
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
        "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]},
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "encounter-diagnosis"}]}],
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "A41.9", "display": "Sepsis, unspecified"}]},
        "subject": {"reference": "Patient/100000030009"},
        "encounter": {"reference": "Encounter/encounter-42"},
        "recorder": {"reference": "Practitioner/N10000001"},
        "recordedDate": "2026-10-25T09:00:00Z",
    }


def composition_payload():
    return {
        "resourceType": "Composition",
        "identifier": [{
            "use": "official",
            "system": "http://sys-ids.kemkes.go.id/composition/100000004",
            "value": "resume-42-v1",
        }],
        "status": "final",
        "type": {"coding": [{"system": "http://loinc.org", "code": "88645-7"}]},
        "category": [{"coding": [{"system": "http://loinc.org", "code": "LP173421-1"}]}],
        "subject": {"reference": "Patient/100000030009"},
        "encounter": {"reference": "Encounter/encounter-42"},
        "author": [{"reference": "Practitioner/N10000001"}],
        "date": "2026-10-25T09:00:00Z",
        "title": "Resume Medis Rawat Jalan",
        "section": [{
            "title": "Diagnosis",
            "code": {"coding": [{"system": "http://terminology.kemkes.go.id", "code": "TK000004"}]},
            "entry": [{"reference": "Condition/condition-42"}],
        }],
    }


def test_sandbox_validator_accepts_well_formed_server_assigned_relative_references():
    validate_sandbox_resource(condition_payload())
    validate_sandbox_resource(composition_payload())


@pytest.mark.parametrize("bad_reference", [
    "Patient/example-123",
    "Patient/.invalid",
    "Patient/abc.invalid",
    "Patient/has space",
    "https://example.org/fhir/Patient/123",
    "Patient/123?identifier=x",
    "Patient/123/_history/2",
])
def test_condition_rejects_unsafe_or_non_relative_reference(bad_reference):
    payload = condition_payload()
    payload["subject"]["reference"] = bad_reference

    with pytest.raises(ValueError):
        validate_sandbox_resource(payload)


def test_composition_section_entry_rejects_example_id_even_if_reference_shape_looks_valid():
    payload = composition_payload()
    payload["section"][0]["entry"][0]["reference"] = "Condition/example-123"

    with pytest.raises(ValueError, match="placeholder|ID eksternal|resource server"):
        validate_sandbox_resource(payload)


def test_nested_reference_not_in_known_fields_is_still_checked():
    payload = condition_payload()
    payload["extension"] = [{
        "url": "https://example.org/fhir/StructureDefinition/related",
        "valueReference": {"reference": "Patient/example-user-42"},
    }]

    with pytest.raises(ValueError):
        validate_sandbox_resource(payload)


def test_composition_rejects_wrong_resource_type_in_section_entry():
    payload = composition_payload()
    payload["section"][0]["entry"][0]["reference"] = "Patient/100000030009"

    with pytest.raises(ValueError, match="tipe resource"):
        validate_sandbox_resource(payload)
