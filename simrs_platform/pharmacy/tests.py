import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from clinical.models import Encounter
from clinical.services import create_encounter
from frontoffice.services import arrive_registration, create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from orders.models import ServiceOrder
from orders.services import create_service_order
from organization.models import OrganizationUnit, UserUnitAssignment
from pharmacy.services import DispenseConflict, dispense_medication

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy_context():
    user = get_user_model().objects.create_user(
        username="pharmacy-user", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="PHARM-TEST", name="Unit Farmasi Tes", unit_type=OrganizationUnit.UnitType.CLINIC
    )
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.DOCTOR)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.PHARMACY)
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
    order = create_service_order(
        encounter_id=str(encounter.id),
        order_type=ServiceOrder.OrderType.MEDICATION,
        code="SYN-MED",
        display="Obat sintetis",
        quantity=5,
        instructions="Gunakan sesuai petunjuk dokter",
        indication="Keluhan sintetis",
        dose="1 unit",
        route="oral",
        frequency="2 kali sehari",
        duration_days=3,
        actor=user,
    )
    return {"user": user, "unit": unit, "order": order}


def test_partial_dispensing_completes_only_at_prescribed_quantity(pharmacy_context):
    d = pharmacy_context
    first = dispense_medication(
        order_id=str(d["order"].id),
        quantity=2,
        batch_reference="SYN-BATCH-1",
        actor=d["user"],
    )
    d["order"].refresh_from_db()
    assert first.sequence == 1
    assert d["order"].status == ServiceOrder.Status.IN_PROGRESS
    second = dispense_medication(
        order_id=str(d["order"].id),
        quantity=3,
        batch_reference="SYN-BATCH-2",
        actor=d["user"],
    )
    d["order"].refresh_from_db()
    assert second.sequence == 2
    assert d["order"].status == ServiceOrder.Status.COMPLETED


def test_dispensing_cannot_exceed_prescribed_quantity(pharmacy_context):
    d = pharmacy_context
    with pytest.raises(ValueError):
        dispense_medication(
            order_id=str(d["order"].id),
            quantity=6,
            batch_reference="SYN-BATCH",
            actor=d["user"],
        )
    d["order"].status = ServiceOrder.Status.CANCELLED
    d["order"].save(update_fields=["status"])
    with pytest.raises(DispenseConflict):
        dispense_medication(
            order_id=str(d["order"].id),
            quantity=1,
            batch_reference="SYN-BATCH",
            actor=d["user"],
        )
