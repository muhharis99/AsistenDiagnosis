from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PayerOrganization(models.Model):
    class PayerType(models.TextChoices):
        NATIONAL = "NATIONAL", "Program nasional"
        PRIVATE = "PRIVATE", "Asuransi swasta"
        EMPLOYER = "EMPLOYER", "Penjamin perusahaan"
        OTHER = "OTHER", "Lainnya"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    payer_type = models.CharField(max_length=12, choices=PayerType.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(code=""), name="payer_code_not_blank"),
            models.CheckConstraint(condition=~models.Q(name=""), name="payer_name_not_blank"),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class PayerPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payer = models.ForeignKey(PayerOrganization, on_delete=models.PROTECT, related_name="plans")
    code = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=180)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    requires_referral = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["payer__code", "code"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(code=""), name="payer_plan_code_not_blank"),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="payer_plan_effective_dates_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Coverage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        "mpi.Patient", on_delete=models.PROTECT, related_name="payer_coverages"
    )
    plan = models.ForeignKey(PayerPlan, on_delete=models.PROTECT, related_name="coverages")
    member_reference = models.CharField(max_length=120)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payer_coverages_verified",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["plan__payer__code", "member_reference"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "member_reference"], name="uniq_coverage_plan_member_reference"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="coverage_effective_dates_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(member_reference=""), name="coverage_member_reference_not_blank"
            ),
        ]

    def active_on(self, visit_date) -> bool:
        return (
            self.is_active
            and self.plan.is_active
            and self.plan.payer.is_active
            and self.effective_from <= visit_date
            and (self.effective_to is None or self.effective_to >= visit_date)
            and self.plan.effective_from <= visit_date
            and (self.plan.effective_to is None or self.plan.effective_to >= visit_date)
            and self.verified_at is not None
        )

    def __str__(self) -> str:
        return f"{self.plan.code} - {self.member_reference}"


class RegistrationCoverage(models.Model):
    registration = models.ForeignKey(
        "frontoffice.Registration", on_delete=models.PROTECT, related_name="coverage_assignments"
    )
    coverage = models.ForeignKey(
        Coverage, on_delete=models.PROTECT, related_name="registration_assignments"
    )
    priority = models.PositiveSmallIntegerField()
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="registration_coverages_verified",
    )
    verified_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority"]
        constraints = [
            models.UniqueConstraint(
                fields=["registration", "priority"], name="uniq_registration_coverage_priority"
            ),
            models.UniqueConstraint(
                fields=["registration", "coverage"], name="uniq_registration_coverage_pair"
            ),
            models.CheckConstraint(
                condition=models.Q(priority__gte=1) & models.Q(priority__lte=3),
                name="registration_coverage_priority_range",
            ),
        ]

    @property
    def is_primary(self) -> bool:
        return self.priority == 1

    def __str__(self) -> str:
        return f"{self.registration_id} - {self.coverage_id} ({self.priority})"
