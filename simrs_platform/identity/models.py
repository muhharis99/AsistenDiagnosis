from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

class RoleAssignment(models.Model):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "Administrator Sistem"
        REGISTRAR = "REGISTRAR", "Petugas Pendaftaran"
        MEDICAL_RECORDS = "MEDICAL_RECORDS", "Perekam Medis"
        DOCTOR = "DOCTOR", "Dokter"
        NURSE = "NURSE", "Perawat/Bidan"
        PHARMACY = "PHARMACY", "Farmasi"
        LAB = "LAB", "Laboratorium"
        CASHIER = "CASHIER", "Kasir"
        AUDITOR = "AUDITOR", "Auditor"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="simrs_role_assignments")
    role = models.CharField(max_length=24, choices=Role.choices)
    unit = models.ForeignKey("organization.OrganizationUnit", on_delete=models.PROTECT, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="roles_granted")

    class Meta:
        indexes = [models.Index(fields=["user", "role", "is_active"])]

    def currently_valid(self) -> bool:
        now = timezone.now()
        return self.is_active and self.starts_at <= now and (self.ends_at is None or self.ends_at > now)
