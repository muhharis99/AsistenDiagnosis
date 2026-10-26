from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Claim(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draf"
        SUBMITTED = "SUBMITTED", "Diajukan"
        ADJUDICATED = "ADJUDICATED", "Diputuskan"
        REJECTED = "REJECTED", "Ditolak"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Dibayar sebagian"
        PAID = "PAID", "Lunas"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim_no = models.CharField(max_length=48, unique=True)
    registration = models.ForeignKey(
        "frontoffice.Registration", on_delete=models.PROTECT, related_name="payer_claims"
    )
    invoice = models.ForeignKey(
        "cashier.Invoice", on_delete=models.PROTECT, related_name="payer_claims"
    )
    coverage_assignment = models.ForeignKey(
        "payer.RegistrationCoverage", on_delete=models.PROTECT, related_name="claims"
    )
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payer_claims_created"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["registration", "coverage_assignment"], name="uniq_claim_registration_coverage"
            ),
            models.CheckConstraint(condition=models.Q(claimed_amount__gt=0), name="claim_amount_positive"),
        ]
        indexes = [models.Index(fields=["status", "created_at"])]

    @property
    def adjudication(self):
        return self.adjudications.order_by("-version").first()

    @property
    def allowed_amount(self):
        row = self.adjudication
        return row.allowed_amount if row else Decimal("0.00")

    @property
    def payer_balance(self):
        from receivables.models import ReceivableLedgerEntry

        values = ReceivableLedgerEntry.objects.filter(
            claim=self, account_type=ReceivableLedgerEntry.AccountType.PAYER
        ).values("direction").annotate(total=Sum("amount"))
        totals = {row["direction"]: row["total"] or Decimal("0.00") for row in values}
        return totals.get(ReceivableLedgerEntry.Direction.DEBIT, Decimal("0.00")) - totals.get(
            ReceivableLedgerEntry.Direction.CREDIT, Decimal("0.00")
        )

    @property
    def patient_balance(self):
        from receivables.models import ReceivableLedgerEntry

        values = ReceivableLedgerEntry.objects.filter(
            claim=self, account_type=ReceivableLedgerEntry.AccountType.PATIENT
        ).values("direction").annotate(total=Sum("amount"))
        totals = {row["direction"]: row["total"] or Decimal("0.00") for row in values}
        return totals.get(ReceivableLedgerEntry.Direction.DEBIT, Decimal("0.00")) - totals.get(
            ReceivableLedgerEntry.Direction.CREDIT, Decimal("0.00")
        )

    def __str__(self) -> str:
        return self.claim_no


class ClaimLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="lines")
    invoice_line = models.ForeignKey(
        "cashier.InvoiceLine", on_delete=models.PROTECT, null=True, blank=True, related_name="payer_claim_lines"
    )
    code_snapshot = models.CharField(max_length=80)
    display_snapshot = models.CharField(max_length=240)
    quantity = models.PositiveIntegerField(default=1)
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["code_snapshot"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="claim_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(claimed_amount__gt=0), name="claim_line_amount_positive"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Baris klaim tersimpan tidak dapat ditimpa.")
        if self.claim_id and Claim.objects.filter(pk=self.claim_id).exclude(status=Claim.Status.DRAFT).exists():
            raise ValidationError("Baris klaim hanya dapat dibuat saat klaim masih DRAFT.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Baris klaim bersifat append-only.")


class ClaimAdjudication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="adjudications")
    version = models.PositiveSmallIntegerField(default=1)
    allowed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    denied_amount = models.DecimalField(max_digits=14, decimal_places=2)
    patient_responsibility = models.DecimalField(max_digits=14, decimal_places=2)
    external_reference = models.CharField(max_length=120)
    reason = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claim_adjudications_recorded"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["claim", "version"], name="uniq_claim_adjudication_version"),
            models.CheckConstraint(condition=models.Q(allowed_amount__gte=0), name="claim_allowed_nonnegative"),
            models.CheckConstraint(condition=models.Q(denied_amount__gte=0), name="claim_denied_nonnegative"),
            models.CheckConstraint(condition=models.Q(patient_responsibility__gte=0), name="claim_patient_share_nonnegative"),
            models.CheckConstraint(condition=~models.Q(external_reference=""), name="claim_adjudication_reference_not_blank"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Hasil adjudikasi tersimpan tidak dapat ditimpa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Adjudikasi klaim bersifat append-only.")


class ClaimCollection(models.Model):
    class CollectionType(models.TextChoices):
        PAYER_REMITTANCE = "PAYER_REMITTANCE", "Pembayaran penjamin"
        PATIENT_PAYMENT = "PATIENT_PAYMENT", "Pembayaran pasien"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="collections")
    collection_type = models.CharField(max_length=20, choices=CollectionType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    external_reference = models.CharField(max_length=120)
    idempotency_key = models.CharField(max_length=120, unique=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claim_collections_recorded"
    )
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["received_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="claim_collection_amount_positive"),
            models.CheckConstraint(condition=~models.Q(external_reference=""), name="claim_collection_reference_not_blank"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Penerimaan klaim tersimpan tidak dapat ditimpa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Penerimaan klaim tidak dapat dihapus; pembalikan harus melalui prosedur ter-audit.")
