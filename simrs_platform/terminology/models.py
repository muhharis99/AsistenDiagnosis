from __future__ import annotations

from django.db import models

class CodeSystem(models.Model):
    uri = models.URLField(max_length=255)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    source_url = models.URLField(max_length=500, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["uri", "version"], name="uniq_codesystem_version")]
        ordering = ["uri", "version"]

class CodeTerm(models.Model):
    system = models.ForeignKey(CodeSystem, on_delete=models.PROTECT, related_name="terms")
    code = models.CharField(max_length=80)
    display = models.CharField(max_length=240)
    definition = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["system", "code"], name="uniq_term_per_system_version")]
        indexes = [models.Index(fields=["code"]), models.Index(fields=["display"])]
        ordering = ["system_id", "code"]
