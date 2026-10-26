from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from diagnostics.models import DiagnosticResult
from orders.models import ServiceOrder
from platform_core.audit import record_audit_event


class DiagnosticConflict(Exception):
    pass


@transaction.atomic
def record_diagnostic_result(*, order_id, result_text, result_status, actor):
    order = (
        ServiceOrder.objects.select_for_update()
        .select_related("encounter__registration__unit")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        raise ValueError("Order diagnostik tidak ditemukan.")
    if order.order_type not in {ServiceOrder.OrderType.LAB, ServiceOrder.OrderType.IMAGING}:
        raise ValueError("Hasil hanya dapat dicatat untuk order laboratorium atau radiologi.")
    if order.status == ServiceOrder.Status.CANCELLED:
        raise DiagnosticConflict("Order yang dibatalkan tidak dapat diberi hasil.")
    result_text = result_text.strip()
    if not result_text:
        raise ValueError("Hasil pemeriksaan wajib diisi.")
    latest = order.diagnostic_results.order_by("-version").first()
    if latest is None and result_status == DiagnosticResult.ResultStatus.AMENDED:
        raise DiagnosticConflict("Amendemen hanya dapat dibuat setelah hasil sebelumnya.")
    if latest and latest.result_status in {
        DiagnosticResult.ResultStatus.FINAL,
        DiagnosticResult.ResultStatus.AMENDED,
    }:
        if result_status != DiagnosticResult.ResultStatus.AMENDED:
            raise DiagnosticConflict("Hasil final hanya dapat dikoreksi melalui amendemen.")
    elif result_status == DiagnosticResult.ResultStatus.AMENDED:
        raise DiagnosticConflict("Amendemen membutuhkan hasil final sebelumnya.")
    version = latest.version + 1 if latest else 1
    row = DiagnosticResult.objects.create(
        order=order,
        version=version,
        result_status=result_status,
        result_text=result_text,
        recorded_by=actor,
        recorded_at=timezone.now(),
    )
    if result_status in {DiagnosticResult.ResultStatus.FINAL, DiagnosticResult.ResultStatus.AMENDED}:
        order.status = ServiceOrder.Status.COMPLETED
        order.fulfilled_at = timezone.now()
        order.save(update_fields=["status", "fulfilled_at"])
    else:
        order.status = ServiceOrder.Status.IN_PROGRESS
        order.save(update_fields=["status"])
    record_audit_event(
        actor=actor,
        event_type="diagnostics.result.recorded",
        subject_type="ServiceOrder",
        subject_id=str(order.id),
        metadata={
            "result_version": version,
            "result_status": result_status,
            "order_type": order.order_type,
        },
        organization_unit=order.encounter.registration.unit,
    )
    return row
