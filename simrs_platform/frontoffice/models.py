from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class RegistrationSequence(models.Model):
    unit = models.ForeignKey("organization.OrganizationUnit", on_delete=models.PROTECT)
    visit_date = models.DateField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "visit_date"], name="uniq_registration_sequence_unit_date"
            )
        ]


class Registration(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Terdaftar"
        ARRIVED = "ARRIVED", "Sudah datang"
        IN_SERVICE = "IN_SERVICE", "Sedang dilayani"
        COMPLETED = "COMPLETED", "Selesai"
        CANCELLED = "CANCELLED", "Dibatalkan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration_no = models.CharField(max_length=80, unique=True)
    patient = models.ForeignKey(
        "mpi.Patient", on_delete=models.PROTECT, related_name="registrations"
    )
    unit = models.ForeignKey(
        "organization.OrganizationUnit", on_delete=models.PROTECT, related_name="registrations"
    )
    visit_date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.REGISTERED, db_index=True
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registrations_created"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["unit", "visit_date", "status"])]


class QueueCounter(models.Model):
    unit = models.ForeignKey("organization.OrganizationUnit", on_delete=models.PROTECT)
    queue_date = models.DateField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "queue_date"], name="uniq_queue_counter_unit_date"
            )
        ]


class QueueTicket(models.Model):
    class Status(models.TextChoices):
        WAITING = "WAITING", "Menunggu"
        CALLED = "CALLED", "Dipanggil"
        SERVING = "SERVING", "Sedang dilayani"
        DONE = "DONE", "Selesai"
        CANCELLED = "CANCELLED", "Dibatalkan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.OneToOneField(
        Registration, on_delete=models.PROTECT, related_name="queue_ticket"
    )
    unit = models.ForeignKey(
        "organization.OrganizationUnit", on_delete=models.PROTECT, related_name="queue_tickets"
    )
    queue_date = models.DateField(db_index=True)
    number = models.PositiveIntegerField()
    queue_code = models.CharField(max_length=80, unique=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.WAITING, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="queue_tickets_created"
    )
    called_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "queue_date", "number"], name="uniq_queue_number_unit_date"
            )
        ]
        indexes = [models.Index(fields=["unit", "queue_date", "status"])]

    def __str__(self):
        return self.queue_code
