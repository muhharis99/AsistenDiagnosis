from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class DiagnosticResult(models.Model):
    class ResultStatus(models.TextChoices):
        PRELIMINARY = "PRELIMINARY", "Sementara"
        FINAL = "FINAL", "Final"
        AMENDED = "AMENDED", "Koreksi/amendemen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        "orders.ServiceOrder", on_delete=models.PROTECT, related_name="diagnostic_results"
    )
    version = models.PositiveIntegerField()
    result_status = models.CharField(max_length=12, choices=ResultStatus.choices)
    result_text = models.TextField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="diagnostic_results_recorded"
    )
    recorded_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["order", "version"], name="uniq_diagnostic_result_version")
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Hasil diagnostik tersimpan tidak dapat ditimpa; tambahkan versi baru.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Hasil diagnostik merupakan rekam append-only.")

    def __str__(self) -> str:
        return f"{self.order_id}:v{self.version}"
