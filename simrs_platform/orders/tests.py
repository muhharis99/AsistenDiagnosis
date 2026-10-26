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
from orders.services import OrderConflict, cancel_service_order, create_service_order
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def order_context():
    user = get_user_model().objects.create_user(
        username="orders-doctor", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="ORD-TEST", name="Unit Order Tes", unit_type=OrganizationUnit.UnitType.CLINIC
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


def test_medication_order_requires_complete_directions(order_context):
    d = order_context
    with pytest.raises(ValueError):
        create_service_order(
            encounter_id=str(d["encounter"].id),
            order_type=ServiceOrder.OrderType.MEDICATION,
            code="SYN-MED",
            display="Obat sintetis",
            quantity=3,
            instructions="",
            indication="",
            dose="",
            route="",
            frequency="",
            duration_days=None,
            actor=d["user"],
        )


def test_order_cancellation_is_audited_and_controlled(order_context):
    d = order_context
    row = create_service_order(
        encounter_id=str(d["encounter"].id),
        order_type=ServiceOrder.OrderType.LAB,
        code="SYN-LAB",
        display="Pemeriksaan sintetis",
        quantity=1,
        instructions="",
        indication="Evaluasi sintetis",
        dose="",
        route="",
        frequency="",
        duration_days=None,
        actor=d["user"],
    )
    cancelled = cancel_service_order(
        order_id=str(row.id), reason="Duplikasi order sintetis", actor=d["user"]
    )
    assert cancelled.status == ServiceOrder.Status.CANCELLED
    with pytest.raises(OrderConflict):
        cancel_service_order(order_id=str(row.id), reason="Coba ulang", actor=d["user"])
