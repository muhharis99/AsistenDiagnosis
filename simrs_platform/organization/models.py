from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class OrganizationUnit(models.Model):
    class UnitType(models.TextChoices):
        FACILITY = "FACILITY", "Fasilitas"
        CLINIC = "CLINIC", "Poliklinik"
        WARD = "WARD", "Ruang Rawat"
        SERVICE = "SERVICE", "Unit Layanan"
        SUPPORT = "SUPPORT", "Unit Penunjang"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    unit_type = models.CharField(max_length=16, choices=UnitType.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(code=""), name="org_unit_code_not_blank")
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class UserUnitAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="unit_assignments"
    )
    unit = models.ForeignKey(
        OrganizationUnit, on_delete=models.PROTECT, related_name="user_assignments"
    )
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "unit"], name="uniq_user_org_unit")]
