from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

class AuditChainHead(models.Model):
    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_sequence = models.PositiveBigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default="0" * 64)
    updated_at = models.DateTimeField(auto_now=True)

class AuditEvent(models.Model):
    sequence = models.PositiveBigIntegerField(primary_key=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    event_type = models.CharField(max_length=100)
    subject_type = models.CharField(max_length=80)
    subject_id = models.CharField(max_length=80)
    organization_unit = models.ForeignKey("organization.OrganizationUnit", on_delete=models.PROTECT, null=True, blank=True)
    metadata = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64)
    event_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["sequence"]
        indexes = [models.Index(fields=["subject_type", "subject_id", "created_at"])]

    def save(self, *args, **kwargs):
        if self.pk is not None and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("AuditEvent bersifat append-only; buat event koreksi, jangan ubah event lama.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent bersifat append-only dan tidak dapat dihapus.")
