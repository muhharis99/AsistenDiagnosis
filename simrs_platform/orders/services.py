from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from clinical.models import Encounter
from orders.models import ServiceOrder
from platform_core.audit import record_audit_event


class OrderConflict(Exception):
    pass


@transaction.atomic
def create_service_order(
    *,
    encounter_id,
    order_type,
    code,
    display,
    quantity,
    instructions,
    indication,
    dose,
    route,
    frequency,
    duration_days,
    actor,
):
    encounter = (
        Encounter.objects.select_for_update()
        .select_related("registration__unit")
        .filter(pk=encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError("Encounter tidak ditemukan.")
    if encounter.status != Encounter.Status.OPEN:
        raise OrderConflict("Encounter sudah ditutup; order baru tidak dapat dibuat.")
    code, display = code.strip(), display.strip()
    if not code or not display:
        raise ValueError("Kode dan nama order wajib diisi.")
    if quantity < 1:
        raise ValueError("Kuantitas order minimal satu.")
    if order_type == ServiceOrder.OrderType.MEDICATION:
        if not all(value.strip() for value in (dose, route, frequency)) or not duration_days:
            raise ValueError("Order obat wajib memiliki dosis, rute, frekuensi, dan durasi.")
    elif order_type in {ServiceOrder.OrderType.LAB, ServiceOrder.OrderType.IMAGING}:
        if not indication.strip():
            raise ValueError("Indikasi klinis wajib untuk order diagnostik.")
    row = ServiceOrder.objects.create(
        encounter=encounter,
        order_type=order_type,
        code_snapshot=code,
        display_snapshot=display,
        quantity=quantity,
        instructions=instructions.strip(),
        indication=indication.strip(),
        dose=dose.strip(),
        route=route.strip(),
        frequency=frequency.strip(),
        duration_days=duration_days,
        ordered_by=actor,
        ordered_at=timezone.now(),
    )
    record_audit_event(
        actor=actor,
        event_type="orders.service_order.created",
        subject_type="ServiceOrder",
        subject_id=str(row.id),
        metadata={"order_type": row.order_type, "code": row.code_snapshot, "quantity": quantity},
        organization_unit=encounter.registration.unit,
    )
    return row


@transaction.atomic
def cancel_service_order(*, order_id, reason, actor):
    row = (
        ServiceOrder.objects.select_for_update()
        .select_related("encounter__registration__unit")
        .filter(pk=order_id)
        .first()
    )
    if row is None:
        raise ValueError("Order tidak ditemukan.")
    if row.status != ServiceOrder.Status.ORDERED:
        raise OrderConflict("Hanya order berstatus ORDERED yang dapat dibatalkan.")
    reason = reason.strip()
    if not reason:
        raise ValueError("Alasan pembatalan wajib diisi.")
    row.status = ServiceOrder.Status.CANCELLED
    row.cancelled_by = actor
    row.cancelled_at = timezone.now()
    row.cancellation_reason = reason[:240]
    row.save(
        update_fields=["status", "cancelled_by", "cancelled_at", "cancellation_reason"]
    )
    record_audit_event(
        actor=actor,
        event_type="orders.service_order.cancelled",
        subject_type="ServiceOrder",
        subject_id=str(row.id),
        metadata={"order_type": row.order_type, "reason": row.cancellation_reason},
        organization_unit=row.encounter.registration.unit,
    )
    return row
