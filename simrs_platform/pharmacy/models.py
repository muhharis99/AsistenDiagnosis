from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class MedicationDispense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        "orders.ServiceOrder", on_delete=models.PROTECT, related_name="dispenses"
    )
    sequence = models.PositiveSmallIntegerField()
    quantity = models.PositiveSmallIntegerField()
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="medication_dispenses"
    )
    batch_reference = models.CharField(max_length=120, blank=True)
    dispensed_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "sequence"], name="uniq_dispense_order_sequence"
            )
        ]

    def __str__(self) -> str:
        return f"{self.order_id}:dispense-{self.sequence}"
