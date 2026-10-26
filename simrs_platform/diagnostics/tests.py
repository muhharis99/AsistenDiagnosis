import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from clinical.models import Encounter
from clinical.services import create_encounter
from diagnostics.models import DiagnosticResult
from diagnostics.services import DiagnosticConflict, record_diagnostic_result
from frontoffice.services import arrive_registration, create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from orders.models import ServiceOrder
from orders.services import create_service_order
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def diagnostics_context():
    user = get_user_model().objects.create_user(
        username="lab-user", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="LAB-TEST", name="Unit Lab Tes", unit_type=OrganizationUnit.UnitType.SUPPORT
    )
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.DOCTOR)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.LAB)
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
        actor=user,
    )
    return {"user": user, "unit": unit, "order": order}


def test_result_finalization_and_amendment_are_versioned(diagnostics_context):
    d = diagnostics_context
    first = record_diagnostic_result(
        order_id=str(d["order"].id),
        result_text="Hasil sintetis pertama",
        result_status=DiagnosticResult.ResultStatus.FINAL,
        actor=d["user"],
    )
    d["order"].refresh_from_db()
    assert first.version == 1
    assert d["order"].status == ServiceOrder.Status.COMPLETED
    second = record_diagnostic_result(
        order_id=str(d["order"].id),
        result_text="Koreksi sintetis",
        result_status=DiagnosticResult.ResultStatus.AMENDED,
        actor=d["user"],
    )
    assert second.version == 2
    first.result_text = "ditimpa"
    with pytest.raises(ValidationError):
        first.save()
    with pytest.raises(ValidationError):
        first.delete()


def test_final_result_must_be_amended_not_replaced(diagnostics_context):
    d = diagnostics_context
    record_diagnostic_result(
        order_id=str(d["order"].id),
        result_text="Hasil sintetis final",
        result_status=DiagnosticResult.ResultStatus.FINAL,
        actor=d["user"],
    )
    with pytest.raises(DiagnosticConflict):
        record_diagnostic_result(
            order_id=str(d["order"].id),
            result_text="Hasil final kedua",
            result_status=DiagnosticResult.ResultStatus.FINAL,
            actor=d["user"],
        )
