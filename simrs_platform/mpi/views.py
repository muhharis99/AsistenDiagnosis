from __future__ import annotations

import json
from datetime import date
from django.http import HttpRequest
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import RoleAssignment
from mpi.models import Patient
from mpi.services import DuplicatePatientCandidate, create_patient, decrypt_value, fingerprint
from organization.models import UserUnitAssignment
from platform_core.audit import record_audit_event

READ_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.REGISTRAR,
    RoleAssignment.Role.MEDICAL_RECORDS, RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE, RoleAssignment.Role.AUDITOR,
}
CREATE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.REGISTRAR}

def _has_role(user, roles: set[str]) -> bool:
    from django.utils import timezone
    now = timezone.now()
    return RoleAssignment.objects.filter(user=user, role__in=roles, is_active=True, starts_at__lte=now).filter(
        models_q_ends_at(now)
    ).exists()

def models_q_ends_at(now):
    from django.db.models import Q
    return Q(ends_at__isnull=True) | Q(ends_at__gt=now)

def _has_any_active_unit(user) -> bool:
    return UserUnitAssignment.objects.filter(user=user, is_active=True, unit__is_active=True).exists()

class PatientCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: HttpRequest) -> Response:
        if not _has_role(request.user, READ_ROLES) or not _has_any_active_unit(request.user):
            return Response({"detail": "Akses MPI tidak diizinkan untuk peran/unit ini."}, status=403)
        mrn = request.query_params.get("mrn", "").strip()
        if not mrn:
            return Response({"detail": "Pencarian wajib menggunakan MRN; daftar pasien umum dinonaktifkan."}, status=400)
        patient = Patient.objects.filter(mrn=mrn).first()
        record_audit_event(actor=request.user, event_type="mpi.patient.read", subject_type="Patient",
                           subject_id=str(patient.id) if patient else "not-found", metadata={"search_type": "MRN"})
        if patient is None:
            return Response({"detail": "Pasien tidak ditemukan."}, status=404)
        return Response({
            "id": str(patient.id), "mrn": patient.mrn, "birth_date": patient.birth_date,
            "administrative_sex": patient.administrative_sex, "status": patient.status,
            "version": patient.version,
        })

    def post(self, request: HttpRequest) -> Response:
        if not _has_role(request.user, CREATE_ROLES) or not _has_any_active_unit(request.user):
            return Response({"detail": "Akses pendaftaran MPI tidak diizinkan."}, status=403)
        try:
            raw_date = request.data.get("birth_date")
            birth_date = date.fromisoformat(raw_date) if raw_date else None
            patient = create_patient(
                full_name=str(request.data.get("full_name", "")),
                birth_date=birth_date,
                administrative_sex=str(request.data.get("administrative_sex", Patient.AdministrativeSex.UNKNOWN)),
                nik=str(request.data.get("nik", "")),
                actor=request.user,
            )
        except DuplicatePatientCandidate as exc:
            return Response({"detail": "Kandidat duplikat ditemukan; tidak ada merge otomatis.",
                             "candidate_ids": exc.candidate_ids, "action": "manual_review"}, status=409)
        except (ValueError, RuntimeError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"id": str(patient.id), "mrn": patient.mrn, "status": patient.status}, status=201)

class PatientDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: HttpRequest, patient_id) -> Response:
        if not _has_role(request.user, READ_ROLES) or not _has_any_active_unit(request.user):
            return Response({"detail": "Akses MPI tidak diizinkan untuk peran/unit ini."}, status=403)
        patient = Patient.objects.filter(id=patient_id).first()
        record_audit_event(actor=request.user, event_type="mpi.patient.read", subject_type="Patient",
                           subject_id=str(patient.id) if patient else str(patient_id), metadata={"search_type": "UUID"})
        if patient is None:
            return Response({"detail": "Pasien tidak ditemukan."}, status=404)
        return Response({
            "id": str(patient.id), "mrn": patient.mrn, "birth_date": patient.birth_date,
            "administrative_sex": patient.administrative_sex, "status": patient.status,
            "version": patient.version,
        })
