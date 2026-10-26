from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from adt.models import Admission
from clinical.models import Encounter
from organization.models import OrganizationUnit
from platform_core.audit import record_audit_event


class ADTConflict(Exception):
    pass


@transaction.atomic
def admit_patient(*, encounter_id, ward_unit_id, admission_reason, actor):
    encounter = (
        Encounter.objects.select_for_update()
        .select_related("registration__unit")
        .filter(pk=encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError("Encounter tidak ditemukan.")
    if encounter.status != Encounter.Status.OPEN:
        raise ADTConflict("Encounter sudah ditutup.")
    ward = (
        OrganizationUnit.objects.select_for_update().filter(pk=ward_unit_id, is_active=True).first()
    )
    if ward is None or ward.unit_type != OrganizationUnit.UnitType.WARD:
        raise ValueError("Unit tujuan harus berupa ruang rawat aktif.")
    if Admission.objects.filter(encounter=encounter).exists():
        raise ADTConflict("Encounter ini sudah memiliki catatan admisi.")
    reason = admission_reason.strip()
    if not reason:
        raise ValueError("Alasan admisi wajib diisi.")
    row = Admission.objects.create(
        encounter=encounter,
        ward=ward,
        admission_reason=reason,
        admitted_by=actor,
        admitted_at=timezone.now(),
    )
    record_audit_event(
        actor=actor,
        event_type="adt.admission.created",
        subject_type="Admission",
        subject_id=str(row.id),
        metadata={"ward_code": ward.code, "encounter_id": str(encounter.id)},
        organization_unit=ward,
    )
    return row


@transaction.atomic
def discharge_patient(*, admission_id, discharge_summary, actor):
    row = (
        Admission.objects.select_for_update()
        .select_related("ward", "encounter__registration__unit")
        .filter(pk=admission_id)
        .first()
    )
    if row is None:
        raise ValueError("Catatan admisi tidak ditemukan.")
    if row.status != Admission.Status.ADMITTED:
        raise ADTConflict("Pasien tidak dalam status dirawat.")
    summary = discharge_summary.strip()
    if not summary:
        raise ValueError("Ringkasan pulang wajib diisi.")
    row.status = Admission.Status.DISCHARGED
    row.discharged_by = actor
    row.discharged_at = timezone.now()
    row.discharge_summary = summary
    row.save(update_fields=["status", "discharged_by", "discharged_at", "discharge_summary"])
    record_audit_event(
        actor=actor,
        event_type="adt.admission.discharged",
        subject_type="Admission",
        subject_id=str(row.id),
        metadata={"ward_code": row.ward.code, "encounter_id": str(row.encounter_id)},
        organization_unit=row.ward,
    )
    return row
