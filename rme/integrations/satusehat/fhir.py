"""Builder resource FHIR R4 untuk preview/mock saja; tidak melakukan HTTP."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any
import re

FHIR_ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10"
FHIR_CONDITION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"
FHIR_CLINICAL_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
FHIR_VERIFICATION_STATUS_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
FHIR_COMPOSITION_CONFIDENTIALITY = "N"
MOCK_ONLY_NOTICE = "ID referensi demo adalah placeholder, bukan nomor IHS SATUSEHAT."

REMOTE_REFERENCE_TYPES = {
    "Patient", "Practitioner", "Organization", "Location", "Encounter",
    "Condition", "Composition", "Observation", "ClinicalImpression",
}
REMOTE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$")
REMOTE_REFERENCE_PATTERN = re.compile(
    r"^(Patient|Practitioner|Organization|Location|Encounter|Condition|Composition|Observation|ClinicalImpression)/([A-Za-z0-9][A-Za-z0-9.-]{0,127})$"
)


def _is_safe_remote_id(value: Any) -> bool:
    if not isinstance(value, str) or not REMOTE_ID_PATTERN.fullmatch(value):
        return False
    lowered = value.casefold()
    return not any(marker in lowered for marker in ("demo", "example", ".invalid"))


def _validate_remote_reference(
    reference: Any,
    label: str,
    *,
    allowed_types: set[str] | None = None,
) -> None:
    """Require a relative reference to a plausible server-assigned resource ID."""
    if not isinstance(reference, str):
        raise ValueError(f"{label} harus berupa relative reference FHIR.")
    match = REMOTE_REFERENCE_PATTERN.fullmatch(reference)
    if match is None:
        raise ValueError(f"{label} harus menunjuk ID resource server yang valid.")
    resource_type, external_id = match.groups()
    if resource_type not in REMOTE_REFERENCE_TYPES:
        raise ValueError(f"{label} memakai tipe resource yang tidak diizinkan.")
    if allowed_types is not None and resource_type not in allowed_types:
        raise ValueError(f"{label} menunjuk tipe resource yang tidak sesuai.")
    if not _is_safe_remote_id(external_id):
        raise ValueError(f"{label} masih memakai placeholder atau ID eksternal yang tidak valid.")



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
    """Local structural checks only; this is not a complete SATUSEHAT profile validator."""
    resource_type = resource.get("resourceType")
    if resource_type == "Condition":
        coding = (((resource.get("code") or {}).get("coding") or [{}])[0])
        if not resource.get("id") or not coding.get("code") or not coding.get("display"):
            raise ValueError("Condition memerlukan id dan coding ICD-10 lengkap.")
        if coding.get("system") != FHIR_ICD10_SYSTEM:
            raise ValueError("Condition memakai system ICD-10 yang tidak sesuai.")
        if not (resource.get("subject") or {}).get("reference") or not (resource.get("encounter") or {}).get("reference"):
            raise ValueError("Condition memerlukan subject dan encounter.")
    elif resource_type == "Composition":
        if resource.get("status") != "final" or not resource.get("title") or not resource.get("section"):
            raise ValueError("Composition harus final, memiliki title, dan section.")
        if not (resource.get("subject") or {}).get("reference") or not (resource.get("encounter") or {}).get("reference"):
            raise ValueError("Composition memerlukan subject dan encounter.")
    elif resource_type == "Encounter":
        if not resource.get("id") or resource.get("status") not in {"arrived", "in-progress", "finished"}:
            raise ValueError("Encounter memerlukan ID dan status yang valid.")
        if not (resource.get("identifier") or []) or not (resource.get("class") or {}).get("code"):
            raise ValueError("Encounter memerlukan identifier dan class.")
        if not (resource.get("subject") or {}).get("reference") or not (resource.get("period") or {}).get("start") or not (resource.get("period") or {}).get("end"):
            raise ValueError("Encounter memerlukan subject dan period lengkap.")
        if not (resource.get("participant") or []) or not (resource.get("location") or []) or not (resource.get("serviceProvider") or {}).get("reference"):
            raise ValueError("Encounter memerlukan participant, location, dan serviceProvider.")
        if not (resource.get("statusHistory") or []) or not (resource.get("diagnosis") or []):
            raise ValueError("Encounter memerlukan statusHistory dan referensi diagnosis.")
    elif resource_type == "Observation":
        coding = (((resource.get("code") or {}).get("coding") or [{}])[0])
        has_value = "valueQuantity" in resource or bool(resource.get("component"))
        if resource.get("status") != "final" or not coding.get("code") or coding.get("system") != "http://loinc.org":
            raise ValueError("Observation memerlukan status final dan coding LOINC.")
        if not has_value or not (resource.get("subject") or {}).get("reference") or not (resource.get("encounter") or {}).get("reference"):
            raise ValueError("Observation memerlukan nilai, subject, dan encounter.")
        if not resource.get("effectiveDateTime"):
            raise ValueError("Observation.effectiveDateTime wajib tersedia.")
    elif resource_type == "ClinicalImpression":
        if resource.get("status") not in {"in-progress", "completed"}:
            raise ValueError("ClinicalImpression.status tidak valid.")
        if not (resource.get("encounter") or {}).get("reference") or not (resource.get("assessor") or {}).get("reference"):
            raise ValueError("ClinicalImpression memerlukan encounter dan assessor.")
        if not resource.get("date") or not resource.get("effectiveDateTime") or not str(resource.get("summary") or "").strip():
            raise ValueError("ClinicalImpression memerlukan date, effectiveDateTime, dan summary.")
        if not (resource.get("investigation") or []):
            raise ValueError("ClinicalImpression memerlukan investigation.")
    else:
        raise ValueError(f"Resource FHIR tidak didukung: {resource_type!r}.")


def validate_sandbox_resource(resource: dict[str, Any]) -> None:
    """Fail-closed subset validator. Not a complete SATUSEHAT profile validator."""
    import json

    serialized = json.dumps(resource, ensure_ascii=False, sort_keys=True).casefold()
    forbidden_markers = ("example.invalid", "demo-", "mock-only-notice")
    if any(marker in serialized for marker in forbidden_markers):
        raise ValueError("Payload masih memuat placeholder demo/mock; tidak dapat dikirim ke sandbox.")

    resource_type = resource.get("resourceType")
    probe = dict(resource)
    if not probe.get("id"):
        probe["id"] = "local-validation-only"
    validate_fhir_resource(probe)
    if resource.get("id") and resource_type != "Encounter":
        raise ValueError("Payload create tidak boleh memakai ID lokal; biarkan server menetapkan ID.")
    if resource_type == "Encounter":
        ext_id = resource.get("id")
        if not _is_safe_remote_id(ext_id):
            raise ValueError("Update Encounter harus memakai ID server yang sudah diverifikasi.")

    def _ref(element: Any, prefix: str, label: str) -> None:
        reference = (element or {}).get("reference")
        expected_type = prefix.rstrip("/")
        _validate_remote_reference(reference, label, allowed_types={expected_type})

    def _refs(items: Any, prefix: str, label: str) -> None:
        if not isinstance(items, list) or not items:
            raise ValueError(f"{label} harus berisi referensi yang sudah dipetakan.")
        for item in items:
            _ref(item, prefix, label)

    if resource_type == "Condition":
        coding = (((resource.get("code") or {}).get("coding") or [{}])[0])
        identifier = ((resource.get("identifier") or [{}])[0])
        if not coding.get("code") or not coding.get("display") or coding.get("system") != FHIR_ICD10_SYSTEM:
            raise ValueError("Condition memerlukan coding ICD-10 2010 yang lengkap.")
        if identifier.get("use") != "official" or not str(identifier.get("system") or "").startswith("http://sys-ids.kemkes.go.id/condition/") or not identifier.get("value"):
            raise ValueError("Condition.identifier harus memakai Organization IHS.")
        if not resource.get("clinicalStatus") or not resource.get("verificationStatus") or not resource.get("category"):
            raise ValueError("Condition memerlukan status klinis, verifikasi, dan kategori.")
        _ref(resource.get("subject"), "Patient/", "Condition.subject")
        _ref(resource.get("encounter"), "Encounter/", "Condition.encounter")
        _ref(resource.get("recorder"), "Practitioner/", "Condition.recorder")
        if not resource.get("recordedDate"):
            raise ValueError("Condition.recordedDate wajib tersedia.")
    elif resource_type == "Composition":
        identifier = ((resource.get("identifier") or [{}])[0])
        type_coding = (((resource.get("type") or {}).get("coding") or [{}])[0])
        category_coding = (((resource.get("category") or [{}])[0].get("coding") or [{}])[0])
        if identifier.get("use") != "official" or not str(identifier.get("system") or "").startswith("http://sys-ids.kemkes.go.id/composition/") or not identifier.get("value"):
            raise ValueError("Composition.identifier harus memakai Organization IHS.")
        if type_coding.get("system") != "http://loinc.org" or type_coding.get("code") != "88645-7":
            raise ValueError("Composition.type belum menggunakan kode LOINC resume rawat jalan.")
        if category_coding.get("system") != "http://loinc.org" or category_coding.get("code") != "LP173421-1":
            raise ValueError("Composition.category belum memakai kategori LOINC Report.")
        _ref(resource.get("subject"), "Patient/", "Composition.subject")
        _ref(resource.get("encounter"), "Encounter/", "Composition.encounter")
        _ref((resource.get("author") or [{}])[0], "Practitioner/", "Composition.author")
        if not resource.get("date") or not resource.get("section"):
            raise ValueError("Composition memerlukan date dan section.")
        for section in resource.get("section") or []:
            if not section.get("title") or not (((section.get("code") or {}).get("coding") or [{}])[0].get("code")):
                raise ValueError("Setiap Composition.section harus memiliki title dan coding.")
            for entry in section.get("entry") or []:
                _validate_remote_reference(
                    (entry or {}).get("reference"),
                    "Composition.section.entry",
                    allowed_types={"Condition", "Observation", "ClinicalImpression"},
                )
    elif resource_type == "Encounter":
        identifier = ((resource.get("identifier") or [{}])[0])
        if identifier.get("use") != "official" or not str(identifier.get("system") or "").startswith("http://sys-ids.kemkes.go.id/encounter/") or not identifier.get("value"):
            raise ValueError("Encounter.identifier harus memakai Organization IHS dan nomor kunjungan lokal.")
        _ref(resource.get("subject"), "Patient/", "Encounter.subject")
        _ref(resource.get("serviceProvider"), "Organization/", "Encounter.serviceProvider")
        for participant in resource.get("participant") or []:
            _ref(participant.get("individual"), "Practitioner/", "Encounter.participant.individual")
        for location in resource.get("location") or []:
            _ref(location.get("location"), "Location/", "Encounter.location.location")
        for diagnosis in resource.get("diagnosis") or []:
            _ref(diagnosis.get("condition"), "Condition/", "Encounter.diagnosis.condition")
    elif resource_type == "Observation":
        identifier = ((resource.get("identifier") or [{}])[0])
        coding = (((resource.get("code") or {}).get("coding") or [{}])[0])
        if identifier.get("use") != "official" or not str(identifier.get("system") or "").startswith("http://sys-ids.kemkes.go.id/observation/") or not identifier.get("value"):
            raise ValueError("Observation.identifier harus memakai Organization IHS.")
        if coding.get("system") != "http://loinc.org" or not coding.get("code") or not coding.get("display"):
            raise ValueError("Observation.code harus mempunyai coding LOINC lengkap.")
        _ref(resource.get("subject"), "Patient/", "Observation.subject")
        _ref(resource.get("encounter"), "Encounter/", "Observation.encounter")
        for performer in resource.get("performer") or []:
            _ref(performer, "Practitioner/", "Observation.performer")
        for component in resource.get("component") or []:
            component_code = (((component.get("code") or {}).get("coding") or [{}])[0])
            if component_code.get("system") != "http://loinc.org" or not component_code.get("code"):
                raise ValueError("Observation.component memerlukan coding LOINC.")
            if not component.get("valueQuantity"):
                raise ValueError("Observation.component memerlukan valueQuantity.")
    elif resource_type == "ClinicalImpression":
        _ref(resource.get("subject"), "Patient/", "ClinicalImpression.subject")
        _ref(resource.get("encounter"), "Encounter/", "ClinicalImpression.encounter")
        _ref(resource.get("assessor"), "Practitioner/", "ClinicalImpression.assessor")
        for problem in resource.get("problem") or []:
            _ref(problem, "Condition/", "ClinicalImpression.problem")
        for investigation in resource.get("investigation") or []:
            for item in investigation.get("item") or []:
                _validate_remote_reference(
                    (item or {}).get("reference"),
                    "ClinicalImpression.investigation.item",
                    allowed_types={"Observation", "Condition"},
                )


    # Defense in depth: check every FHIR Reference element, including future nested
    # fields not covered by the resource-specific checks above.
    def _scan_references(value: Any, path: str = "resource") -> None:
        if isinstance(value, dict):
            if "reference" in value:
                _validate_remote_reference(value["reference"], f"{path}.reference")
            for key, child in value.items():
                _scan_references(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                _scan_references(child, f"{path}[{index}]")

    _scan_references(resource)



def build_encounter_update(patient, visit, diagnoses) -> dict[str, Any]:
    """Build an Encounter update payload referencing verified diagnoses; ID is placeholder until mapped."""
    arrived = _as_utc(visit.arrived_at)
    started = _as_utc(visit.started_at or visit.arrived_at)
    finished = _as_utc(visit.finished_at or visit.started_at or visit.arrived_at)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in (visit.poli or "poli")).strip("-")
    return {
        "resourceType": "Encounter",
        "id": f"demo-encounter-update-{visit.id}",
        "identifier": [{"use": "official", "system": "https://example.invalid/fhir/encounter",
                        "value": visit.visit_number}],
        "status": "finished",
        "statusHistory": [
            {"status": "arrived", "period": {"start": arrived, "end": started}},
            {"status": "in-progress", "period": {"start": started, "end": finished}},
            {"status": "finished", "period": {"start": finished, "end": finished}},
        ],
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                  "code": "AMB", "display": "ambulatory"},
        "classHistory": [{
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                      "code": "AMB", "display": "ambulatory"},
            "period": {"start": arrived, "end": finished},
        }],
        "subject": {"reference": f"Patient/demo-patient-{patient.id}"},
        "participant": [{"type": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
            "code": "ATND", "display": "attender",
        }]}], "individual": {"reference": f"Practitioner/demo-practitioner-{visit.dpjp_user_id}"}}],
        "period": {"start": arrived, "end": finished},
        "reasonCode": [{"text": visit.poli}],
        "diagnosis": [{
            "condition": {"reference": f"Condition/demo-condition-{d.id}"},
            "use": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/diagnosis-role",
                "code": "AD", "display": "Admission diagnosis",
            }]},
            "rank": index,
        } for index, d in enumerate(diagnoses, start=1)],
        "location": [{
            "location": {"reference": f"Location/demo-location-{visit.facility_id}-{slug}",
                         "display": visit.poli},
            "status": "completed",
            "period": {"start": arrived, "end": finished},
        }],
        "serviceProvider": {"reference": f"Organization/demo-organization-{visit.facility_id}"},
    }


def build_vital_observations(patient, visit, vitals) -> list[dict[str, Any]]:
    """Create one Observation per vital sign, using the LOINC codes in the outpatient playbook."""
    stamp = _as_utc(vitals.recorded_at)
    performer = f"Practitioner/demo-practitioner-{vitals.recorded_by}"
    subject = f"Patient/demo-patient-{patient.id}"
    encounter = f"Encounter/demo-encounter-{visit.id}"
    result: list[dict[str, Any]] = []

    def resource(suffix: str, code: str, display: str, value: float | int | None,
                 unit: str, unit_code: str) -> None:
        if value is None:
            return
        code_suffix = "".join(ch for ch in code if ch.isalnum())
        result.append({
            "resourceType": "Observation",
            "id": f"demo-observation-{visit.id}-{code_suffix}",
            "identifier": [{"use": "official", "system": "https://example.invalid/fhir/observation",
                            "value": f"vitals-{vitals.id}-{suffix}"}],
            "status": "final",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs", "display": "Vital Signs",
            }]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
            "subject": {"reference": subject},
            "encounter": {"reference": encounter},
            "effectiveDateTime": stamp,
            "issued": stamp,
            "performer": [{"reference": performer}],
            "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit_code},
        })

    if vitals.systolic_mmhg is not None or vitals.diastolic_mmhg is not None:
        components = []
        if vitals.systolic_mmhg is not None:
            components.append({"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6",
                                                       "display": "Systolic blood pressure"}]},
                               "valueQuantity": {"value": vitals.systolic_mmhg, "unit": "mmHg",
                                                 "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}})
        if vitals.diastolic_mmhg is not None:
            components.append({"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4",
                                                       "display": "Diastolic blood pressure"}]},
                               "valueQuantity": {"value": vitals.diastolic_mmhg, "unit": "mmHg",
                                                 "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}})
        code_suffix = "853549"
        result.append({
            "resourceType": "Observation", "id": f"demo-observation-{visit.id}-{code_suffix}",
            "identifier": [{"use": "official", "system": "https://example.invalid/fhir/observation",
                            "value": f"vitals-{vitals.id}-blood-pressure"}],
            "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "vital-signs", "display": "Vital Signs"}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]},
            "subject": {"reference": subject}, "encounter": {"reference": encounter},
            "effectiveDateTime": stamp, "issued": stamp, "performer": [{"reference": performer}],
            "component": components,
        })
    resource("pulse", "8867-4", "Heart rate", vitals.pulse_per_min, "beats/minute", "/min")
    resource("respiration", "9279-1", "Respiratory rate", vitals.respiration_per_min, "breaths/minute", "/min")
    resource("temperature", "8310-5", "Body temperature", vitals.temperature_c, "Cel", "Cel")
    resource("spo2", "59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry", vitals.spo2_percent, "%", "%")
    resource("weight", "29463-7", "Body weight", vitals.weight_kg, "kg", "kg")
    resource("height", "8302-2", "Body height", vitals.height_cm, "cm", "cm")
    resource("bmi", "39156-5", "Body mass index (BMI) [Ratio]", vitals.bmi, "kg/m2", "kg/m2")
    return result


def build_clinical_impression(patient, visit, anamnesis, resume, diagnoses, observations) -> dict[str, Any]:
    """Represent clinician-documented history/assessment, never an AI-generated diagnosis."""
    history_parts = []
    if anamnesis is not None:
        for label, value in (("Keluhan utama", anamnesis.chief_complaint),
                             ("Gejala penyerta", anamnesis.associated_symptoms),
                             ("Riwayat pribadi", anamnesis.personal_history),
                             ("Riwayat keluarga", anamnesis.family_history)):
            if (value or "").strip():
                history_parts.append(f"{label}: {value.strip()}")
    if resume.subjective.strip():
        history_parts.append(f"Subjektif dokter: {resume.subjective.strip()}")
    if resume.assessment.strip():
        history_parts.append(f"Asesmen dokter: {resume.assessment.strip()}")
    effective = _as_utc(resume.finalized_at or visit.finished_at or visit.arrived_at)
    diagnosis_list = [d for d in diagnoses if d.status == "confirmed" and d.code_verified]
    return {
        "resourceType": "ClinicalImpression",
        "id": f"demo-clinical-impression-{visit.id}-v{getattr(resume, 'version', 1)}",
        "status": "completed",
        "subject": {"reference": f"Patient/demo-patient-{patient.id}"},
        "encounter": {"reference": f"Encounter/demo-encounter-{visit.id}"},
        "effectiveDateTime": effective,
        "date": effective,
        "assessor": {"reference": f"Practitioner/demo-practitioner-{resume.signed_by or resume.created_by}"},
        "problem": [{"reference": f"Condition/demo-condition-{d.id}"} for d in diagnosis_list],
        "investigation": [{
            "code": {"text": "Riwayat perjalanan penyakit dan pemeriksaan tanda vital"},
            "item": [{"reference": observation["id"].replace("demo-observation-", "Observation/demo-observation-")}
                     for observation in observations],
        }],
        "summary": "\n".join(history_parts) or "Riwayat perjalanan penyakit belum didokumentasikan.",
        "finding": [{
            "itemCodeableConcept": {"coding": [{
                "system": FHIR_ICD10_SYSTEM, "code": d.icd10_code, "display": d.icd10_display,
            }], "text": d.clinical_label}
        } for d in diagnosis_list],
    }
