from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ServiceOrder(models.Model):
    class OrderType(models.TextChoices):
        MEDICATION = "MEDICATION", "Obat"
        LAB = "LAB", "Laboratorium"
        IMAGING = "IMAGING", "Radiologi"
        PROCEDURE = "PROCEDURE", "Tindakan"

    class Status(models.TextChoices):
        ORDERED = "ORDERED", "Dipesan"
        IN_PROGRESS = "IN_PROGRESS", "Sedang diproses"
        COMPLETED = "COMPLETED", "Selesai"
        CANCELLED = "CANCELLED", "Dibatalkan"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        "clinical.Encounter", on_delete=models.PROTECT, related_name="service_orders"
    )
    order_type = models.CharField(max_length=12, choices=OrderType.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ORDERED)
    code_snapshot = models.CharField(max_length=80)
    display_snapshot = models.CharField(max_length=240)
    quantity = models.PositiveSmallIntegerField(default=1)
    instructions = models.TextField(blank=True)
    indication = models.TextField(blank=True)
    dose = models.CharField(max_length=120, blank=True)
    route = models.CharField(max_length=80, blank=True)
    frequency = models.CharField(max_length=120, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="service_orders_created"
    )
    ordered_at = models.DateTimeField(default=timezone.now)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="service_orders_cancelled",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-ordered_at"]
        indexes = [models.Index(fields=["order_type", "status", "ordered_at"])]

    def __str__(self) -> str:
        return f"{self.code_snapshot} - {self.display_snapshot}"
