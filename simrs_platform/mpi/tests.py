import os
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from identity.models import RoleAssignment
from mpi.models import Patient
from mpi.services import DuplicatePatientCandidate, create_patient, decrypt_value, find_duplicate_candidates
from organization.models import OrganizationUnit, UserUnitAssignment
from rest_framework.test import APIClient

os.environ.setdefault("MPI_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MPI_HMAC_KEY", "test-only-hmac-key-with-more-than-32-bytes")

pytestmark = pytest.mark.django_db

@pytest.fixture
def registrar():
    user = get_user_model().objects.create_user(username="registrar", password="test-pass-strong-2026")
    unit = OrganizationUnit.objects.create(code="TEST-REG", name="Unit Tes", unit_type=OrganizationUnit.UnitType.CLINIC)
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, role=RoleAssignment.Role.REGISTRAR, unit=unit)
    return user

def test_identity_fields_are_encrypted_and_duplicate_is_not_merged(registrar):
    patient = create_patient(full_name="SINTETIS DUA", birth_date=None,
        administrative_sex=Patient.AdministrativeSex.UNKNOWN, nik="", actor=registrar)
    assert "SINTETIS DUA" not in patient.full_name_ciphertext
    assert decrypt_value(patient.full_name_ciphertext) == "SINTETIS DUA"
    candidates = find_duplicate_candidates(full_name="SINTETIS DUA", birth_date=None)
    assert [str(p.id) for p in candidates] == [str(patient.id)]
    with pytest.raises(DuplicatePatientCandidate):
        create_patient(full_name="SINTETIS DUA", birth_date=None,
            administrative_sex=Patient.AdministrativeSex.UNKNOWN, nik="", actor=registrar)
    patient.refresh_from_db()
    assert patient.status == Patient.Status.ACTIVE
    assert patient.merged_into is None

def test_mpi_endpoint_requires_role_and_returns_no_plaintext_name(registrar):
    client = APIClient()
    client.force_authenticate(user=registrar)
    response = client.post("/api/mpi/patients/", {
        "full_name": "PASIEN SINTETIS 0002", "birth_date": "2000-01-02",
        "administrative_sex": "U", "nik": "",
    }, format="json")
    assert response.status_code == 201
    patient = Patient.objects.get(id=response.data["id"])
    assert patient.mrn == response.data["mrn"]
    assert "full_name" not in response.data
    assert "nik" not in response.data
