from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

def new_mrn() -> str:
    return "SIM" + uuid.uuid4().hex[:12].upper()

class Patient(models.Model):
    class AdministrativeSex(models.TextChoices):
        FEMALE = "F", "Perempuan"
        MALE = "M", "Laki-laki"
        UNKNOWN = "U", "Tidak diketahui"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Aktif"
        MERGED = "MERGED", "Digabung melalui proses ter-audit"
        DECEASED = "DECEASED", "Meninggal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mrn = models.CharField(max_length=24, unique=True, default=new_mrn)
    full_name_ciphertext = models.TextField()
    name_fingerprint = models.CharField(max_length=64, db_index=True)
    birth_date = models.DateField(null=True, blank=True)
    administrative_sex = models.CharField(max_length=1, choices=AdministrativeSex.choices, default=AdministrativeSex.UNKNOWN)
    nik_ciphertext = models.TextField(blank=True)
    nik_fingerprint = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    merged_into = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="merged_sources")
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="mpi_patients_created")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["birth_date", "name_fingerprint"]), models.Index(fields=["status", "created_at"])]
        constraints = [
            models.CheckConstraint(condition=~models.Q(full_name_ciphertext=""), name="mpi_name_ciphertext_not_blank"),
            models.CheckConstraint(condition=~models.Q(status="MERGED") | models.Q(merged_into__isnull=False), name="mpi_merged_requires_target"),
        ]

    def __str__(self) -> str:
        return self.mrn

class PatientIdentifier(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="identifiers")
    system = models.CharField(max_length=80)
    value_ciphertext = models.TextField()
    fingerprint = models.CharField(max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["patient", "system"], name="uniq_patient_identifier_system")]

class DuplicateReview(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Menunggu verifikasi"
        CONFIRMED = "CONFIRMED", "Duplikat terkonfirmasi"
        REJECTED = "REJECTED", "Bukan duplikat"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="duplicate_reviews")
    candidate = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="candidate_reviews")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField(max_length=240, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "candidate"], name="uniq_mpi_duplicate_review_pair"),
            models.CheckConstraint(condition=~models.Q(patient=models.F("candidate")), name="mpi_duplicate_pair_not_self"),
        ]

class PatientMergeEvent(models.Model):
    source = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="merge_events_as_source")
    target = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="merge_events_as_target")
    merged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=~models.Q(source=models.F("target")), name="mpi_merge_not_self")]
