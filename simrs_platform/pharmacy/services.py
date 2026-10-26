from __future__ import annotations

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from orders.models import ServiceOrder
from pharmacy.models import MedicationDispense
from platform_core.audit import record_audit_event


class DispenseConflict(Exception):
    pass


@transaction.atomic
def dispense_medication(*, order_id, quantity, batch_reference, actor):
    order = (
        ServiceOrder.objects.select_for_update()
        .select_related("encounter__registration__unit")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        raise ValueError("Order obat tidak ditemukan.")
    if order.order_type != ServiceOrder.OrderType.MEDICATION:
        raise ValueError("Hanya order obat yang dapat diproses farmasi.")
    if order.status not in {ServiceOrder.Status.ORDERED, ServiceOrder.Status.IN_PROGRESS}:
        raise DispenseConflict("Order obat tidak lagi dapat diserahkan.")
    if quantity < 1:
        raise ValueError("Jumlah yang diserahkan minimal satu.")
    dispensed = order.dispenses.aggregate(total=Sum("quantity"))["total"] or 0
    if dispensed + quantity > order.quantity:
        raise ValueError("Jumlah penyerahan melebihi jumlah yang diresepkan.")
    last_sequence = order.dispenses.aggregate(value=Max("sequence"))["value"] or 0
    row = MedicationDispense.objects.create(
        order=order,
        sequence=last_sequence + 1,
        quantity=quantity,
        batch_reference=batch_reference.strip(),
        dispensed_by=actor,
        dispensed_at=timezone.now(),
    )
    total_dispensed = dispensed + quantity
    complete = total_dispensed == order.quantity
    order.status = ServiceOrder.Status.COMPLETED if complete else ServiceOrder.Status.IN_PROGRESS
    if complete:
        order.fulfilled_at = timezone.now()
        order.save(update_fields=["status", "fulfilled_at"])
    else:
        order.save(update_fields=["status"])
    record_audit_event(
        actor=actor,
        event_type="pharmacy.medication.dispensed",
        subject_type="ServiceOrder",
        subject_id=str(order.id),
        metadata={
            "dispense_id": str(row.id),
            "sequence": row.sequence,
            "quantity": quantity,
            "total_dispensed": total_dispensed,
            "order_status": order.status,
        },
        organization_unit=order.encounter.registration.unit,
    )
    return row
