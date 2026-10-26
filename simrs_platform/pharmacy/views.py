from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from identity.models import RoleAssignment
from orders.models import ServiceOrder
from pharmacy.models import MedicationDispense
from pharmacy.services import DispenseConflict, dispense_medication
from platform_core.authorization import has_scoped_role


PHARMACY_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.PHARMACY}


class DispenseRequest(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=1000)
    batch_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)


def dispense_data(row):
    return {
        "id": str(row.id),
        "order_id": str(row.order_id),
        "sequence": row.sequence,
        "quantity": row.quantity,
        "batch_reference": row.batch_reference,
        "dispensed_at": row.dispensed_at.isoformat(),
        "dispensed_by_id": row.dispensed_by_id,
    }


class MedicationDispenseCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = ServiceOrder.objects.select_related("encounter__registration__unit").filter(
            pk=order_id
        ).first()
        if order is None:
            return Response({"detail": "Order obat tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, PHARMACY_ROLES, unit_id=str(order.encounter.registration.unit_id)
        ):
            return Response({"detail": "Akses farmasi tidak diizinkan untuk unit ini."}, status=403)
        rows = MedicationDispense.objects.filter(order=order).select_related("dispensed_by")
        return Response({"items": [dispense_data(row) for row in rows]})

    def post(self, request, order_id):
        order = ServiceOrder.objects.select_related("encounter__registration__unit").filter(
            pk=order_id
        ).first()
        if order is None:
            return Response({"detail": "Order obat tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, PHARMACY_ROLES, unit_id=str(order.encounter.registration.unit_id)
        ):
            return Response({"detail": "Penyerahan obat memerlukan role farmasi."}, status=403)
        serializer = DispenseRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            row = dispense_medication(
                order_id=str(order.id), actor=request.user, **serializer.validated_data
            )
        except DispenseConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(dispense_data(row), status=201)
