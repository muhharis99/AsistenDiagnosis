"""Guarded SATUSEHAT sandbox MPI search and outbox transmission."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rme.integrations.satusehat.client import SATUSEHATClient, SATUSEHATClientError
from rme.integrations.satusehat.fhir import (build_condition, build_composition, build_encounter_update, build_vital_observations, build_clinical_impression, validate_sandbox_resource)
from rme.integrations.satusehat.mapping import (
    build_visit_sandbox_preflight,
    is_safe_external_id,
    location_local_key,
)
from rme.models import (
    Anamnesis, Consent, Diagnosis, Facility, OutboxSync, Patient, ResumeMedical, SATUSEHATIdMapping,
    SATUSEHATTransmission, User, Visit, VitalSigns, utc_now,
)
from rme.security import append_audit, require_permission


class SATUSEHATWorkflowError(ValueError):
    """Precondition or controlled-transmission error."""


def _latest_consent(session: Session, patient_id: int, consent_type: str = "data_sharing") -> bool:
    row = session.scalar(
        select(Consent).where(
            Consent.patient_id == patient_id, Consent.consent_type == consent_type
        ).order_by(Consent.id.desc()).limit(1)
    )
    return bool(row and row.granted)


def _verified_mapping(
    session: Session, resource_type: str, local_key: str, *, expected_external_id: str | None = None
) -> str:
    row = session.scalar(
        select(SATUSEHATIdMapping).where(
            SATUSEHATIdMapping.resource_type == resource_type,
            SATUSEHATIdMapping.local_key == str(local_key),
            SATUSEHATIdMapping.environment == "sandbox",
            SATUSEHATIdMapping.verified.is_(True),
            SATUSEHATIdMapping.is_demo.is_(True),
        )
    )
    if row is None or not is_safe_external_id(row.external_id):
        raise SATUSEHATWorkflowError(f"Mapping {resource_type} belum terverifikasi untuk kunci lokal ini.")
    if expected_external_id is not None and row.external_id != expected_external_id:
        raise SATUSEHATWorkflowError(f"Mapping {resource_type} tidak cocok dengan konfigurasi organisasi sandbox.")
    return row.external_id


def _patient_match_ids(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("resourceType") != "Bundle":
        raise SATUSEHATWorkflowError("Respons pencarian MPI bukan Bundle FHIR.")
    matches: list[dict[str, str]] = []
    for entry in (bundle.get("entry") or [])[:100]:
        resource = (entry or {}).get("resource") or {}
        candidate = resource.get("id")
        if resource.get("resourceType") == "Patient" and isinstance(candidate, str) and is_safe_external_id(candidate):
            matches.append({"resourceType": "Patient", "id": candidate})
    total = bundle.get("total")
    if not isinstance(total, int) or total < 0:
        total = len(matches)
    return {"total": total, "matches": matches, "ambiguous": total != 1 or len(matches) != 1}


def search_demo_patient_mpi(
    session: Session,
    user: User,
    patient_id: int,
    cipher,
    *,
    confirmed_demo_only: bool,
    client: SATUSEHATClient | None = None,
) -> dict[str, Any]:
    """Search sandbox MPI using decrypted NIK of one demo patient; never persists or audits the NIK."""
    require_permission(user, "satusehat:manage")
    if not confirmed_demo_only:
        raise SATUSEHATWorkflowError("Konfirmasi bahwa pasien dan NIK adalah data uji fiktif wajib dicentang.")
    patient = session.get(Patient, patient_id)
    if patient is None or not patient.is_demo:
        raise SATUSEHATWorkflowError("Pencarian MPI pada fase ini hanya untuk pasien demo.")
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Persetujuan pembukaan/pemanfaatan data pasien belum aktif.")
    api = client or SATUSEHATClient()
    nik = cipher.decrypt(patient.nik_ciphertext)
    if not re.fullmatch(r"[0-9]{16}", nik):
        raise SATUSEHATWorkflowError("NIK demo harus 16 digit agar dapat dicari di MPI sandbox.")
    response = api.search_patient_by_nik(nik)
    summary = _patient_match_ids(response.payload)
    append_audit(
        session, user, "satusehat.mpi_patient_search", "Patient", patient.id,
        {"mode": "sandbox", "query_type": "NIK", "match_count": len(summary["matches"]),
         "reported_total": summary["total"], "nik_logged": False},
    )
    session.commit()
    return summary


def _map_references(
    value: Any,
    replacements: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        return {key: _map_references(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_references(item, replacements) for item in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            if value == old:
                return new
        return value
    return value


def _condition_external_reference(
    session: Session, visit_id: int, reference: str
) -> str:
    match = re.fullmatch(r"Condition/demo-condition-([0-9]+)", reference or "")
    if not match:
        raise SATUSEHATWorkflowError("Referensi Condition tidak dikenali.")
    diagnosis_id = int(match.group(1))
    rows = session.scalars(
        select(OutboxSync).where(
            OutboxSync.visit_id == visit_id, OutboxSync.resource_type == "Condition",
            OutboxSync.is_demo.is_(True),
        ).order_by(OutboxSync.id.desc())
    ).all()
    for item in rows:
        try:
            payload = json.loads(item.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("id") != f"demo-condition-{diagnosis_id}":
            continue
        sent = session.scalar(select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == item.id))
        if sent is not None and sent.status == "succeeded" and sent.external_resource_id:
            return f"Condition/{sent.external_resource_id}"
    raise SATUSEHATWorkflowError(
        "Condition yang dirujuk belum memiliki respons sukses; kirim Condition terverifikasi terlebih dahulu."
    )


def _prepare_condition(
    session: Session, outbox: OutboxSync, visit: Visit, patient: Patient, organization_ihs: str
) -> dict[str, Any]:
    try:
        payload = json.loads(outbox.payload_json)
    except json.JSONDecodeError as exc:
        raise SATUSEHATWorkflowError("Payload outbox bukan JSON yang valid.") from exc
    demo_id = payload.get("id", "")
    match = re.fullmatch(r"demo-condition-([0-9]+)", str(demo_id))
    if not match:
        raise SATUSEHATWorkflowError("ID Condition demo tidak dikenal; payload ditahan.")
    diagnosis = session.get(Diagnosis, int(match.group(1)))
    if diagnosis is None or diagnosis.visit_id != visit.id or diagnosis.status != "confirmed" or not diagnosis.code_verified:
        raise SATUSEHATWorkflowError("Diagnosis Condition bukan diagnosis confirmed dengan kode terverifikasi.")
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Consent pembukaan/pemanfaatan data sudah tidak aktif.")

    patient_ihs = _verified_mapping(session, "Patient", str(patient.id))
    encounter_id = _verified_mapping(session, "Encounter", str(visit.id))
    practitioner_id = _verified_mapping(session, "Practitioner", str(diagnosis.diagnosis_set_by))
    org_id = _verified_mapping(
        session, "Organization", str(visit.facility_id), expected_external_id=organization_ihs
    )
    # Only server-assigned IDs may be used in references; the client assigns the Condition.id.
    payload.pop("id", None)
    payload["identifier"] = [{
        "use": "official",
        "system": f"http://sys-ids.kemkes.go.id/condition/{org_id}",
        "value": f"diagnosis-{diagnosis.id}",
    }]
    replacements = {
        f"Patient/demo-patient-{patient.id}": f"Patient/{patient_ihs}",
        f"Encounter/demo-encounter-{visit.id}": f"Encounter/{encounter_id}",
        f"Practitioner/demo-practitioner-{diagnosis.diagnosis_set_by}": f"Practitioner/{practitioner_id}",
    }
    return _map_references(payload, replacements)


def _prepare_composition(
    session: Session, outbox: OutboxSync, visit: Visit, patient: Patient,
    resume: ResumeMedical, organization_ihs: str
) -> dict[str, Any]:
    try:
        payload = json.loads(outbox.payload_json)
    except json.JSONDecodeError as exc:
        raise SATUSEHATWorkflowError("Payload outbox bukan JSON yang valid.") from exc
    if resume.status != "final" or not resume.finalized_at:
        raise SATUSEHATWorkflowError("Resume belum final.")
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Consent pembukaan/pemanfaatan data sudah tidak aktif.")

    patient_ihs = _verified_mapping(session, "Patient", str(patient.id))
    encounter_id = _verified_mapping(session, "Encounter", str(visit.id))
    signing_user_id = resume.signed_by or resume.created_by
    practitioner_id = _verified_mapping(session, "Practitioner", str(signing_user_id))
    org_id = _verified_mapping(
        session, "Organization", str(visit.facility_id), expected_external_id=organization_ihs
    )
    location_id = _verified_mapping(session, "Location", location_local_key(visit))

    replacements = {
        f"Patient/demo-patient-{patient.id}": f"Patient/{patient_ihs}",
        f"Encounter/demo-encounter-{visit.id}": f"Encounter/{encounter_id}",
        f"Practitioner/demo-practitioner-{signing_user_id}": f"Practitioner/{practitioner_id}",
    }
    # Every diagnosis reference must already have an acknowledged Condition POST response.
    def replace_condition_refs(value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "reference" and isinstance(item, str) and item.startswith("Condition/demo-condition-"):
                    result[key] = _condition_external_reference(session, visit.id, item)
                else:
                    result[key] = replace_condition_refs(item)
            return result
        if isinstance(value, list):
            return [replace_condition_refs(item) for item in value]
        if isinstance(value, str):
            return replacements.get(value, value)
        return value

    payload = replace_condition_refs(payload)
    payload.pop("id", None)
    payload.pop("extension", None)
    payload["identifier"] = [{
        "use": "official",
        "system": f"http://sys-ids.kemkes.go.id/composition/{org_id}",
        "value": f"resume-{resume.id}-v{getattr(resume, 'version', 1)}",
    }]
    payload["status"] = "final"
    payload["type"] = {"coding": [{
        "system": "http://loinc.org",
        "code": "88645-7",
        "display": "Outpatient hospital Discharge summary",
    }], "text": "Resume Medis Rawat Jalan"}
    payload["category"] = [{"coding": [{
        "system": "http://loinc.org", "code": "LP173421-1", "display": "Report"
    }]}]
    payload["title"] = "Resume Medis Rawat Jalan"
    payload["confidentiality"] = "N"
    # Map the demo SOAP sections to the terminology published for the outpatient RME playbook.
    section_mapping = {
        "S - Subjective": ("Anamnesis", "http://terminology.kemkes.go.id", "TK000003", "Anamnesis"),
        "O - Objective": ("Pemeriksaan Fisik", "http://terminology.kemkes.go.id", "TK000007", "Pemeriksaan Fisik"),
        "A - Assessment": ("Diagnosis", "http://terminology.kemkes.go.id", "TK000004", "Diagnosis"),
        "P - Plan": ("Perencanaan Perawatan", "http://loinc.org", "18776-5", "Plan of care note"),
        "Tindak lanjut": ("Rencana Tindak Lanjut", "http://loinc.org", "8653-8", "Hospital Discharge instructions"),
    }
    mapped_sections = []
    diagnosis_entries = []
    for section in payload.get("section") or []:
        old_title = str(section.get("title") or "")
        if old_title == "Diagnosis terverifikasi":
            diagnosis_entries.extend(section.get("entry") or [])
            continue
        mapping = section_mapping.get(old_title)
        if not mapping:
            raise SATUSEHATWorkflowError("Ada section Composition yang belum punya mapping terminologi Fase 5.")
        title, system, code, display = mapping
        mapped = dict(section)
        mapped["title"] = title
        mapped["code"] = {"coding": [{"system": system, "code": code, "display": display}]}
        mapped_sections.append(mapped)
    if diagnosis_entries:
        diagnosis_section = next((item for item in mapped_sections if item["title"] == "Diagnosis"), None)
        if diagnosis_section is None:
            raise SATUSEHATWorkflowError("Section Diagnosis tidak ditemukan untuk mereferensikan Condition.")
        diagnosis_section["entry"] = list(diagnosis_section.get("entry") or []) + diagnosis_entries
    payload["section"] = mapped_sections

    # Attach the actual submitted Observations to the physical-examination section.
    observation_rows = session.scalars(
        select(OutboxSync).where(
            OutboxSync.visit_id == visit.id,
            OutboxSync.resource_type == "Observation",
            OutboxSync.idempotency_key.like(f"phase6:Observation:visit-{visit.id}:%"),
        ).order_by(OutboxSync.id)
    ).all()
    if observation_rows:
        physical_section = next((item for item in mapped_sections if item["title"] == "Pemeriksaan Fisik"), None)
        if physical_section is None:
            raise SATUSEHATWorkflowError("Section Pemeriksaan Fisik tidak tersedia untuk memuat Observation.")
        entries = list(physical_section.get("entry") or [])
        for item in observation_rows:
            sent = session.scalar(select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == item.id))
            if sent is None or sent.status != "succeeded" or not sent.external_resource_id:
                raise SATUSEHATWorkflowError("Kirim seluruh Observation terlebih dahulu sebelum Composition.")
            entries.append({"reference": f"Observation/{sent.external_resource_id}"})
        physical_section["entry"] = entries

    impression_rows = session.scalars(
        select(OutboxSync).where(
            OutboxSync.visit_id == visit.id,
            OutboxSync.resource_type == "ClinicalImpression",
            OutboxSync.idempotency_key.like(f"phase6:ClinicalImpression:visit-{visit.id}:%"),
        ).order_by(OutboxSync.id)
    ).all()
    if impression_rows:
        anamnesis_section = next((item for item in mapped_sections if item["title"] == "Anamnesis"), None)
        if anamnesis_section is None:
            raise SATUSEHATWorkflowError("Section Anamnesis tidak tersedia untuk memuat ClinicalImpression.")
        entries = list(anamnesis_section.get("entry") or [])
        for item in impression_rows:
            sent = session.scalar(select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == item.id))
            if sent is None or sent.status != "succeeded" or not sent.external_resource_id:
                raise SATUSEHATWorkflowError("Kirim ClinicalImpression terlebih dahulu sebelum Composition.")
            entries.append({"reference": f"ClinicalImpression/{sent.external_resource_id}"})
        anamnesis_section["entry"] = entries

    # Location is checked/mapped before allowing submission, even when this minimal Composition
    # profile does not include a Location element directly.
    _ = location_id
    return payload


def _external_id_for_demo_resource(
    session: Session, visit_id: int, resource_type: str, demo_id: str
) -> str:
    rows = session.scalars(
        select(OutboxSync).where(
            OutboxSync.visit_id == visit_id,
            OutboxSync.resource_type == resource_type,
            OutboxSync.is_demo.is_(True),
        ).order_by(OutboxSync.id.desc())
    ).all()
    for item in rows:
        try:
            payload = json.loads(item.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("id") != demo_id:
            continue
        sent = session.scalar(select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == item.id))
        if sent is not None and sent.status == "succeeded" and sent.external_resource_id:
            return sent.external_resource_id
    raise SATUSEHATWorkflowError(
        f"Resource {resource_type} yang dirujuk belum dikirim atau belum menerima ID eksternal terkonfirmasi."
    )


def _prepare_observation(
    session: Session, outbox: OutboxSync, visit: Visit, patient: Patient, organization_ihs: str
) -> dict[str, Any]:
    payload = json.loads(outbox.payload_json)
    vitals = session.scalar(select(VitalSigns).where(VitalSigns.visit_id == visit.id))
    if vitals is None:
        raise SATUSEHATWorkflowError("Tanda vital sumber tidak ditemukan.")
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Consent pembukaan/pemanfaatan data sudah tidak aktif.")
    patient_id = _verified_mapping(session, "Patient", str(patient.id))
    encounter_id = _verified_mapping(session, "Encounter", str(visit.id))
    practitioner_id = _verified_mapping(session, "Practitioner", str(vitals.recorded_by))
    organization_id = _verified_mapping(
        session, "Organization", str(visit.facility_id), expected_external_id=organization_ihs
    )
    demo_id = str(payload.get("id") or "")
    if not re.fullmatch(r"demo-observation-[0-9]+-[A-Za-z0-9-]+", demo_id):
        raise SATUSEHATWorkflowError("ID Observation demo tidak dikenal.")
    payload.pop("id", None)
    payload["identifier"] = [{
        "use": "official",
        "system": f"http://sys-ids.kemkes.go.id/observation/{organization_id}",
        "value": f"vitals-{vitals.id}-{demo_id.rsplit('-', 1)[-1]}",
    }]
    replacements = {
        f"Patient/demo-patient-{patient.id}": f"Patient/{patient_id}",
        f"Encounter/demo-encounter-{visit.id}": f"Encounter/{encounter_id}",
        f"Practitioner/demo-practitioner-{vitals.recorded_by}": f"Practitioner/{practitioner_id}",
    }
    return _map_references(payload, replacements)


def _prepare_clinical_impression(
    session: Session, outbox: OutboxSync, visit: Visit, patient: Patient, resume: ResumeMedical,
    organization_ihs: str
) -> dict[str, Any]:
    payload = json.loads(outbox.payload_json)
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Consent pembukaan/pemanfaatan data sudah tidak aktif.")
    patient_id = _verified_mapping(session, "Patient", str(patient.id))
    encounter_id = _verified_mapping(session, "Encounter", str(visit.id))
    assessor_local = resume.signed_by or resume.created_by
    practitioner_id = _verified_mapping(session, "Practitioner", str(assessor_local))
    _verified_mapping(session, "Organization", str(visit.facility_id), expected_external_id=organization_ihs)
    demo_id = str(payload.get("id") or "")
    if not demo_id.startswith(f"demo-clinical-impression-{visit.id}-v"):
        raise SATUSEHATWorkflowError("ID ClinicalImpression demo tidak dikenal.")
    for problem in payload.get("problem") or []:
        reference = (problem or {}).get("reference") or ""
        mapped = _condition_external_reference(session, visit.id, reference)
        problem["reference"] = mapped
    for investigation in payload.get("investigation") or []:
        for item in investigation.get("item") or []:
            reference = (item or {}).get("reference") or ""
            match = re.fullmatch(r"Observation/(demo-observation-[0-9]+-[A-Za-z0-9-]+)", reference)
            if not match:
                raise SATUSEHATWorkflowError("Referensi Observation dalam ClinicalImpression tidak valid.")
            item["reference"] = f"Observation/{_external_id_for_demo_resource(session, visit.id, 'Observation', match.group(1))}"
    payload.pop("id", None)
    payload["subject"] = {"reference": f"Patient/{patient_id}"}
    payload["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    payload["assessor"] = {"reference": f"Practitioner/{practitioner_id}"}
    return payload


def _prepare_encounter_update(
    session: Session, outbox: OutboxSync, visit: Visit, patient: Patient, organization_ihs: str
) -> dict[str, Any]:
    payload = json.loads(outbox.payload_json)
    if payload.get("resourceType") != "Encounter" or not visit.dpjp_user_id:
        raise SATUSEHATWorkflowError("Encounter update memerlukan DPJP dan payload yang benar.")
    patient_id = _verified_mapping(session, "Patient", str(patient.id))
    encounter_id = _verified_mapping(session, "Encounter", str(visit.id))
    practitioner_id = _verified_mapping(session, "Practitioner", str(visit.dpjp_user_id))
    organization_id = _verified_mapping(
        session, "Organization", str(visit.facility_id), expected_external_id=organization_ihs
    )
    location_id = _verified_mapping(session, "Location", location_local_key(visit))
    diagnosis_rows = session.scalars(select(Diagnosis).where(
        Diagnosis.visit_id == visit.id, Diagnosis.status == "confirmed", Diagnosis.code_verified.is_(True)
    ).order_by(Diagnosis.id)).all()
    if not diagnosis_rows:
        raise SATUSEHATWorkflowError("Encounter update memerlukan diagnosis dokter yang kode ICD-10-nya diverifikasi.")
    for diagnosis in diagnosis_rows:
        condition_ref = f"Condition/demo-condition-{diagnosis.id}"
        external_ref = _condition_external_reference(session, visit.id, condition_ref)
        entry = next((row for row in payload.get("diagnosis", [])
                      if (row.get("condition") or {}).get("reference") == condition_ref), None)
        if entry is None:
            raise SATUSEHATWorkflowError("Encounter tidak memuat semua diagnosis terverifikasi.")
        entry["condition"]["reference"] = external_ref
    payload["id"] = encounter_id
    payload["identifier"] = [{
        "use": "official", "system": f"http://sys-ids.kemkes.go.id/encounter/{organization_id}",
        "value": visit.visit_number,
    }]
    replacements = {
        f"Patient/demo-patient-{patient.id}": f"Patient/{patient_id}",
        f"Practitioner/demo-practitioner-{visit.dpjp_user_id}": f"Practitioner/{practitioner_id}",
        f"Organization/demo-organization-{visit.facility_id}": f"Organization/{organization_id}",
    }
    payload = _map_references(payload, replacements)
    for location in payload.get("location") or []:
        local_ref = (location.get("location") or {}).get("reference") or ""
        if local_ref.startswith("Location/demo-location-"):
            location["location"]["reference"] = f"Location/{location_id}"
    return payload


def prepare_sandbox_payload(session: Session, user: User, outbox_id: int, client: SATUSEHATClient) -> dict[str, Any]:
    """Prepare mapped payload for review. Never sends anything over the network."""
    require_permission(user, "satusehat:manage")
    outbox = session.get(OutboxSync, outbox_id)
    if outbox is None or not outbox.is_demo or outbox.status != "queued":
        raise SATUSEHATWorkflowError("Hanya outbox demo berstatus queued yang dapat dipersiapkan.")
    visit = session.get(Visit, outbox.visit_id)
    if visit is None or not visit.is_demo or visit.status != "finished":
        raise SATUSEHATWorkflowError("Kunjungan harus finished dan berstatus demo.")
    patient = session.get(Patient, visit.patient_id)
    if patient is None or not patient.is_demo:
        raise SATUSEHATWorkflowError("Pasien bukan data demo.")
    if not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Consent pembukaan/pemanfaatan data belum aktif.")
    resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit.id))
    if resume is None or resume.status != "final" or not resume.finalized_at:
        raise SATUSEHATWorkflowError("Resume final belum tersedia.")
    preflight = build_visit_sandbox_preflight(session, user, visit.id, client.env)
    if not preflight["ready"]:
        failed = [str(item["item"]) for item in preflight["checks"] if not item["passed"]]
        raise SATUSEHATWorkflowError("Preflight belum lengkap: " + ", ".join(failed[:8]))
    if outbox.resource_type == "Condition":
        payload = _prepare_condition(session, outbox, visit, patient, client.organization_ihs_id)
    elif outbox.resource_type == "Observation":
        payload = _prepare_observation(session, outbox, visit, patient, client.organization_ihs_id)
    elif outbox.resource_type == "ClinicalImpression":
        payload = _prepare_clinical_impression(session, outbox, visit, patient, resume, client.organization_ihs_id)
    elif outbox.resource_type == "Encounter":
        payload = _prepare_encounter_update(session, outbox, visit, patient, client.organization_ihs_id)
    elif outbox.resource_type == "Composition":
        payload = _prepare_composition(session, outbox, visit, patient, resume, client.organization_ihs_id)
    else:
        raise SATUSEHATWorkflowError("Jenis resource outbox belum didukung.")
    validate_sandbox_resource(payload)
    return payload


def transmit_outbox_item_sandbox(
    session: Session,
    user: User,
    outbox_id: int,
    *,
    client: SATUSEHATClient | None = None,
    confirmed_demo_only: bool,
) -> SATUSEHATTransmission:
    """One explicit POST at a time; uncertain outcomes are not retried automatically."""
    require_permission(user, "satusehat:manage")
    if not confirmed_demo_only:
        raise SATUSEHATWorkflowError("Konfirmasi pengiriman payload fiktif ke sandbox wajib dicentang.")
    api = client or SATUSEHATClient()
    if not api.network_enabled or api.mode != "sandbox":
        raise SATUSEHATWorkflowError("Pengiriman hanya boleh diaktifkan secara eksplisit untuk sandbox.")
    payload = prepare_sandbox_payload(session, user, outbox_id, api)
    outbox = session.get(OutboxSync, outbox_id)
    transmission = session.scalar(
        select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == outbox_id)
    )
    if transmission is not None:
        if transmission.status == "succeeded":
            return transmission
        if transmission.status in {"sending", "uncertain", "blocked"}:
            raise SATUSEHATWorkflowError(
                "Hasil transmisi sebelumnya belum aman untuk diulang; rekonsiliasi manual diperlukan."
            )
        if transmission.status != "failed":
            raise SATUSEHATWorkflowError("Status transmisi tidak mendukung percobaan ulang.")
        transmission.status = "sending"
        transmission.attempt_count += 1
        transmission.last_attempt_by = user.id
        transmission.updated_at = utc_now()
        transmission.http_status = None
        transmission.operation_outcome_codes_json = "[]"
        transmission.response_summary = None
        transmission.completed_at = None
    else:
        transmission = SATUSEHATTransmission(
            outbox_id=outbox.id,
            status="sending",
            attempt_count=1,
            last_attempt_by=user.id,
            is_demo=True,
        )
        session.add(transmission)
        session.flush()
    session.commit()
    session.refresh(transmission)

    try:
        if outbox.resource_type == "Encounter":
            response = api.update_resource("Encounter", str(payload.get("id") or ""), payload)
            external_id = str(payload.get("id") or "")
        else:
            response = api.post_resource(outbox.resource_type, payload)
            external_id = response.payload.get("id")
            if not isinstance(external_id, str) or not is_safe_external_id(external_id):
                location = str(response.headers.get("Location") or response.headers.get("location") or "")
                match = re.search(
                    r"/(Condition|Composition|Observation|ClinicalImpression|Encounter)/([A-Za-z0-9.-]{1,128})(?:/_history/[0-9]+)?$",
                    location,
                )
                external_id = match.group(2) if match else None
        if not external_id or not is_safe_external_id(external_id):
            raise SATUSEHATClientError(
                "POST mendapat respons sukses tetapi ID resource tidak dapat dipastikan.",
                status_code=response.status_code,
                uncertain=True,
            )
        transmission.status = "succeeded"
        transmission.external_resource_id = external_id
        transmission.http_status = response.status_code
        transmission.operation_outcome_codes_json = "[]"
        transmission.response_summary = f"HTTP {response.status_code}; ID resource tercatat."
        transmission.completed_at = utc_now()
        audit_status = "succeeded"
    except SATUSEHATClientError as exc:
        transmission.status = "uncertain" if exc.uncertain else "failed"
        transmission.http_status = exc.status_code
        transmission.operation_outcome_codes_json = json.dumps(exc.issue_codes, separators=(",", ":"))
        transmission.response_summary = str(exc)[:500]
        transmission.completed_at = utc_now()
        audit_status = transmission.status
    except Exception:
        # A transport failure may happen after the server accepted the POST. Never auto-retry.
        transmission.status = "uncertain"
        transmission.response_summary = "Kesalahan tak terduga; penerimaan resource belum dapat dipastikan."
        transmission.completed_at = utc_now()
        audit_status = transmission.status

    transmission.updated_at = utc_now()
    append_audit(
        session, user, "satusehat.sandbox_transmission", "OutboxSync", outbox_id,
        {"resource_type": outbox.resource_type, "status": audit_status,
         "attempt_count": transmission.attempt_count, "http_status": transmission.http_status,
         "issue_codes": json.loads(transmission.operation_outcome_codes_json),
         "external_resource_id": transmission.external_resource_id, "payload_body_logged": False},
    )
    session.commit()
    session.refresh(transmission)
    return transmission


def list_transmissions(session: Session, user) -> list[SATUSEHATTransmission]:
    require_permission(user, "satusehat:read")
    rows = session.scalars(
        select(SATUSEHATTransmission).where(SATUSEHATTransmission.is_demo.is_(True))
        .order_by(SATUSEHATTransmission.created_at.desc()).limit(200)
    ).all()
    append_audit(session, user, "satusehat.transmission_list_read", "SATUSEHATTransmission", "list",
                 {"count": len(rows)})
    session.commit()
    return rows


def queue_visit_phase6_resources(session: Session, user: User, visit_id: int) -> list[OutboxSync]:
    """Queue FHIR resources for a finished demo visit; no network calls occur here."""
    require_permission(user, "satusehat:manage")
    visit = session.get(Visit, visit_id)
    if visit is None or not visit.is_demo or visit.status != "finished":
        raise SATUSEHATWorkflowError("Fase 6 hanya dapat menyiapkan kunjungan demo berstatus finished.")
    patient = session.get(Patient, visit.patient_id)
    if patient is None or not patient.is_demo or not _latest_consent(session, patient.id):
        raise SATUSEHATWorkflowError("Pasien demo dan consent pembukaan/pemanfaatan data aktif diperlukan.")
    resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit.id))
    if resume is None or resume.status != "final" or not resume.finalized_at:
        raise SATUSEHATWorkflowError("Resume final belum tersedia.")
    diagnoses = session.scalars(select(Diagnosis).where(
        Diagnosis.visit_id == visit.id,
        Diagnosis.status == "confirmed",
        Diagnosis.code_verified.is_(True),
    ).order_by(Diagnosis.id)).all()
    if not diagnoses:
        raise SATUSEHATWorkflowError("Minimal satu diagnosis confirmed dan kode ICD-10 terverifikasi diperlukan.")
    vitals = session.scalar(select(VitalSigns).where(VitalSigns.visit_id == visit.id))
    if vitals is None:
        raise SATUSEHATWorkflowError("Tanda vital harus tersedia sebelum menyiapkan Observation.")
    observations = build_vital_observations(patient, visit, vitals)
    if not observations:
        raise SATUSEHATWorkflowError("Tidak ada nilai tanda vital yang dapat dipetakan ke Observation.")
    anamnesis = session.scalar(select(Anamnesis).where(Anamnesis.visit_id == visit.id))
    encounter_payload = build_encounter_update(patient, visit, diagnoses)
    impression_payload = build_clinical_impression(patient, visit, anamnesis, resume, diagnoses, observations)
    condition_payloads = [build_condition(patient, visit, diagnosis) for diagnosis in diagnoses]
    composition_payload = build_composition(patient, visit, resume, diagnoses)
    staged: list[tuple[str, dict[str, Any], str]] = []
    for diagnosis, payload in zip(diagnoses, condition_payloads):
        prior_sent = False
        prior_rows = session.scalars(select(OutboxSync).where(
            OutboxSync.visit_id == visit.id, OutboxSync.resource_type == "Condition",
            OutboxSync.is_demo.is_(True),
        ).order_by(OutboxSync.id.desc())).all()
        for prior in prior_rows:
            try:
                prior_payload = json.loads(prior.payload_json)
            except json.JSONDecodeError:
                continue
            if prior_payload.get("id") != f"demo-condition-{diagnosis.id}":
                continue
            prior_tx = session.scalar(select(SATUSEHATTransmission).where(SATUSEHATTransmission.outbox_id == prior.id))
            if prior_tx is not None and prior_tx.status == "succeeded" and prior_tx.external_resource_id:
                prior_sent = True
                break
        if not prior_sent:
            staged.append(("Condition", payload,
                           f"phase6:Condition:visit-{visit.id}:diagnosis-{diagnosis.id}"))
    staged.extend(("Observation", payload, f"phase6:Observation:visit-{visit.id}:{payload['id']}")
                  for payload in observations)
    staged.append(("ClinicalImpression", impression_payload,
                   f"phase6:ClinicalImpression:visit-{visit.id}:resume-{resume.id}-v{resume.version}"))
    staged.append(("Encounter", encounter_payload, f"phase6:Encounter:update-visit-{visit.id}:v1"))
    staged.append(("Composition", composition_payload,
                   f"phase6:Composition:visit-{visit.id}:resume-{resume.id}-v{resume.version}"))

    queued: list[OutboxSync] = []
    for resource_type, payload, key in staged:
        existing = session.scalar(select(OutboxSync).where(OutboxSync.idempotency_key == key))
        if existing is not None:
            queued.append(existing)
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
        queued.append(row)
    append_audit(
        session, user, "satusehat.phase6_outbox_queued", "Visit", visit.id,
        {"resource_types": [kind for kind, _, _ in staged], "outbox_count": len(queued),
         "mode": "mock_queue_only", "network_request": False},
    )
    session.commit()
    for item in queued:
        session.refresh(item)
    return queued
