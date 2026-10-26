import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from adt.models import Admission
from adt.services import ADTConflict, admit_patient, discharge_patient
from clinical.models import Encounter
from clinical.services import create_encounter
from frontoffice.services import arrive_registration, create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def adt_context():
    user = get_user_model().objects.create_user(
        username="adt-doctor", password="synthetic-test-password"
    )
    clinic = OrganizationUnit.objects.create(
        code="ADT-CLINIC", name="Klinik ADT Tes", unit_type=OrganizationUnit.UnitType.CLINIC
    )
    ward = OrganizationUnit.objects.create(
        code="ADT-WARD", name="Ruang Rawat ADT Tes", unit_type=OrganizationUnit.UnitType.WARD
    )
    for unit in (clinic, ward):
        UserUnitAssignment.objects.create(user=user, unit=unit)
        RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.DOCTOR)
    patient = Patient.objects.create(
        full_name_ciphertext="encrypted-synthetic-fixture",
        name_fingerprint=uuid.uuid4().hex,
        administrative_sex=Patient.AdministrativeSex.UNKNOWN,
    )
    registration = create_registration(
        patient_id=str(patient.id),
        unit_id=str(clinic.id),
        visit_date=timezone.localdate(),
        actor=user,
    )
    arrive_registration(registration_id=str(registration.id), actor=user)
    encounter = create_encounter(
        registration_id=str(registration.id),
        encounter_type=Encounter.EncounterType.INPATIENT,
        chief_complaint="Keluhan sintetis",
        actor=user,
    )
    return {"user": user, "clinic": clinic, "ward": ward, "encounter": encounter}


def test_admission_and_discharge_are_audited_transitions(adt_context):
    d = adt_context
    row = admit_patient(
        encounter_id=str(d["encounter"].id),
        ward_unit_id=str(d["ward"].id),
        admission_reason="Observasi sintetis",
        actor=d["user"],
    )
    assert row.status == Admission.Status.ADMITTED
    discharged = discharge_patient(
        admission_id=str(row.id),
        discharge_summary="Ringkasan pulang sintetis",
        actor=d["user"],
    )
    assert discharged.status == Admission.Status.DISCHARGED
    with pytest.raises(ADTConflict):
        discharge_patient(
            admission_id=str(row.id),
            discharge_summary="Percobaan kedua",
            actor=d["user"],
        )


def test_admission_requires_active_ward(adt_context):
    d = adt_context
    d["ward"].unit_type = OrganizationUnit.UnitType.SUPPORT
    d["ward"].save(update_fields=["unit_type"])
    with pytest.raises(ValueError):
        admit_patient(
            encounter_id=str(d["encounter"].id),
            ward_unit_id=str(d["ward"].id),
            admission_reason="Observasi sintetis",
            actor=d["user"],
        )
