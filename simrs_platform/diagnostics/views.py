from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from diagnostics.models import DiagnosticResult
from diagnostics.services import DiagnosticConflict, record_diagnostic_result
from identity.models import RoleAssignment
from orders.models import ServiceOrder
from platform_core.authorization import has_scoped_role


RESULT_READ_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE,
    RoleAssignment.Role.LAB,
    RoleAssignment.Role.RADIOLOGY,
    RoleAssignment.Role.AUDITOR,
}


class DiagnosticResultRequest(serializers.Serializer):
    result_status = serializers.ChoiceField(choices=DiagnosticResult.ResultStatus.choices)
    result_text = serializers.CharField(max_length=20000)


def result_data(row):
    return {
        "id": str(row.id),
        "order_id": str(row.order_id),
        "version": row.version,
        "result_status": row.result_status,
        "result_text": row.result_text,
        "recorded_by_id": row.recorded_by_id,
        "recorded_at": row.recorded_at.isoformat(),
    }


def role_for_order(order):
    if order.order_type == ServiceOrder.OrderType.LAB:
        return {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.LAB}
    if order.order_type == ServiceOrder.OrderType.IMAGING:
        return {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.RADIOLOGY}
    return set()


class DiagnosticResultCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = ServiceOrder.objects.select_related("encounter__registration__unit").filter(
            pk=order_id
        ).first()
        if order is None:
            return Response({"detail": "Order diagnostik tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, RESULT_READ_ROLES, unit_id=str(order.encounter.registration.unit_id)
        ):
            return Response({"detail": "Akses hasil diagnostik tidak diizinkan."}, status=403)
        rows = order.diagnostic_results.select_related("recorded_by").all()
        return Response({"items": [result_data(row) for row in rows]})

    def post(self, request, order_id):
        order = ServiceOrder.objects.select_related("encounter__registration__unit").filter(
            pk=order_id
        ).first()
        if order is None:
            return Response({"detail": "Order diagnostik tidak ditemukan."}, status=404)
        roles = role_for_order(order)
        if not roles or not has_scoped_role(
            request.user, roles, unit_id=str(order.encounter.registration.unit_id)
        ):
            return Response({"detail": "Role unit tidak sesuai untuk order diagnostik ini."}, status=403)
        serializer = DiagnosticResultRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            row = record_diagnostic_result(
                order_id=str(order.id), actor=request.user, **serializer.validated_data
            )
        except DiagnosticConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(result_data(row), status=201)
