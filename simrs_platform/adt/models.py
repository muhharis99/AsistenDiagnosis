from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Admission(models.Model):
    class Status(models.TextChoices):
        ADMITTED = "ADMITTED", "Dirawat"
        DISCHARGED = "DISCHARGED", "Pulang"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.OneToOneField(
        "clinical.Encounter", on_delete=models.PROTECT, related_name="admission"
    )
    ward = models.ForeignKey(
        "organization.OrganizationUnit", on_delete=models.PROTECT, related_name="admissions"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ADMITTED)
    admission_reason = models.TextField()
    admitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="admissions_created"
    )
    admitted_at = models.DateTimeField(default=timezone.now)
    discharged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admissions_discharged",
    )
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharge_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-admitted_at"]
        indexes = [models.Index(fields=["ward", "status", "admitted_at"])]

    def __str__(self) -> str:
        return f"{self.encounter_id} - {self.status}"
