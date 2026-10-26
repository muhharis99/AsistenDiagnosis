from __future__ import annotations

from django.db import transaction

from frontoffice.models import Registration
from payer.models import Coverage, RegistrationCoverage
from platform_core.audit import record_audit_event


@transaction.atomic
def assign_registration_coverage(*, registration_id, coverage_id, priority, actor):
    registration = (
        Registration.objects.select_for_update()
        .select_related("unit", "patient")
        .filter(pk=registration_id)
        .first()
    )
    if registration is None:
        raise ValueError("Registrasi tidak ditemukan.")
    if not registration.unit.is_active:
        raise ValueError("Unit layanan tidak aktif.")
    coverage = (
        Coverage.objects.select_for_update()
        .select_related("plan__payer", "patient")
        .filter(pk=coverage_id)
        .first()
    )
    if coverage is None:
        raise ValueError("Kepesertaan penjamin tidak ditemukan.")
    if coverage.patient_id != registration.patient_id:
        raise ValueError("Kepesertaan penjamin bukan milik pasien pada registrasi ini.")
    if not coverage.active_on(registration.visit_date):
        raise ValueError("Kepesertaan atau paket penjamin tidak aktif pada tanggal kunjungan.")
    if priority < 1 or priority > 3:
        raise ValueError("Urutan COB harus antara 1 dan 3.")
    if (
        RegistrationCoverage.objects.filter(
            registration=registration, priority__lt=priority
        ).exists()
        is False
        and priority != 1
    ):
        raise ValueError("Penjamin harus ditambahkan berurutan mulai dari prioritas 1.")
    if (
        priority > 1
        and not RegistrationCoverage.objects.filter(
            registration=registration, priority=priority - 1
        ).exists()
    ):
        raise ValueError("Prioritas COB sebelumnya harus sudah terdaftar.")
    row = RegistrationCoverage.objects.create(
        registration=registration,
        coverage=coverage,
        priority=priority,
        verified_by=actor,
    )
    record_audit_event(
        actor=actor,
        event_type="payer.registration_coverage.assigned",
        subject_type="Registration",
        subject_id=str(registration.id),
        metadata={
            "registration_no": registration.registration_no,
            "payer_code": coverage.plan.payer.code,
            "plan_code": coverage.plan.code,
            "priority": priority,
        },
        organization_unit=registration.unit,
    )
    return row
