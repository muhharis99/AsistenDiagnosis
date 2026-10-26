import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cashier.models import Invoice, TariffItem, create_invoice, issue_invoice
from claims.models import Claim, ClaimCollection
from claims.services import ClaimConflict, adjudicate_claim, collect_claim_balance, create_claim, submit_claim
from frontoffice.services import create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from payer.models import Coverage, PayerOrganization, PayerPlan, RegistrationCoverage
from platform_core.authorization import has_scoped_role
from receivables.models import ReceivableLedgerEntry
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def claims_context():
    user = get_user_model().objects.create_user(
        username="claims-officer", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="CLAIM-TEST", name="Unit Klaim Tes", unit_type=OrganizationUnit.UnitType.CLINIC
    )
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.INSURANCE_BILLING)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.PAYER_REVIEWER)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.CASHIER)
    patient = Patient.objects.create(
        full_name_ciphertext="encrypted-synthetic-fixture",
        name_fingerprint=uuid.uuid4().hex,
        administrative_sex=Patient.AdministrativeSex.UNKNOWN,
    )
    registration = create_registration(
        patient_id=str(patient.id), unit_id=str(unit.id), visit_date=timezone.localdate(), actor=user
    )
    invoice_line_price = Decimal("10000.00")
    tariff = TariffItem.objects.create(
        code="CLAIM-SYN-TAR", name="Tarif klaim sintetis",
        category=TariffItem.Category.CONSULTATION, unit_price=invoice_line_price,
        effective_from=date(2020, 1, 1), is_active=True,
    )
    invoice = create_invoice(
        registration_id=str(registration.id),
        lines=[{"tariff_id": str(tariff.id), "quantity": 2}],
        actor=user,
    )
    invoice = issue_invoice(invoice_id=str(invoice.id), actor=user)
    payer1 = PayerOrganization.objects.create(code="SYN-P1", name="Penjamin Sintetis 1", payer_type=PayerOrganization.PayerType.PRIVATE)
    plan1 = PayerPlan.objects.create(
        payer=payer1, code="SYN-PLAN-1", name="Paket Sintetis 1",
        effective_from=date(2020, 1, 1),
    )
    coverage1 = Coverage.objects.create(
        patient=patient, plan=plan1, member_reference="SYN-MEMBER-1",
        effective_from=date(2020, 1, 1), verified_by=user, verified_at=timezone.now(),
    )
    assignment1 = RegistrationCoverage.objects.create(
        registration=registration, coverage=coverage1, priority=1, verified_by=user
    )
    payer2 = PayerOrganization.objects.create(code="SYN-P2", name="Penjamin Sintetis 2", payer_type=PayerOrganization.PayerType.OTHER)
    plan2 = PayerPlan.objects.create(
        payer=payer2, code="SYN-PLAN-2", name="Paket Sintetis 2",
        effective_from=date(2020, 1, 1),
    )
    coverage2 = Coverage.objects.create(
        patient=patient, plan=plan2, member_reference="SYN-MEMBER-2",
        effective_from=date(2020, 1, 1), verified_by=user, verified_at=timezone.now(),
    )
    assignment2 = RegistrationCoverage.objects.create(
        registration=registration, coverage=coverage2, priority=2, verified_by=user
    )
    return {
        "user": user, "unit": unit, "patient": patient, "registration": registration,
        "invoice": invoice, "assignment1": assignment1, "assignment2": assignment2,
    }


def test_primary_claim_adjudication_and_collections(claims_context):
    d = claims_context
    claim = create_claim(
        registration_id=str(d["registration"].id),
        coverage_assignment_id=d["assignment1"].id,
        actor=d["user"],
    )
    assert claim.claimed_amount == Decimal("20000.00")
    submit_claim(claim_id=str(claim.id), actor=d["user"])
    adjudication = adjudicate_claim(
        claim_id=str(claim.id),
        allowed_amount=Decimal("15000.00"),
        denied_amount=Decimal("2000.00"),
        patient_responsibility=Decimal("3000.00"),
        external_reference="SYN-ADJ-1",
        reason="Keputusan sintetis",
        actor=d["user"],
    )
    claim.refresh_from_db()
    assert adjudication.version == 1
    assert claim.payer_balance == Decimal("15000.00")
    assert claim.patient_balance == Decimal("3000.00")
    payment = collect_claim_balance(
        claim_id=str(claim.id),
        collection_type=ClaimCollection.CollectionType.PAYER_REMITTANCE,
        amount=Decimal("10000.00"),
        external_reference="SYN-REM-1",
        idempotency_key="syn-remit-1",
        actor=d["user"],
    )
    assert payment.amount == Decimal("10000.00")
    assert collect_claim_balance(
        claim_id=str(claim.id),
        collection_type=ClaimCollection.CollectionType.PAYER_REMITTANCE,
        amount=Decimal("10000.00"),
        external_reference="SYN-REM-1",
        idempotency_key="syn-remit-1",
        actor=d["user"],
    ).id == payment.id
    claim.refresh_from_db()
    assert claim.status == Claim.Status.PARTIALLY_PAID
    with pytest.raises(ValueError):
        collect_claim_balance(
            claim_id=str(claim.id),
            collection_type=ClaimCollection.CollectionType.PAYER_REMITTANCE,
            amount=Decimal("6000.00"),
            external_reference="SYN-REM-2",
            idempotency_key="syn-remit-2",
            actor=d["user"],
        )
    collect_claim_balance(
        claim_id=str(claim.id),
        collection_type=ClaimCollection.CollectionType.PAYER_REMITTANCE,
        amount=Decimal("5000.00"),
        external_reference="SYN-REM-3",
        idempotency_key="syn-remit-3",
        actor=d["user"],
    )
    claim.refresh_from_db()
    assert claim.status == Claim.Status.PAID
    collect_claim_balance(
        claim_id=str(claim.id),
        collection_type=ClaimCollection.CollectionType.PATIENT_PAYMENT,
        amount=Decimal("3000.00"),
        external_reference="SYN-PATIENT-RECEIPT",
        idempotency_key="syn-patient-1",
        actor=d["user"],
    )
    claim.refresh_from_db()
    assert claim.patient_balance == Decimal("0.00")


def test_cob_secondary_claim_transfers_outstanding_patient_share(claims_context):
    d = claims_context
    primary = create_claim(
        registration_id=str(d["registration"].id),
        coverage_assignment_id=d["assignment1"].id,
        actor=d["user"],
    )
    submit_claim(claim_id=str(primary.id), actor=d["user"])
    adjudicate_claim(
        claim_id=str(primary.id),
        allowed_amount=Decimal("10000.00"),
        denied_amount=Decimal("4000.00"),
        patient_responsibility=Decimal("6000.00"),
        external_reference="SYN-ADJ-COB",
        reason="COB primary synthetic",
        actor=d["user"],
    )
    secondary = create_claim(
        registration_id=str(d["registration"].id),
        coverage_assignment_id=d["assignment2"].id,
        actor=d["user"],
    )
    assert secondary.claimed_amount == Decimal("6000.00")
    submit_claim(claim_id=str(secondary.id), actor=d["user"])
    primary.refresh_from_db()
    secondary.refresh_from_db()
    assert primary.patient_balance == Decimal("0.00")
    assert secondary.payer_balance == Decimal("6000.00")
    adjudicate_claim(
        claim_id=str(secondary.id),
        allowed_amount=Decimal("5000.00"),
        denied_amount=Decimal("1000.00"),
        patient_responsibility=Decimal("0.00"),
        external_reference="SYN-ADJ-COB-2",
        reason="COB secondary synthetic",
        actor=d["user"],
    )
    secondary.refresh_from_db()
    assert secondary.payer_balance == Decimal("5000.00")
    assert secondary.patient_balance == Decimal("0.00")


def test_claim_amounts_must_balance_and_double_submit_is_rejected(claims_context):
    d = claims_context
    claim = create_claim(
        registration_id=str(d["registration"].id),
        coverage_assignment_id=d["assignment1"].id,
        actor=d["user"],
    )
    submit_claim(claim_id=str(claim.id), actor=d["user"])
    with pytest.raises(ValueError):
        adjudicate_claim(
            claim_id=str(claim.id),
            allowed_amount=Decimal("5000.00"),
            denied_amount=Decimal("1000.00"),
            patient_responsibility=Decimal("100.00"),
            external_reference="SYN-BAD-ADJ",
            reason="Angka tidak seimbang",
            actor=d["user"],
        )
    adjudicate_claim(
        claim_id=str(claim.id),
        allowed_amount=Decimal("20000.00"),
        denied_amount=Decimal("0.00"),
        patient_responsibility=Decimal("0.00"),
        external_reference="SYN-OK-ADJ",
        reason="Disetujui sintetis",
        actor=d["user"],
    )
    with pytest.raises(ClaimConflict):
        submit_claim(claim_id=str(claim.id), actor=d["user"])


def test_ledger_entries_are_immutable(claims_context):
    d = claims_context
    claim = create_claim(
        registration_id=str(d["registration"].id),
        coverage_assignment_id=d["assignment1"].id,
        actor=d["user"],
    )
    submit_claim(claim_id=str(claim.id), actor=d["user"])
    entry = ReceivableLedgerEntry.objects.get(claim=claim)
    entry.amount = Decimal("1.00")
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        entry.delete()
