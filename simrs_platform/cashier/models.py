from __future__ import annotations
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from frontoffice.models import Registration
from platform_core.audit import record_audit_event

class TariffItem(models.Model):
    class Category(models.TextChoices):
        REGISTRATION = "REGISTRATION", "Pendaftaran"
        CONSULTATION = "CONSULTATION", "Konsultasi"
        PROCEDURE = "PROCEDURE", "Tindakan"
        SUPPORT = "SUPPORT", "Penunjang"
        OTHER = "OTHER", "Lainnya"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="tariff_price_positive"),
            models.CheckConstraint(condition=Q(effective_to__isnull=True) | Q(effective_to__gte=models.F("effective_from")), name="tariff_effective_dates_valid"),
        ]
    def __str__(self):
        return "{} - {}".format(self.code, self.name)

class InvoiceSequence(models.Model):
    invoice_date = models.DateField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draf"
        ISSUED = "ISSUED", "Terbit"
        PARTIAL = "PARTIAL", "Dibayar sebagian"
        PAID = "PAID", "Lunas"
        VOID = "VOID", "Dibatalkan"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_no = models.CharField(max_length=40, unique=True)
    registration = models.OneToOneField(Registration, on_delete=models.PROTECT, related_name="invoice")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices_created")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices_issued")
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]
    @property
    def paid_amount(self):
        amount = self.payments.aggregate(value=Sum("amount"))["value"]
        return amount if amount is not None else Decimal("0.00")
    @property
    def outstanding_amount(self):
        return self.total_amount - self.paid_amount

class InvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    tariff = models.ForeignKey(TariffItem, on_delete=models.PROTECT, related_name="invoice_lines")
    tariff_code_snapshot = models.CharField(max_length=40)
    tariff_name_snapshot = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoice_line_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gt=0), name="invoice_line_unit_price_positive"),
        ]
    def save(self, *args, **kwargs):
        if self.invoice_id and Invoice.objects.filter(pk=self.invoice_id).exclude(status=Invoice.Status.DRAFT).exists():
            raise ValidationError("Baris invoice yang sudah diterbitkan tidak boleh diubah.")
        if self.pk and InvoiceLine.objects.filter(pk=self.pk).exists():
            raise ValidationError("Baris invoice bersifat append-only; buat invoice koreksi sesuai prosedur.")
        super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError("Baris invoice tidak dapat dihapus; gunakan prosedur koreksi finansial.")

class InvoicePayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Tunai"
        TRANSFER = "TRANSFER", "Transfer"
        DEBIT = "DEBIT", "Kartu debit"
        QRIS = "QRIS", "QRIS"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    change_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    idempotency_key = models.CharField(max_length=120, unique=True)
    external_reference = models.CharField(max_length=120, blank=True)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_recorded")
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(condition=Q(received_amount__gte=0), name="payment_received_nonnegative"),
            models.CheckConstraint(condition=Q(change_amount__gte=0), name="payment_change_nonnegative"),
        ]
    def save(self, *args, **kwargs):
        if self.pk and InvoicePayment.objects.filter(pk=self.pk).exists():
            raise ValidationError("Transaksi pembayaran bersifat append-only.")
        super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValidationError("Pembayaran tidak dapat dihapus; gunakan pembalikan yang ter-audit.")

class FinancialConflict(Exception):
    pass

@transaction.atomic
def create_invoice(*, registration_id, lines, actor):
    if not lines or len(lines) > 100:
        raise ValueError("Invoice harus memiliki 1–100 baris tarif.")
    registration = Registration.objects.select_for_update().select_related("unit").filter(pk=registration_id).first()
    if registration is None:
        raise ValueError("Registrasi tidak ditemukan.")
    if registration.status == Registration.Status.CANCELLED:
        raise ValueError("Registrasi yang dibatalkan tidak dapat ditagihkan.")
    if Invoice.objects.filter(registration=registration).exists():
        raise FinancialConflict("Registrasi sudah memiliki invoice.")
    quantities = {}
    for line in lines:
        tariff_id = str(line.get("tariff_id", ""))
        quantity = int(line.get("quantity", 0))
        if not tariff_id or quantity < 1 or quantity > 1000:
            raise ValueError("ID tarif dan kuantitas 1–1000 wajib valid.")
        quantities[tariff_id] = quantities.get(tariff_id, 0) + quantity
        if quantities[tariff_id] > 1000:
            raise ValueError("Total kuantitas per tarif maksimal 1000.")
    tariffs = TariffItem.objects.filter(id__in=quantities.keys(), is_active=True, effective_from__lte=registration.visit_date).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=registration.visit_date))
    applicable = {str(t.id): t for t in tariffs}
    if set(quantities) != set(applicable):
        raise ValueError("Ada tarif tidak aktif atau tidak berlaku pada tanggal kunjungan.")
    day = timezone.localdate()
    sequence, _ = InvoiceSequence.objects.get_or_create(invoice_date=day, defaults={"last_value": 0})
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_value += 1
    sequence.save(update_fields=["last_value"])
    invoice = Invoice.objects.create(invoice_no="INV-PSRS-{}-{:06d}".format(day.strftime("%Y%m%d"), sequence.last_value),
        registration=registration, created_by=actor)
    total = Decimal("0.00")
    for tariff_id, quantity in quantities.items():
        tariff = applicable[tariff_id]
        amount = tariff.unit_price * quantity
        InvoiceLine.objects.create(invoice=invoice, tariff=tariff, tariff_code_snapshot=tariff.code,
            tariff_name_snapshot=tariff.name, quantity=quantity, unit_price=tariff.unit_price, line_total=amount)
        total += amount
    invoice.total_amount = total
    invoice.save(update_fields=["total_amount"])
    record_audit_event(actor=actor, event_type="cashier.invoice.created", subject_type="Invoice",
        subject_id=str(invoice.id), metadata={"invoice_no": invoice.invoice_no, "line_count": len(quantities), "amount": str(total)},
        organization_unit=registration.unit)
    return invoice

@transaction.atomic
def issue_invoice(*, invoice_id, actor):
    invoice = Invoice.objects.select_for_update().select_related("registration__unit").filter(pk=invoice_id).first()
    if invoice is None:
        raise ValueError("Invoice tidak ditemukan.")
    if invoice.status != Invoice.Status.DRAFT:
        raise FinancialConflict("Hanya invoice DRAFT yang dapat diterbitkan.")
    lines = list(invoice.lines.all())
    if not lines:
        raise ValueError("Invoice kosong tidak dapat diterbitkan.")
    invoice.total_amount = sum((line.line_total for line in lines), Decimal("0.00"))
    invoice.status = Invoice.Status.ISSUED
    invoice.issued_by = actor
    invoice.issued_at = timezone.now()
    invoice.save(update_fields=["total_amount", "status", "issued_by", "issued_at"])
    record_audit_event(actor=actor, event_type="cashier.invoice.issued", subject_type="Invoice",
        subject_id=str(invoice.id), metadata={"invoice_no": invoice.invoice_no, "amount": str(invoice.total_amount)},
        organization_unit=invoice.registration.unit)
    return invoice

@transaction.atomic
def record_payment(*, invoice_id, method, amount, idempotency_key, actor, received_amount=None, external_reference=""):
    if not idempotency_key.strip():
        raise ValueError("idempotency_key wajib diisi.")
    if amount <= Decimal("0.00"):
        raise ValueError("Nominal pembayaran harus lebih besar dari nol.")
    existing = InvoicePayment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if str(existing.invoice_id) == str(invoice_id) and existing.method == method and existing.amount == amount and existing.cashier_id == actor.pk:
            return existing
        raise FinancialConflict("idempotency_key telah digunakan untuk transaksi berbeda.")
    invoice = Invoice.objects.select_for_update().select_related("registration__unit").filter(pk=invoice_id).first()
    if invoice is None:
        raise ValueError("Invoice tidak ditemukan.")
    if invoice.status not in {Invoice.Status.ISSUED, Invoice.Status.PARTIAL}:
        raise FinancialConflict("Invoice harus sudah terbit dan belum lunas.")
    paid = invoice.payments.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    if amount > invoice.total_amount - paid:
        raise ValueError("Nominal pembayaran melebihi sisa tagihan.")
    if method == InvoicePayment.Method.CASH:
        received = received_amount if received_amount is not None else amount
        if received < amount:
            raise ValueError("Uang diterima tidak boleh kurang dari nominal pembayaran.")
        change = received - amount
    else:
        if method not in {InvoicePayment.Method.TRANSFER, InvoicePayment.Method.DEBIT, InvoicePayment.Method.QRIS}:
            raise ValueError("Metode pembayaran tidak dikenal.")
        if not external_reference.strip():
            raise ValueError("Referensi eksternal wajib untuk pembayaran non-tunai.")
        received, change = amount, Decimal("0.00")
    payment = InvoicePayment.objects.create(invoice=invoice, method=method, amount=amount,
        received_amount=received, change_amount=change, idempotency_key=idempotency_key.strip(),
        external_reference=external_reference.strip(), cashier=actor)
    invoice.status = Invoice.Status.PAID if paid + amount >= invoice.total_amount else Invoice.Status.PARTIAL
    invoice.save(update_fields=["status"])
    record_audit_event(actor=actor, event_type="cashier.payment.recorded", subject_type="Invoice",
        subject_id=str(invoice.id), metadata={"payment_id": str(payment.id), "method": method,
        "amount": str(amount), "invoice_status": invoice.status}, organization_unit=invoice.registration.unit)
    return payment
