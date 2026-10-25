"""Builder resource FHIR R4 untuk preview/mock saja; tidak melakukan HTTP."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

FHIR_ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
FHIR_CONDITION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"
FHIR_CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
FHIR_VERIFICATION_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
FHIR_COMPOSITION_CONFIDENTIALITY = "N"
MOCK_ONLY_NOTICE = "ID referensi demo adalah placeholder, bukan nomor IHS SATUSEHAT."


def _as_utc(value: datetime | None) -> str:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _narrative(title: str, content: str) -> dict[str, str]:
    safe_title = escape(title)
    safe_content = escape(content or "Belum dicatat")
    return {
        "status": "generated",
        "div": f'<div xmlns="http://www.w3.org/1999/xhtml"><p><b>{safe_title}</b></p><p>{safe_content}</p></div>',
    }


def build_condition(patient, visit, diagnosis) -> dict[str, Any]:
    if not getattr(diagnosis, "code_verified", False) or diagnosis.status != "confirmed":
        raise ValueError("Condition hanya dapat dibentuk dari diagnosis confirmed dan kode terverifikasi.")
    return {
        "resourceType": "Condition",
        "id": f"demo-condition-{diagnosis.id}",
        "identifier": [{"system": "https://example.invalid/fhir/condition", "value": f"diagnosis-{diagnosis.id}"}],
        "clinicalStatus": {"coding": [{
            "system": FHIR_CLINICAL_STATUS_SYSTEM, "code": "active", "display": "Active"
        }]},
        "verificationStatus": {"coding": [{
            "system": FHIR_VERIFICATION_STATUS_SYSTEM, "code": "confirmed", "display": "Confirmed"
        }]},
        "category": [{"coding": [{
            "system": FHIR_CONDITION_CATEGORY_SYSTEM,
            "code": "encounter-diagnosis",
            "display": "Encounter Diagnosis",
        }]}],
        "code": {"coding": [{
            "system": FHIR_ICD10_SYSTEM,
            "code": diagnosis.icd10_code,
            "display": diagnosis.icd10_display,
        }], "text": diagnosis.clinical_label},
        "subject": {"reference": f"Patient/demo-patient-{patient.id}"},
        "encounter": {"reference": f"Encounter/demo-encounter-{visit.id}"},
        "recordedDate": _as_utc(diagnosis.created_at),
        "recorder": {"reference": f"Practitioner/demo-practitioner-{diagnosis.diagnosis_set_by}"},
    }


def build_composition(patient, visit, resume, diagnoses) -> dict[str, Any]:
    if resume.status != "final" or not resume.finalized_at:
        raise ValueError("Composition hanya dapat dibentuk dari resume final.")
    verified = [d for d in diagnoses if d.status == "confirmed" and d.code_verified]
    sections = [
        {"title": "S - Subjective", "text": _narrative("S - Subjective", resume.subjective)},
        {"title": "O - Objective", "text": _narrative("O - Objective", resume.objective)},
        {"title": "A - Assessment", "text": _narrative("A - Assessment", resume.assessment)},
        {"title": "P - Plan", "text": _narrative("P - Plan", resume.plan)},
    ]
    if resume.follow_up.strip():
        sections.append({"title": "Tindak lanjut", "text": _narrative("Tindak lanjut", resume.follow_up)})
    if verified:
        sections.append({
            "title": "Diagnosis terverifikasi",
            "entry": [{"reference": f"Condition/demo-condition-{d.id}"} for d in verified],
            "text": _narrative("Diagnosis terverifikasi", "; ".join(f"{d.icd10_code} — {d.icd10_display}" for d in verified)),
        })
    return {
        "resourceType": "Composition",
        "id": f"demo-composition-{resume.id}-v{getattr(resume, 'version', 1)}",
        "identifier": [{"system": "https://example.invalid/fhir/composition", "value": f"resume-{resume.id}-v{getattr(resume, 'version', 1)}"}],
        "status": "final",
        "type": {"text": "Resume Medis Rawat Jalan"},
        "subject": {"reference": f"Patient/demo-patient-{patient.id}"},
        "encounter": {"reference": f"Encounter/demo-encounter-{visit.id}"},
        "date": _as_utc(resume.finalized_at),
        "author": [{"reference": f"Practitioner/demo-practitioner-{resume.signed_by or resume.created_by}"}],
        "title": "Resume Medis Rawat Jalan — PROTOTIPE",
        "confidentiality": FHIR_COMPOSITION_CONFIDENTIALITY,
        "section": sections,
        "extension": [{
            "url": "https://example.invalid/fhir/StructureDefinition/mock-only-notice",
            "valueString": MOCK_ONLY_NOTICE,
        }],
    }


def validate_fhir_resource(resource: dict[str, Any]) -> None:
    """Minimal local shape check, not a full FHIR profile validator."""
    resource_type = resource.get("resourceType")
    if resource_type == "Condition":
        coding = (((resource.get("code") or {}).get("coding") or [{}])[0])
        if not resource.get("id") or not coding.get("code") or not coding.get("display"):
            raise ValueError("Condition memerlukan id dan kode ICD-10 yang memiliki display.")
        if coding.get("system") != FHIR_ICD10_SYSTEM:
            raise ValueError("Condition memakai system ICD-10 yang tidak sesuai.")
        if not (resource.get("subject") or {}).get("reference") or not (resource.get("encounter") or {}).get("reference"):
            raise ValueError("Condition memerlukan subject dan encounter.")
    elif resource_type == "Composition":
        if resource.get("status") != "final" or not resource.get("title") or not resource.get("section"):
            raise ValueError("Composition harus final, memiliki title, dan section.")
        if not (resource.get("subject") or {}).get("reference") or not (resource.get("encounter") or {}).get("reference"):
            raise ValueError("Composition memerlukan subject dan encounter.")
    else:
        raise ValueError(f"Resource FHIR tidak didukung pada fase ini: {resource_type!r}.")


def validate_sandbox_resource(resource: dict[str, Any]) -> None:
    """Fail-closed guard against the demo placeholders used by the mock builders."""
    import json
    validate_fhir_resource(resource)
    serialized = json.dumps(resource, ensure_ascii=False, sort_keys=True).casefold()
    forbidden_markers = ("example.invalid", "demo-", "mock-only-notice")
    found = [marker for marker in forbidden_markers if marker in serialized]
    if found:
        raise ValueError("Payload masih memuat placeholder demo/mock; tidak dapat dipakai dalam preflight sandbox.")
    resource_type = resource.get("resourceType")
    if resource_type == "Condition":
        required_references = {
            "subject": "Patient/",
            "encounter": "Encounter/",
            "recorder": "Practitioner/",
        }
        for element, prefix in required_references.items():
            reference = ((resource.get(element) or {}).get("reference") or "")
            if not reference.startswith(prefix) or len(reference) <= len(prefix):
                raise ValueError(f"Condition.{element} harus menunjuk resource SATUSEHAT yang sudah dipetakan.")
    elif resource_type == "Composition":
        required_references = {
            "subject": "Patient/",
            "encounter": "Encounter/",
        }
        for element, prefix in required_references.items():
            reference = ((resource.get(element) or {}).get("reference") or "")
            if not reference.startswith(prefix) or len(reference) <= len(prefix):
                raise ValueError(f"Composition.{element} harus menunjuk resource SATUSEHAT yang sudah dipetakan.")
        authors = resource.get("author") or []
        if not authors or not any(str((a.get("reference") or "")).startswith("Practitioner/") for a in authors):
            raise ValueError("Composition.author harus menunjuk Practitioner yang sudah dipetakan.")
