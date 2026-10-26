from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ReceivableLedgerEntry(models.Model):
    class AccountType(models.TextChoices):
        PAYER = "PAYER", "Piutang penjamin"
        PATIENT = "PATIENT", "Piutang pasien"

    class Direction(models.TextChoices):
        DEBIT = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Kredit"

    class EntryType(models.TextChoices):
        CLAIM_SUBMITTED = "CLAIM_SUBMITTED", "Klaim diajukan"
        DENIAL_ADJUSTMENT = "DENIAL_ADJUSTMENT", "Penyesuaian klaim ditolak"
        PATIENT_RESPONSIBILITY_TRANSFER = "PATIENT_RESPONSIBILITY_TRANSFER", "Pemindahan tanggung jawab pasien"
        COB_TRANSFER_TO_SECONDARY = "COB_TRANSFER_TO_SECONDARY", "Pemindahan saldo ke penjamin berikutnya"
        PAYER_REMITTANCE = "PAYER_REMITTANCE", "Penerimaan penjamin"
        PATIENT_PAYMENT = "PATIENT_PAYMENT", "Penerimaan pasien"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(
        "claims.Claim", on_delete=models.PROTECT, related_name="receivable_entries"
    )
    invoice = models.ForeignKey(
        "cashier.Invoice", on_delete=models.PROTECT, related_name="receivable_entries"
    )
    payer = models.ForeignKey(
        "payer.PayerOrganization", on_delete=models.PROTECT, null=True, blank=True,
        related_name="receivable_entries"
    )
    account_type = models.CharField(max_length=8, choices=AccountType.choices)
    entry_type = models.CharField(max_length=40, choices=EntryType.choices)
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    idempotency_key = models.CharField(max_length=160, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="receivable_entries_created"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="receivable_entry_amount_positive")
        ]
        indexes = [
            models.Index(fields=["account_type", "entry_type", "created_at"]),
            models.Index(fields=["claim", "account_type", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Buku besar piutang bersifat append-only.")
        if self.account_type == self.AccountType.PAYER and self.payer_id is None:
            raise ValidationError("Entri piutang penjamin wajib memiliki penjamin.")
        if self.account_type == self.AccountType.PATIENT and self.payer_id is not None:
            raise ValidationError("Entri piutang pasien tidak boleh mengarah ke penjamin.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Entri buku besar tidak dapat dihapus; gunakan pembalikan ter-audit.")

    def __str__(self) -> str:
        return f"{self.claim_id}:{self.account_type}:{self.direction}:{self.amount}"
