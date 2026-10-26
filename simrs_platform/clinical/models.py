from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Encounter(models.Model):
    class EncounterType(models.TextChoices):
        OUTPATIENT = "OUTPATIENT", "Rawat jalan"
        INPATIENT = "INPATIENT", "Rawat inap"
        EMERGENCY = "EMERGENCY", "Gawat darurat"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Terbuka"
        CLOSED = "CLOSED", "Ditutup"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.OneToOneField(
        "frontoffice.Registration", on_delete=models.PROTECT, related_name="encounter"
    )
    encounter_type = models.CharField(max_length=16, choices=EncounterType.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    chief_complaint = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clinical_encounters_created",
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [models.Index(fields=["status", "opened_at"])]

    def __str__(self) -> str:
        return f"{self.registration.registration_no} - {self.encounter_type}"


class ClinicalNote(models.Model):
    class NoteType(models.TextChoices):
        TRIAGE = "TRIAGE", "Triage"
        PROGRESS = "PROGRESS", "Catatan perkembangan"
        DISCHARGE = "DISCHARGE", "Catatan pulang"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="notes")
    version = models.PositiveIntegerField()
    note_type = models.CharField(max_length=12, choices=NoteType.choices)
    subjective = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="clinical_notes_authored"
    )
    signed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "version"], name="uniq_clinical_note_version"
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "Catatan klinis tersimpan tidak dapat ditimpa; tambahkan versi baru."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Catatan klinis merupakan rekam append-only.")

    def __str__(self) -> str:
        return f"{self.encounter_id}:v{self.version}"


class EncounterDiagnosis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="diagnoses")
    code = models.CharField(max_length=40)
    display = models.CharField(max_length=240)
    is_primary = models.BooleanField(default=False)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="encounter_diagnoses_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "code"], name="uniq_encounter_diagnosis_code"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.display}"
