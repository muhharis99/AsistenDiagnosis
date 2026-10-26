import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from clinical.models import ClinicalNote, Encounter
from clinical.services import append_clinical_note, create_encounter, record_diagnosis
from frontoffice.services import arrive_registration, create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def clinical_context():
    user = get_user_model().objects.create_user(
        username="clinical-doctor", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="CLIN-TEST", name="Klinik Tes", unit_type=OrganizationUnit.UnitType.CLINIC
    )
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.DOCTOR)
    patient = Patient.objects.create(
        full_name_ciphertext="encrypted-synthetic-fixture",
        name_fingerprint=uuid.uuid4().hex,
        administrative_sex=Patient.AdministrativeSex.UNKNOWN,
    )
    registration = create_registration(
        patient_id=str(patient.id),
        unit_id=str(unit.id),
        visit_date=timezone.localdate(),
        actor=user,
    )
    arrive_registration(registration_id=str(registration.id), actor=user)
    encounter = create_encounter(
        registration_id=str(registration.id),
        encounter_type=Encounter.EncounterType.OUTPATIENT,
        chief_complaint="Keluhan sintetis",
        actor=user,
    )
    return {"user": user, "unit": unit, "encounter": encounter}


def test_clinical_note_is_versioned_and_append_only(clinical_context):
    d = clinical_context
    first = append_clinical_note(
        encounter_id=str(d["encounter"].id),
        note_type=ClinicalNote.NoteType.PROGRESS,
        subjective="Keluhan sintetis",
        objective="",
        assessment="",
        plan="Evaluasi ulang",
        actor=d["user"],
    )
    second = append_clinical_note(
        encounter_id=str(d["encounter"].id),
        note_type=ClinicalNote.NoteType.PROGRESS,
        subjective="Perubahan keluhan",
        objective="",
        assessment="",
        plan="Tindak lanjut",
        actor=d["user"],
    )
    assert (first.version, second.version) == (1, 2)
    first.subjective = "ditimpa"
    with pytest.raises(ValidationError):
        first.save()
    with pytest.raises(ValidationError):
        first.delete()


def test_primary_diagnosis_cannot_be_duplicated(clinical_context):
    d = clinical_context
    record_diagnosis(
        encounter_id=str(d["encounter"].id),
        code="SYN-A",
        display="Diagnosis sintetis",
        is_primary=True,
        actor=d["user"],
    )
    from clinical.services import ClinicalConflict

    with pytest.raises(ClinicalConflict):
        record_diagnosis(
            encounter_id=str(d["encounter"].id),
            code="SYN-B",
            display="Diagnosis sintetis sekunder",
            is_primary=True,
            actor=d["user"],
        )
