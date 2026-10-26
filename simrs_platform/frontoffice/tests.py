from datetime import date
import uuid
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from frontoffice.models import QueueTicket, Registration
from frontoffice.services import WorkflowConflict, arrive_registration, create_registration, transition_queue
from identity.models import RoleAssignment
from mpi.models import Patient
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db

@pytest.fixture
def registrar_context():
    user = get_user_model().objects.create_user(username="fo-registrar", password="synthetic-test-password")
    unit = OrganizationUnit.objects.create(code="FO-TEST", name="Unit Front Office Tes", unit_type=OrganizationUnit.UnitType.CLINIC)
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.REGISTRAR)
    patient = Patient.objects.create(full_name_ciphertext="encrypted-synthetic-fixture",
        name_fingerprint=uuid.uuid4().hex, administrative_sex=Patient.AdministrativeSex.UNKNOWN)
    return {"user": user, "unit": unit, "patient": patient}

def test_registration_queue_transitions(registrar_context):
    d = registrar_context
    row = create_registration(patient_id=str(d["patient"].id), unit_id=str(d["unit"].id),
        visit_date=timezone.localdate(), actor=d["user"])
    assert row.status == Registration.Status.REGISTERED
    ticket = arrive_registration(registration_id=str(row.id), actor=d["user"])
    assert ticket.status == QueueTicket.Status.WAITING
    with pytest.raises(WorkflowConflict):
        arrive_registration(registration_id=str(row.id), actor=d["user"])
    transition_queue(ticket_id=str(ticket.id), action="call", actor=d["user"])
    ticket = transition_queue(ticket_id=str(ticket.id), action="start", actor=d["user"])
    row.refresh_from_db()
    assert row.status == Registration.Status.IN_SERVICE
    ticket = transition_queue(ticket_id=str(ticket.id), action="complete", actor=d["user"])
    row.refresh_from_db()
    assert ticket.status == QueueTicket.Status.DONE
    assert row.status == Registration.Status.COMPLETED

def test_registration_rejects_inactive_patient(registrar_context):
    d = registrar_context
    d["patient"].status = Patient.Status.MERGED
    d["patient"].merged_into = Patient.objects.create(full_name_ciphertext="synthetic-target",
        name_fingerprint=uuid.uuid4().hex, administrative_sex=Patient.AdministrativeSex.UNKNOWN)
    d["patient"].save()
    with pytest.raises(ValueError):
        create_registration(patient_id=str(d["patient"].id), unit_id=str(d["unit"].id),
            visit_date=timezone.localdate(), actor=d["user"])

def test_registration_rejects_past_date(registrar_context):
    d = registrar_context
    with pytest.raises(ValueError):
        create_registration(patient_id=str(d["patient"].id), unit_id=str(d["unit"].id),
            visit_date=date(2000, 1, 1), actor=d["user"])
