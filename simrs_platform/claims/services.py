from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from cashier.models import Invoice
from claims.models import Claim, ClaimAdjudication, ClaimCollection, ClaimLine
from frontoffice.models import Registration
from payer.models import RegistrationCoverage
from platform_core.audit import record_audit_event
from receivables.models import ReceivableLedgerEntry


class ClaimConflict(Exception):
    pass


def _ledger(*, claim, account_type, entry_type, direction, amount, actor, key, payer=None):
    if amount <= Decimal("0.00"):
        return None
    return ReceivableLedgerEntry.objects.create(
        claim=claim,
        invoice=claim.invoice,
        payer=payer,
        account_type=account_type,
        entry_type=entry_type,
        direction=direction,
        amount=amount,
        idempotency_key=key,
        created_by=actor,
    )


@transaction.atomic
def create_claim(*, registration_id, coverage_assignment_id, actor):
    registration = (
        Registration.objects.select_for_update()
        .select_related("unit", "patient")
        .filter(pk=registration_id)
        .first()
    )
    if registration is None:
        raise ValueError("Registrasi tidak ditemukan.")
    assignment = (
        RegistrationCoverage.objects.select_for_update()
        .select_related("registration", "coverage__plan__payer", "coverage__patient")
        .filter(pk=coverage_assignment_id, registration=registration)
        .first()
    )
    if assignment is None:
        raise ValueError("Penjamin tidak terhubung dengan registrasi ini.")
    invoice = Invoice.objects.select_for_update().filter(registration=registration).first()
    if invoice is None or invoice.status != Invoice.Status.ISSUED:
        raise ValueError("Klaim demo hanya dapat dibuat dari invoice yang sudah terbit dan belum dibayar.")
    if not assignment.coverage.active_on(registration.visit_date):
        raise ValueError("Kepesertaan tidak aktif pada tanggal kunjungan.")
    if Claim.objects.filter(registration=registration, coverage_assignment=assignment).exists():
        raise ClaimConflict("Klaim untuk penjamin pada registrasi ini sudah ada.")
    if assignment.priority == 1:
        amount = invoice.total_amount
        line_source = list(invoice.lines.all())
        if not line_source:
            raise ValueError("Invoice tanpa baris tidak dapat diklaim.")
    else:
        previous_assignment = RegistrationCoverage.objects.filter(
            registration=registration, priority=assignment.priority - 1
        ).first()
        previous_claim = (
            Claim.objects.select_for_update()
            .filter(registration=registration, coverage_assignment=previous_assignment)
            .first()
            if previous_assignment
            else None
        )
        if previous_claim is None or previous_claim.status not in {
            Claim.Status.ADJUDICATED,
            Claim.Status.REJECTED,
            Claim.Status.PARTIALLY_PAID,
            Claim.Status.PAID,
        }:
            raise ClaimConflict("Klaim penjamin sebelumnya harus sudah diadjudikasi.")
        amount = previous_claim.patient_balance
        if amount <= Decimal("0.00"):
            raise ValueError("Tidak ada sisa tanggung jawab pasien untuk klaim COB berikutnya.")
        line_source = []
    if amount <= Decimal("0.00"):
        raise ValueError("Nominal klaim harus lebih besar dari nol.")
    claim_no = f"CLM-{timezone.localdate():%Y%m%d}-{Claim._meta.pk.default().hex[:10].upper()}"
    claim = Claim.objects.create(
        claim_no=claim_no,
        registration=registration,
        invoice=invoice,
        coverage_assignment=assignment,
        claimed_amount=amount,
        created_by=actor,
    )
    if assignment.priority == 1:
        for item in line_source:
            ClaimLine.objects.create(
                claim=claim,
                invoice_line=item,
                code_snapshot=item.tariff_code_snapshot,
                display_snapshot=item.tariff_name_snapshot,
                quantity=item.quantity,
                claimed_amount=item.line_total,
            )
    else:
        ClaimLine.objects.create(
            claim=claim,
            code_snapshot="COB-PATIENT-RESPONSIBILITY",
            display_snapshot="Sisa tanggung jawab pasien dari penjamin sebelumnya",
            quantity=1,
            claimed_amount=amount,
        )
    record_audit_event(
        actor=actor,
        event_type="claims.claim.created",
        subject_type="Claim",
        subject_id=str(claim.id),
        metadata={
            "claim_no": claim.claim_no,
            "registration_no": registration.registration_no,
            "payer_code": assignment.coverage.plan.payer.code,
            "priority": assignment.priority,
            "amount": str(amount),
        },
        organization_unit=registration.unit,
    )
    return claim


@transaction.atomic
def submit_claim(*, claim_id, actor):
    claim = (
        Claim.objects.select_for_update()
        .select_related("registration__unit", "coverage_assignment__coverage__plan__payer")
        .filter(pk=claim_id)
        .first()
    )
    if claim is None:
        raise ValueError("Klaim tidak ditemukan.")
    if claim.status != Claim.Status.DRAFT:
        raise ClaimConflict("Hanya klaim DRAFT yang dapat diajukan.")
    if not claim.lines.exists() or sum((x.claimed_amount for x in claim.lines.all()), Decimal("0.00")) != claim.claimed_amount:
        raise ValueError("Jumlah baris klaim tidak sama dengan total klaim.")
    payer = claim.coverage_assignment.coverage.plan.payer
    if claim.coverage_assignment.priority > 1:
        previous_assignment = RegistrationCoverage.objects.filter(
            registration=claim.registration, priority=claim.coverage_assignment.priority - 1
        ).first()
        previous_claim = Claim.objects.select_for_update().filter(
            registration=claim.registration, coverage_assignment=previous_assignment
        ).first()
        if previous_claim is None or previous_claim.patient_balance != claim.claimed_amount:
            raise ClaimConflict("Saldo tanggung jawab pasien berubah; perbarui klaim COB.")
        _ledger(
            claim=previous_claim,
            account_type=ReceivableLedgerEntry.AccountType.PATIENT,
            entry_type=ReceivableLedgerEntry.EntryType.COB_TRANSFER_TO_SECONDARY,
            direction=ReceivableLedgerEntry.Direction.CREDIT,
            amount=claim.claimed_amount,
            actor=actor,
            key=f"claim:{claim.id}:cob-transfer",
        )
    _ledger(
        claim=claim,
        account_type=ReceivableLedgerEntry.AccountType.PAYER,
        entry_type=ReceivableLedgerEntry.EntryType.CLAIM_SUBMITTED,
        direction=ReceivableLedgerEntry.Direction.DEBIT,
        amount=claim.claimed_amount,
        actor=actor,
        key=f"claim:{claim.id}:submitted",
        payer=payer,
    )
    claim.status = Claim.Status.SUBMITTED
    claim.submitted_at = timezone.now()
    claim.save(update_fields=["status", "submitted_at"])
    record_audit_event(
        actor=actor,
        event_type="claims.claim.submitted",
        subject_type="Claim",
        subject_id=str(claim.id),
        metadata={"claim_no": claim.claim_no, "amount": str(claim.claimed_amount), "payer_code": payer.code},
        organization_unit=claim.registration.unit,
    )
    return claim


@transaction.atomic
def adjudicate_claim(
    *, claim_id, allowed_amount, denied_amount, patient_responsibility, external_reference, reason, actor
):
    claim = (
        Claim.objects.select_for_update()
        .select_related("registration__unit", "coverage_assignment__coverage__plan__payer")
        .filter(pk=claim_id)
        .first()
    )
    if claim is None:
        raise ValueError("Klaim tidak ditemukan.")
    if claim.status != Claim.Status.SUBMITTED:
        raise ClaimConflict("Hanya klaim SUBMITTED yang dapat diadjudikasi.")
    allowed_amount = Decimal(allowed_amount)
    denied_amount = Decimal(denied_amount)
    patient_responsibility = Decimal(patient_responsibility)
    if min(allowed_amount, denied_amount, patient_responsibility) < Decimal("0.00"):
        raise ValueError("Nominal adjudikasi tidak boleh negatif.")
    if allowed_amount + denied_amount + patient_responsibility != claim.claimed_amount:
        raise ValueError("Allowed + denied + tanggung jawab pasien harus sama dengan nominal klaim.")
    if not external_reference.strip():
        raise ValueError("Referensi adjudikasi wajib diisi.")
    row = ClaimAdjudication.objects.create(
        claim=claim,
        version=1,
        allowed_amount=allowed_amount,
        denied_amount=denied_amount,
        patient_responsibility=patient_responsibility,
        external_reference=external_reference.strip(),
        reason=reason.strip(),
        recorded_by=actor,
        recorded_at=timezone.now(),
    )
    payer = claim.coverage_assignment.coverage.plan.payer
    _ledger(
        claim=claim,
        account_type=ReceivableLedgerEntry.AccountType.PAYER,
        entry_type=ReceivableLedgerEntry.EntryType.DENIAL_ADJUSTMENT,
        direction=ReceivableLedgerEntry.Direction.CREDIT,
        amount=denied_amount,
        actor=actor,
        key=f"claim:{claim.id}:adjudication:denied",
        payer=payer,
    )
    _ledger(
        claim=claim,
        account_type=ReceivableLedgerEntry.AccountType.PAYER,
        entry_type=ReceivableLedgerEntry.EntryType.PATIENT_RESPONSIBILITY_TRANSFER,
        direction=ReceivableLedgerEntry.Direction.CREDIT,
        amount=patient_responsibility,
        actor=actor,
        key=f"claim:{claim.id}:adjudication:payer-transfer",
        payer=payer,
    )
    _ledger(
        claim=claim,
        account_type=ReceivableLedgerEntry.AccountType.PATIENT,
        entry_type=ReceivableLedgerEntry.EntryType.PATIENT_RESPONSIBILITY_TRANSFER,
        direction=ReceivableLedgerEntry.Direction.DEBIT,
        amount=patient_responsibility,
        actor=actor,
        key=f"claim:{claim.id}:adjudication:patient-transfer",
    )
    claim.status = (
        Claim.Status.REJECTED
        if allowed_amount == Decimal("0.00") and patient_responsibility == Decimal("0.00")
        else Claim.Status.ADJUDICATED
    )
    claim.save(update_fields=["status"])
    record_audit_event(
        actor=actor,
        event_type="claims.claim.adjudicated",
        subject_type="Claim",
        subject_id=str(claim.id),
        metadata={
            "claim_no": claim.claim_no,
            "version": row.version,
            "allowed_amount": str(allowed_amount),
            "denied_amount": str(denied_amount),
            "patient_responsibility": str(patient_responsibility),
            "payer_code": payer.code,
        },
        organization_unit=claim.registration.unit,
    )
    return row


@transaction.atomic
def collect_claim_balance(*, claim_id, collection_type, amount, external_reference, idempotency_key, actor):
    claim = (
        Claim.objects.select_for_update()
        .select_related("registration__unit", "coverage_assignment__coverage__plan__payer")
        .filter(pk=claim_id)
        .first()
    )
    if claim is None:
        raise ValueError("Klaim tidak ditemukan.")
    amount = Decimal(amount)
    if amount <= Decimal("0.00"):
        raise ValueError("Nominal penerimaan harus lebih besar dari nol.")
    external_reference, idempotency_key = external_reference.strip(), idempotency_key.strip()
    if not external_reference or not idempotency_key:
        raise ValueError("Referensi penerimaan dan idempotency_key wajib diisi.")
    existing = ClaimCollection.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.claim_id == claim.id
            and existing.collection_type == collection_type
            and existing.amount == amount
            and existing.external_reference == external_reference
            and existing.recorded_by_id == actor.pk
        ):
            return existing
        raise ClaimConflict("idempotency_key sudah dipakai untuk penerimaan berbeda.")
    adjudication = claim.adjudication
    if adjudication is None or claim.status in {Claim.Status.DRAFT, Claim.Status.SUBMITTED}:
        raise ClaimConflict("Klaim harus sudah diadjudikasi sebelum penerimaan dicatat.")
    if collection_type == ClaimCollection.CollectionType.PAYER_REMITTANCE:
        if claim.status == Claim.Status.REJECTED:
            raise ClaimConflict("Klaim ditolak tidak memiliki saldo penjamin.")
        balance = claim.payer_balance
        account_type = ReceivableLedgerEntry.AccountType.PAYER
        entry_type = ReceivableLedgerEntry.EntryType.PAYER_REMITTANCE
        payer = claim.coverage_assignment.coverage.plan.payer
    else:
        balance = claim.patient_balance
        account_type = ReceivableLedgerEntry.AccountType.PATIENT
        entry_type = ReceivableLedgerEntry.EntryType.PATIENT_PAYMENT
        payer = None
    if balance <= Decimal("0.00"):
        raise ClaimConflict("Tidak ada saldo piutang untuk jenis penerimaan ini.")
    if amount > balance:
        raise ValueError("Nominal penerimaan melebihi saldo piutang.")
    row = ClaimCollection.objects.create(
        claim=claim,
        collection_type=collection_type,
        amount=amount,
        external_reference=external_reference,
        idempotency_key=idempotency_key,
        recorded_by=actor,
    )
    _ledger(
        claim=claim,
        account_type=account_type,
        entry_type=entry_type,
        direction=ReceivableLedgerEntry.Direction.CREDIT,
        amount=amount,
        actor=actor,
        key=f"collection:{row.id}",
        payer=payer,
    )
    if collection_type == ClaimCollection.CollectionType.PAYER_REMITTANCE:
        claim.refresh_from_db()
        claim.status = Claim.Status.PAID if claim.payer_balance == Decimal("0.00") else Claim.Status.PARTIALLY_PAID
        claim.save(update_fields=["status"])
    record_audit_event(
        actor=actor,
        event_type="claims.collection.recorded",
        subject_type="Claim",
        subject_id=str(claim.id),
        metadata={
            "claim_no": claim.claim_no,
            "collection_type": collection_type,
            "collection_id": str(row.id),
            "amount": str(amount),
            "payer_code": claim.coverage_assignment.coverage.plan.payer.code,
        },
        organization_unit=claim.registration.unit,
    )
    return row
