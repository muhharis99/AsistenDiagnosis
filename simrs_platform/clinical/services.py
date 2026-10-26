from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from clinical.models import ClinicalNote, Encounter, EncounterDiagnosis
from frontoffice.models import Registration
from platform_core.audit import record_audit_event


class ClinicalConflict(Exception):
    pass


@transaction.atomic
def create_encounter(*, registration_id, encounter_type, chief_complaint, actor):
    registration = (
        Registration.objects.select_for_update()
        .select_related("unit")
        .filter(pk=registration_id)
        .first()
    )
    if registration is None:
        raise ValueError("Registrasi tidak ditemukan.")
    if not registration.unit.is_active:
        raise ValueError("Unit layanan tidak aktif.")
    if registration.status not in {Registration.Status.ARRIVED, Registration.Status.IN_SERVICE}:
        raise ClinicalConflict("Pasien harus check-in sebelum encounter dibuat.")
    if Encounter.objects.filter(registration=registration).exists():
        raise ClinicalConflict("Registrasi ini sudah memiliki encounter.")
    encounter = Encounter.objects.create(
        registration=registration,
        encounter_type=encounter_type,
        chief_complaint=chief_complaint.strip(),
        created_by=actor,
    )
    record_audit_event(
        actor=actor,
        event_type="clinical.encounter.created",
        subject_type="Encounter",
        subject_id=str(encounter.id),
        metadata={
            "encounter_type": encounter_type,
            "registration_no": registration.registration_no,
        },
        organization_unit=registration.unit,
    )
    return encounter


@transaction.atomic
def append_clinical_note(
    *, encounter_id, note_type, subjective, objective, assessment, plan, actor
):
    encounter = (
        Encounter.objects.select_for_update()
        .select_related("registration__unit")
        .filter(pk=encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError("Encounter tidak ditemukan.")
    if encounter.status != Encounter.Status.OPEN:
        raise ClinicalConflict("Encounter sudah ditutup.")
    if not any(value.strip() for value in (subjective, objective, assessment, plan)):
        raise ValueError("Isi setidaknya satu bagian catatan klinis.")
    latest = encounter.notes.order_by("-version").first()
    version = latest.version + 1 if latest else 1
    note = ClinicalNote.objects.create(
        encounter=encounter,
        version=version,
        note_type=note_type,
        subjective=subjective.strip(),
        objective=objective.strip(),
        assessment=assessment.strip(),
        plan=plan.strip(),
        author=actor,
        signed_at=timezone.now(),
    )
    record_audit_event(
        actor=actor,
        event_type="clinical.note.appended",
        subject_type="Encounter",
        subject_id=str(encounter.id),
        metadata={"note_version": version, "note_type": note_type},
        organization_unit=encounter.registration.unit,
    )
    return note


@transaction.atomic
def record_diagnosis(*, encounter_id, code, display, is_primary, actor):
    encounter = (
        Encounter.objects.select_for_update()
        .select_related("registration__unit")
        .filter(pk=encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError("Encounter tidak ditemukan.")
    if encounter.status != Encounter.Status.OPEN:
        raise ClinicalConflict("Encounter sudah ditutup.")
    code = code.strip()
    display = display.strip()
    if not code or not display:
        raise ValueError("Kode dan nama diagnosis wajib diisi.")
    if encounter.diagnoses.filter(code=code).exists():
        raise ClinicalConflict("Kode diagnosis sudah tercatat pada encounter ini.")
    if is_primary and encounter.diagnoses.filter(is_primary=True).exists():
        raise ClinicalConflict("Diagnosis utama sudah ada; diagnosis baru harus sekunder.")
    diagnosis = EncounterDiagnosis.objects.create(
        encounter=encounter,
        code=code,
        display=display,
        is_primary=is_primary,
        recorded_by=actor,
    )
    record_audit_event(
        actor=actor,
        event_type="clinical.diagnosis.recorded",
        subject_type="Encounter",
        subject_id=str(encounter.id),
        metadata={"diagnosis_code": code, "is_primary": is_primary},
        organization_unit=encounter.registration.unit,
    )
    return diagnosis
