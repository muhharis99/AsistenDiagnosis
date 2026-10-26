import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from cashier.models import (
    FinancialConflict,
    Invoice,
    InvoicePayment,
    TariffItem,
    create_invoice,
    issue_invoice,
    record_payment,
)
from frontoffice.services import create_registration
from identity.models import RoleAssignment
from mpi.models import Patient
from organization.models import OrganizationUnit, UserUnitAssignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier_context():
    user = get_user_model().objects.create_user(
        username="cashier-test", password="synthetic-test-password"
    )
    unit = OrganizationUnit.objects.create(
        code="CASH-TEST", name="Unit Kasir Tes", unit_type=OrganizationUnit.UnitType.CLINIC
    )
    UserUnitAssignment.objects.create(user=user, unit=unit)
    RoleAssignment.objects.create(user=user, unit=unit, role=RoleAssignment.Role.CASHIER)
    patient = Patient.objects.create(
        full_name_ciphertext="encrypted-synthetic-fixture",
        name_fingerprint=uuid.uuid4().hex,
        administrative_sex=Patient.AdministrativeSex.UNKNOWN,
    )
    row = create_registration(
        patient_id=str(patient.id),
        unit_id=str(unit.id),
        visit_date=timezone.localdate(),
        actor=user,
    )
    tariff = TariffItem.objects.create(
        code="SYN-CONSULT",
        name="Konsultasi Demo Sintetis",
        category=TariffItem.Category.CONSULTATION,
        unit_price=Decimal("10000.00"),
        effective_from=date(2020, 1, 1),
        is_active=True,
    )
    return {"user": user, "registration": row, "tariff": tariff}


def test_invoice_snapshot_payments_and_idempotency(cashier_context):
    d = cashier_context
    invoice = create_invoice(
        registration_id=str(d["registration"].id),
        lines=[{"tariff_id": str(d["tariff"].id), "quantity": 1}],
        actor=d["user"],
    )
    line = invoice.lines.get()
    d["tariff"].name = "Tarif berubah"
    d["tariff"].unit_price = Decimal("12000.00")
    d["tariff"].save()
    line.refresh_from_db()
    assert line.tariff_name_snapshot == "Konsultasi Demo Sintetis"
    assert line.unit_price == Decimal("10000.00")
    issue_invoice(invoice_id=str(invoice.id), actor=d["user"])
    args = {
        "invoice_id": str(invoice.id),
        "method": InvoicePayment.Method.CASH,
        "amount": Decimal("6000.00"),
        "received_amount": Decimal("10000.00"),
        "idempotency_key": "synthetic-payment-cash-1",
        "actor": d["user"],
    }
    payment = record_payment(**args)
    assert payment.change_amount == Decimal("4000.00")
    assert record_payment(**args).id == payment.id
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PARTIAL
    with pytest.raises(ValueError):
        record_payment(
            invoice_id=str(invoice.id),
            method=InvoicePayment.Method.QRIS,
            amount=Decimal("5000.00"),
            idempotency_key="synthetic-overpayment",
            external_reference="SYN-OVERPAY",
            actor=d["user"],
        )
    record_payment(
        invoice_id=str(invoice.id),
        method=InvoicePayment.Method.QRIS,
        amount=Decimal("4000.00"),
        idempotency_key="synthetic-payment-qris-2",
        external_reference="SYNTHETIC-QRIS-REF",
        actor=d["user"],
    )
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    assert invoice.outstanding_amount == Decimal("0.00")


def test_duplicate_invoice_and_missing_reference_rejected(cashier_context):
    d = cashier_context
    invoice = create_invoice(
        registration_id=str(d["registration"].id),
        lines=[{"tariff_id": str(d["tariff"].id), "quantity": 1}],
        actor=d["user"],
    )
    with pytest.raises(FinancialConflict):
        create_invoice(
            registration_id=str(d["registration"].id),
            lines=[{"tariff_id": str(d["tariff"].id), "quantity": 1}],
            actor=d["user"],
        )
    issue_invoice(invoice_id=str(invoice.id), actor=d["user"])
    with pytest.raises(ValueError):
        record_payment(
            invoice_id=str(invoice.id),
            method=InvoicePayment.Method.TRANSFER,
            amount=Decimal("1000.00"),
            idempotency_key="synthetic-transfer-no-ref",
            actor=d["user"],
        )


def test_issued_invoice_lines_are_immutable(cashier_context):
    d = cashier_context
    invoice = create_invoice(
        registration_id=str(d["registration"].id),
        lines=[{"tariff_id": str(d["tariff"].id), "quantity": 1}],
        actor=d["user"],
    )
    issue_invoice(invoice_id=str(invoice.id), actor=d["user"])
    line = invoice.lines.get()
    line.tariff_name_snapshot = "Changed"
    with pytest.raises(ValidationError):
        line.save()
    with pytest.raises(ValidationError):
        line.delete()
