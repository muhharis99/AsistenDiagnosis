from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from frontoffice.models import Registration
from identity.models import RoleAssignment
from mpi.models import Patient
from payer.models import Coverage, PayerOrganization, PayerPlan, RegistrationCoverage
from payer.services import assign_registration_coverage
from platform_core.audit import record_audit_event
from platform_core.authorization import has_any_scoped_role, has_scoped_role


PAYER_ADMIN_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.INSURANCE_BILLING}
PAYER_READ_ROLES = PAYER_ADMIN_ROLES | {RoleAssignment.Role.PAYER_REVIEWER, RoleAssignment.Role.AUDITOR}


def payer_access(user):
    return has_any_scoped_role(user, PAYER_READ_ROLES)


class PayerRequest(serializers.Serializer):
    code = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$")
    name = serializers.CharField(max_length=180)
    payer_type = serializers.ChoiceField(choices=PayerOrganization.PayerType.choices)


class PlanRequest(serializers.Serializer):
    payer_id = serializers.UUIDField()
    code = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,47}$")
    name = serializers.CharField(max_length=180)
    effective_from = serializers.DateField()
    effective_to = serializers.DateField(required=False, allow_null=True)
    requires_referral = serializers.BooleanField(default=False)


class CoverageRequest(serializers.Serializer):
    patient_id = serializers.UUIDField()
    plan_id = serializers.UUIDField()
    member_reference = serializers.CharField(max_length=120)
    effective_from = serializers.DateField()
    effective_to = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("effective_to") and attrs["effective_to"] < attrs["effective_from"]:
            raise serializers.ValidationError("Tanggal akhir kepesertaan harus sama atau sesudah tanggal awal.")
        if not attrs["member_reference"].strip():
            raise serializers.ValidationError("Referensi kepesertaan wajib diisi.")
        return attrs


class RegistrationCoverageRequest(serializers.Serializer):
    registration_id = serializers.UUIDField()
    coverage_id = serializers.UUIDField()
    priority = serializers.IntegerField(min_value=1, max_value=3)


def payer_data(row):
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "payer_type": row.payer_type,
        "is_active": row.is_active,
    }


def plan_data(row):
    return {
        "id": str(row.id),
        "payer_id": str(row.payer_id),
        "payer_code": row.payer.code,
        "code": row.code,
        "name": row.name,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "requires_referral": row.requires_referral,
        "is_active": row.is_active,
    }


def coverage_data(row):
    return {
        "id": str(row.id),
        "patient_mrn": row.patient.mrn,
        "plan_id": str(row.plan_id),
        "payer_code": row.plan.payer.code,
        "plan_code": row.plan.code,
        "member_reference": row.member_reference,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_active": row.is_active,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


def registration_coverage_data(row):
    return {
        "id": row.pk,
        "registration_id": str(row.registration_id),
        "coverage_id": str(row.coverage_id),
        "patient_mrn": row.coverage.patient.mrn,
        "payer_code": row.coverage.plan.payer.code,
        "plan_code": row.coverage.plan.code,
        "priority": row.priority,
        "is_primary": row.is_primary,
        "verified_at": row.verified_at.isoformat(),
    }


class PayerCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not payer_access(request.user):
            return Response({"detail": "Akses data penjamin tidak diizinkan."}, status=403)
        return Response({"items": [payer_data(x) for x in PayerOrganization.objects.order_by("code")[:500]]})

    def post(self, request):
        if not has_any_scoped_role(request.user, PAYER_ADMIN_ROLES):
            return Response({"detail": "Pembuatan penjamin memerlukan role penjamin."}, status=403)
        serializer = PayerRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        row = PayerOrganization.objects.create(**serializer.validated_data)
        record_audit_event(
            actor=request.user,
            event_type="payer.organization.created",
            subject_type="PayerOrganization",
            subject_id=str(row.id),
            metadata={"payer_code": row.code, "payer_type": row.payer_type},
        )
        return Response(payer_data(row), status=201)


class PlanCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not payer_access(request.user):
            return Response({"detail": "Akses paket penjamin tidak diizinkan."}, status=403)
        payer_id = request.query_params.get("payer_id", "").strip()
        query = PayerPlan.objects.select_related("payer").order_by("payer__code", "code")
        if payer_id:
            query = query.filter(payer_id=payer_id)
        return Response({"items": [plan_data(x) for x in query[:500]]})

    def post(self, request):
        if not has_any_scoped_role(request.user, PAYER_ADMIN_ROLES):
            return Response({"detail": "Pembuatan paket penjamin memerlukan role penjamin."}, status=403)
        serializer = PlanRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        payer = PayerOrganization.objects.filter(pk=data.pop("payer_id"), is_active=True).first()
        if payer is None:
            return Response({"detail": "Penjamin tidak ditemukan atau tidak aktif."}, status=404)
        if data.get("effective_to") and data["effective_to"] < data["effective_from"]:
            return Response({"detail": "Tanggal efektif paket tidak valid."}, status=400)
        row = PayerPlan.objects.create(payer=payer, **data)
        record_audit_event(
            actor=request.user,
            event_type="payer.plan.created",
            subject_type="PayerPlan",
            subject_id=str(row.id),
            metadata={"payer_code": payer.code, "plan_code": row.code},
        )
        return Response(plan_data(row), status=201)


class CoverageCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not payer_access(request.user):
            return Response({"detail": "Akses kepesertaan penjamin tidak diizinkan."}, status=403)
        patient_id = request.query_params.get("patient_id", "").strip()
        if not patient_id:
            return Response({"detail": "patient_id wajib diisi."}, status=400)
        rows = Coverage.objects.select_related("patient", "plan__payer").filter(
            patient_id=patient_id
        ).order_by("plan__payer__code")[:200]
        return Response({"items": [coverage_data(x) for x in rows]})

    def post(self, request):
        if not has_any_scoped_role(request.user, PAYER_ADMIN_ROLES):
            return Response({"detail": "Pembuatan kepesertaan memerlukan role penjamin."}, status=403)
        serializer = CoverageRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        patient = Patient.objects.filter(pk=data.pop("patient_id"), status=Patient.Status.ACTIVE).first()
        plan = PayerPlan.objects.select_related("payer").filter(
            pk=data.pop("plan_id"), is_active=True, payer__is_active=True
        ).first()
        if patient is None:
            return Response({"detail": "Pasien MPI tidak ditemukan atau tidak aktif."}, status=404)
        if plan is None:
            return Response({"detail": "Paket penjamin tidak ditemukan atau tidak aktif."}, status=404)
        if data["effective_from"] < plan.effective_from or (
            plan.effective_to and (data.get("effective_to") is None or data["effective_to"] > plan.effective_to)
        ):
            return Response({"detail": "Periode kepesertaan harus berada dalam masa berlaku paket."}, status=400)
        row = Coverage.objects.create(
            patient=patient,
            plan=plan,
            verified_by=request.user,
            verified_at=timezone.now(),
            **data,
        )
        record_audit_event(
            actor=request.user,
            event_type="payer.coverage.created",
            subject_type="Coverage",
            subject_id=str(row.id),
            metadata={"payer_code": plan.payer.code, "plan_code": plan.code},
        )
        return Response(coverage_data(row), status=201)


class RegistrationCoverageCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        registration_id = request.query_params.get("registration_id", "").strip()
        if not registration_id:
            return Response({"detail": "registration_id wajib diisi."}, status=400)
        registration = Registration.objects.filter(pk=registration_id).first()
        if registration is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, PAYER_READ_ROLES, unit_id=str(registration.unit_id)
        ):
            return Response({"detail": "Akses penjamin tidak diizinkan untuk unit ini."}, status=403)
        rows = RegistrationCoverage.objects.select_related(
            "registration", "coverage__patient", "coverage__plan__payer"
        ).filter(registration=registration)
        return Response({"items": [registration_coverage_data(x) for x in rows]})

    def post(self, request):
        serializer = RegistrationCoverageRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        registration = Registration.objects.filter(pk=data["registration_id"]).first()
        if registration is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, PAYER_ADMIN_ROLES, unit_id=str(registration.unit_id)
        ):
            return Response({"detail": "Penetapan penjamin memerlukan role penjamin di unit ini."}, status=403)
        try:
            row = assign_registration_coverage(actor=request.user, **data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        row = RegistrationCoverage.objects.select_related(
            "registration", "coverage__patient", "coverage__plan__payer"
        ).get(pk=row.pk)
        return Response(registration_coverage_data(row), status=201)
