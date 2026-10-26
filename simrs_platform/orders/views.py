from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from clinical.models import Encounter
from identity.models import RoleAssignment
from orders.models import ServiceOrder
from orders.services import OrderConflict, cancel_service_order, create_service_order
from platform_core.authorization import has_scoped_role


DOCTOR_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.DOCTOR}
ORDER_READ_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE,
    RoleAssignment.Role.PHARMACY,
    RoleAssignment.Role.LAB,
    RoleAssignment.Role.RADIOLOGY,
    RoleAssignment.Role.AUDITOR,
}


class ServiceOrderRequest(serializers.Serializer):
    encounter_id = serializers.UUIDField()
    order_type = serializers.ChoiceField(choices=ServiceOrder.OrderType.choices)
    code = serializers.CharField(max_length=80)
    display = serializers.CharField(max_length=240)
    quantity = serializers.IntegerField(min_value=1, max_value=1000, default=1)
    instructions = serializers.CharField(required=False, allow_blank=True)
    indication = serializers.CharField(required=False, allow_blank=True)
    dose = serializers.CharField(max_length=120, required=False, allow_blank=True)
    route = serializers.CharField(max_length=80, required=False, allow_blank=True)
    frequency = serializers.CharField(max_length=120, required=False, allow_blank=True)
    duration_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    def validate(self, attrs):
        kind = attrs["order_type"]
        if kind == ServiceOrder.OrderType.MEDICATION and not all(
            attrs.get(key, "").strip() for key in ("dose", "route", "frequency")
        ):
            raise serializers.ValidationError("Order obat wajib memiliki dosis, rute, dan frekuensi.")
        if kind == ServiceOrder.OrderType.MEDICATION and not attrs.get("duration_days"):
            raise serializers.ValidationError("Durasi order obat wajib diisi.")
        if kind in {ServiceOrder.OrderType.LAB, ServiceOrder.OrderType.IMAGING} and not attrs.get("indication", "").strip():
            raise serializers.ValidationError("Indikasi klinis wajib untuk order diagnostik.")
        return attrs


class CancelRequest(serializers.Serializer):
    reason = serializers.CharField(max_length=240)


def order_data(row):
    return {
        "id": str(row.id),
        "encounter_id": str(row.encounter_id),
        "order_type": row.order_type,
        "status": row.status,
        "code": row.code_snapshot,
        "display": row.display_snapshot,
        "quantity": row.quantity,
        "instructions": row.instructions,
        "indication": row.indication,
        "dose": row.dose,
        "route": row.route,
        "frequency": row.frequency,
        "duration_days": row.duration_days,
        "ordered_at": row.ordered_at.isoformat(),
        "fulfilled_at": row.fulfilled_at.isoformat() if row.fulfilled_at else None,
    }


class ServiceOrderCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        encounter_id = request.query_params.get("encounter_id", "").strip()
        if not encounter_id:
            return Response({"detail": "encounter_id wajib diisi."}, status=400)
        encounter = Encounter.objects.select_related("registration__unit").filter(pk=encounter_id).first()
        if encounter is None:
            return Response({"detail": "Encounter tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, ORDER_READ_ROLES, unit_id=str(encounter.registration.unit_id)
        ):
            return Response({"detail": "Akses order tidak diizinkan untuk unit ini."}, status=403)
        rows = ServiceOrder.objects.filter(encounter=encounter).order_by("-ordered_at")
        return Response({"items": [order_data(row) for row in rows]})

    def post(self, request):
        serializer = ServiceOrderRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        encounter = Encounter.objects.select_related("registration__unit").filter(
            pk=data["encounter_id"]
        ).first()
        if encounter is None:
            return Response({"detail": "Encounter tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, DOCTOR_ROLES, unit_id=str(encounter.registration.unit_id)
        ):
            return Response({"detail": "Pembuatan order klinis memerlukan role dokter."}, status=403)
        try:
            row = create_service_order(actor=request.user, **data)
        except OrderConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(order_data(row), status=201)


class ServiceOrderCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        row = ServiceOrder.objects.select_related("encounter__registration__unit").filter(
            pk=order_id
        ).first()
        if row is None:
            return Response({"detail": "Order tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, DOCTOR_ROLES, unit_id=str(row.encounter.registration.unit_id)
        ):
            return Response({"detail": "Pembatalan order memerlukan role dokter."}, status=403)
        serializer = CancelRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            updated = cancel_service_order(
                order_id=str(row.id), reason=serializer.validated_data["reason"], actor=request.user
            )
        except OrderConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(order_data(updated))
