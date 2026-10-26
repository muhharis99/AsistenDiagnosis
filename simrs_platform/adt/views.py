from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from adt.models import Admission
from adt.services import ADTConflict, admit_patient, discharge_patient
from clinical.models import Encounter
from identity.models import RoleAssignment
from organization.models import OrganizationUnit
from platform_core.authorization import has_scoped_role

ADT_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE,
}


class AdmissionRequest(serializers.Serializer):
    encounter_id = serializers.UUIDField()
    ward_unit_id = serializers.UUIDField()
    admission_reason = serializers.CharField(max_length=4000)


class DischargeRequest(serializers.Serializer):
    discharge_summary = serializers.CharField(max_length=10000)


def admission_data(row):
    return {
        "id": str(row.id),
        "encounter_id": str(row.encounter_id),
        "registration_no": row.encounter.registration.registration_no,
        "patient_mrn": row.encounter.registration.patient.mrn,
        "ward_unit_id": str(row.ward_id),
        "ward_code": row.ward.code,
        "status": row.status,
        "admission_reason": row.admission_reason,
        "admitted_at": row.admitted_at.isoformat(),
        "discharged_at": row.discharged_at.isoformat() if row.discharged_at else None,
        "discharge_summary": row.discharge_summary,
    }


class AdmissionCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ward_id = request.query_params.get("ward_unit_id", "").strip()
        if not ward_id:
            return Response({"detail": "ward_unit_id wajib diisi."}, status=400)
        if not has_scoped_role(request.user, ADT_ROLES, unit_id=ward_id):
            return Response({"detail": "Akses ADT tidak diizinkan untuk unit ini."}, status=403)
        rows = (
            Admission.objects.select_related(
                "encounter__registration", "encounter__registration__patient", "ward"
            )
            .filter(ward_id=ward_id)
            .order_by("-admitted_at")[:100]
        )
        return Response({"items": [admission_data(row) for row in rows]})

    def post(self, request):
        serializer = AdmissionRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        encounter = (
            Encounter.objects.select_related("registration__unit")
            .filter(pk=data["encounter_id"])
            .first()
        )
        ward = OrganizationUnit.objects.filter(pk=data["ward_unit_id"], is_active=True).first()
        if encounter is None or ward is None:
            return Response({"detail": "Encounter atau unit tujuan tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, ADT_ROLES, unit_id=str(encounter.registration.unit_id)
        ) or not has_scoped_role(request.user, ADT_ROLES, unit_id=str(ward.id)):
            return Response(
                {"detail": "Akses admisi memerlukan penugasan pada unit asal dan ruang rawat."},
                status=403,
            )
        try:
            row = admit_patient(
                encounter_id=str(encounter.id),
                ward_unit_id=str(ward.id),
                admission_reason=data["admission_reason"],
                actor=request.user,
            )
        except ADTConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        row = Admission.objects.select_related(
            "encounter__registration", "encounter__registration__patient", "ward"
        ).get(pk=row.pk)
        return Response(admission_data(row), status=201)


class AdmissionDischargeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, admission_id):
        row = (
            Admission.objects.select_related(
                "ward",
                "encounter__registration__unit",
                "encounter__registration__patient",
                "encounter__registration",
            )
            .filter(pk=admission_id)
            .first()
        )
        if row is None:
            return Response({"detail": "Catatan admisi tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, ADT_ROLES, unit_id=str(row.ward_id)):
            return Response(
                {"detail": "Akses pemulangan tidak diizinkan untuk ruang rawat ini."}, status=403
            )
        serializer = DischargeRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            updated = discharge_patient(
                admission_id=str(row.id),
                discharge_summary=serializer.validated_data["discharge_summary"],
                actor=request.user,
            )
        except ADTConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        updated = Admission.objects.select_related(
            "encounter__registration", "encounter__registration__patient", "ward"
        ).get(pk=updated.pk)
        return Response(admission_data(updated))
