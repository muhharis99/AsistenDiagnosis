from __future__ import annotations

from datetime import date
from typing import Any
from django.db import transaction
from django.utils import timezone

from frontoffice.models import QueueCounter, QueueTicket, Registration, RegistrationSequence
from mpi.models import Patient
from organization.models import OrganizationUnit
from platform_core.audit import record_audit_event

class WorkflowConflict(Exception):
    pass

@transaction.atomic
def create_registration(*, patient_id: str, unit_id: str, visit_date: date, actor: Any) -> Registration:
    if visit_date < timezone.localdate():
        raise ValueError("Tanggal kunjungan tidak boleh sebelum hari ini.")
    patient = Patient.objects.select_for_update().filter(pk=patient_id, status=Patient.Status.ACTIVE).first()
    if patient is None:
        raise ValueError("Pasien tidak ditemukan atau tidak aktif di MPI.")
    unit = OrganizationUnit.objects.select_for_update().filter(pk=unit_id, is_active=True).first()
    if unit is None:
        raise ValueError("Unit layanan tidak ditemukan atau tidak aktif.")
    counter, _ = RegistrationSequence.objects.get_or_create(unit=unit, visit_date=visit_date, defaults={"last_value": 0})
    counter = RegistrationSequence.objects.select_for_update().get(pk=counter.pk)
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    number = f"REG-{visit_date:%Y%m%d}-{unit.code}-{counter.last_value:05d}"
    row = Registration.objects.create(registration_no=number, patient=patient, unit=unit,
                                      visit_date=visit_date, registered_by=actor)
    record_audit_event(actor=actor, event_type="frontoffice.registration.created",
        subject_type="Registration", subject_id=str(row.id),
        metadata={"unit_code": unit.code, "visit_date": visit_date.isoformat()}, organization_unit=unit)
    return row

@transaction.atomic
def arrive_registration(*, registration_id: str, actor: Any) -> QueueTicket:
    row = Registration.objects.select_for_update().select_related("unit").filter(pk=registration_id).first()
    if row is None:
        raise ValueError("Registrasi tidak ditemukan.")
    if row.status != Registration.Status.REGISTERED:
        raise WorkflowConflict("Antrean hanya dapat dibuat satu kali untuk registrasi berstatus REGISTERED.")
    if row.visit_date != timezone.localdate():
        raise WorkflowConflict("Antrean hanya dibuat pada tanggal kunjungan hari ini.")
    counter, _ = QueueCounter.objects.get_or_create(unit=row.unit, queue_date=row.visit_date, defaults={"last_number": 0})
    counter = QueueCounter.objects.select_for_update().get(pk=counter.pk)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    code = f"{row.unit.code}-{row.visit_date:%y%m%d}-{counter.last_number:03d}"
    ticket = QueueTicket.objects.create(registration=row, unit=row.unit, queue_date=row.visit_date,
        number=counter.last_number, queue_code=code, created_by=actor)
    row.status = Registration.Status.ARRIVED
    row.save(update_fields=["status"])
    record_audit_event(actor=actor, event_type="frontoffice.queue.created", subject_type="QueueTicket",
        subject_id=str(ticket.id), metadata={"unit_code": row.unit.code, "queue_code": code}, organization_unit=row.unit)
    return ticket

@transaction.atomic
def transition_queue(*, ticket_id: str, action: str, actor: Any, reason: str = "") -> QueueTicket:
    ticket = QueueTicket.objects.select_for_update().select_related("unit", "registration").filter(pk=ticket_id).first()
    if ticket is None:
        raise ValueError("Tiket antrean tidak ditemukan.")
    transitions = {
        "call": (QueueTicket.Status.WAITING, QueueTicket.Status.CALLED),
        "start": (QueueTicket.Status.CALLED, QueueTicket.Status.SERVING),
        "complete": (QueueTicket.Status.SERVING, QueueTicket.Status.DONE),
        "cancel": (QueueTicket.Status.WAITING, QueueTicket.Status.CANCELLED),
    }
    if action not in transitions:
        raise ValueError("Aksi antrean tidak dikenal.")
    expected, target = transitions[action]
    if ticket.status != expected:
        raise WorkflowConflict("Transisi status antrean tidak valid.")
    now = timezone.now()
    ticket.status = target
    fields = ["status"]
    if action == "call":
        ticket.called_at = now
        fields.append("called_at")
    elif action == "start":
        ticket.started_at = now
        fields.append("started_at")
        ticket.registration.status = Registration.Status.IN_SERVICE
        ticket.registration.save(update_fields=["status"])
    elif action == "complete":
        ticket.completed_at = now
        fields.append("completed_at")
        ticket.registration.status = Registration.Status.COMPLETED
        ticket.registration.save(update_fields=["status"])
    ticket.save(update_fields=fields)
    record_audit_event(actor=actor, event_type="frontoffice.queue." + action, subject_type="QueueTicket",
        subject_id=str(ticket.id), metadata={"unit_code": ticket.unit.code, "status": ticket.status,
        "reason_recorded": bool(reason.strip())}, organization_unit=ticket.unit)
    return ticket
