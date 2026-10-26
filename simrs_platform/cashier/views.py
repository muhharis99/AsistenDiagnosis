from __future__ import annotations

from decimal import Decimal
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cashier.models import FinancialConflict, Invoice, InvoicePayment, TariffItem, create_invoice, issue_invoice, record_payment
from frontoffice.models import Registration
from identity.models import RoleAssignment
from platform_core.audit import record_audit_event
from platform_core.authorization import has_any_scoped_role, has_scoped_role

TARIFF_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.REGISTRAR, RoleAssignment.Role.CASHIER}
CASHIER_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.CASHIER}

class InvoiceLineRequest(serializers.Serializer):
    tariff_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=1000)
class InvoiceCreateRequest(serializers.Serializer):
    registration_id = serializers.UUIDField()
    lines = InvoiceLineRequest(many=True, allow_empty=False, max_length=100)
class PaymentRequest(serializers.Serializer):
    method = serializers.ChoiceField(choices=["CASH", "TRANSFER", "DEBIT", "QRIS"])
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    received_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False)
    idempotency_key = serializers.CharField(max_length=120)
    external_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)

def invoice_data(invoice):
    return {"id": str(invoice.id), "invoice_no": invoice.invoice_no,
        "registration_id": str(invoice.registration_id), "registration_no": invoice.registration.registration_no,
        "unit_id": str(invoice.registration.unit_id), "unit_code": invoice.registration.unit.code,
        "status": invoice.status, "total_amount": str(invoice.total_amount), "paid_amount": str(invoice.paid_amount),
        "outstanding_amount": str(invoice.outstanding_amount), "created_at": invoice.created_at.isoformat(),
        "lines": [{"tariff_code": x.tariff_code_snapshot, "tariff_name": x.tariff_name_snapshot,
            "quantity": x.quantity, "unit_price": str(x.unit_price), "line_total": str(x.line_total)} for x in invoice.lines.all()]}

class TariffCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        if not has_any_scoped_role(request.user, TARIFF_ROLES):
            return Response({"detail": "Akses katalog tarif tidak diizinkan."}, status=403)
        today = timezone.localdate()
        rows = TariffItem.objects.filter(is_active=True, effective_from__lte=today).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=today)).order_by("code")[:1000]
        return Response({"items": [{"id": str(t.id), "code": t.code, "name": t.name, "category": t.category,
            "unit_price": str(t.unit_price), "effective_from": t.effective_from.isoformat(),
            "effective_to": t.effective_to.isoformat() if t.effective_to else None} for t in rows]})

class InvoiceCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        reg_id, number = request.query_params.get("registration_id", "").strip(), request.query_params.get("invoice_no", "").strip()
        if bool(reg_id) == bool(number):
            return Response({"detail": "Isi tepat satu parameter: registration_id atau invoice_no."}, status=400)
        query = Invoice.objects.select_related("registration", "registration__unit").prefetch_related("lines", "payments")
        invoice = query.filter(registration_id=reg_id).first() if reg_id else query.filter(invoice_no=number).first()
        if invoice is None:
            return Response({"detail": "Invoice tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CASHIER_ROLES | {RoleAssignment.Role.AUDITOR}, unit_id=str(invoice.registration.unit_id)):
            record_audit_event(actor=request.user, event_type="access.denied", subject_type="Invoice",
                subject_id=str(invoice.id), metadata={"operation": "read"})
            return Response({"detail": "Akses invoice tidak diizinkan untuk unit ini."}, status=403)
        record_audit_event(actor=request.user, event_type="cashier.invoice.read", subject_type="Invoice",
            subject_id=str(invoice.id), metadata={"invoice_status": invoice.status}, organization_unit=invoice.registration.unit)
        return Response(invoice_data(invoice))
    def post(self, request):
        serializer = InvoiceCreateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        reg_id = str(serializer.validated_data["registration_id"])
        registration = Registration.objects.filter(pk=reg_id).first()
        if registration is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CASHIER_ROLES, unit_id=str(registration.unit_id)):
            return Response({"detail": "Akses pembuatan invoice tidak diizinkan untuk unit ini."}, status=403)
        try:
            invoice = create_invoice(registration_id=reg_id, lines=serializer.validated_data["lines"], actor=request.user)
        except FinancialConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        invoice = Invoice.objects.select_related("registration", "registration__unit").prefetch_related("lines", "payments").get(pk=invoice.pk)
        return Response(invoice_data(invoice), status=201)

class InvoiceIssueView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, invoice_id):
        invoice = Invoice.objects.select_related("registration__unit").filter(pk=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CASHIER_ROLES, unit_id=str(invoice.registration.unit_id)):
            return Response({"detail": "Akses penerbitan invoice tidak diizinkan."}, status=403)
        try:
            row = issue_invoice(invoice_id=str(invoice.id), actor=request.user)
        except FinancialConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        row = Invoice.objects.select_related("registration", "registration__unit").prefetch_related("lines", "payments").get(pk=row.pk)
        return Response(invoice_data(row))

class InvoicePaymentView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, invoice_id):
        invoice = Invoice.objects.select_related("registration__unit").filter(pk=invoice_id).first()
        if invoice is None:
            return Response({"detail": "Invoice tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CASHIER_ROLES, unit_id=str(invoice.registration.unit_id)):
            return Response({"detail": "Akses pembayaran tidak diizinkan."}, status=403)
        serializer = PaymentRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        try:
            payment = record_payment(invoice_id=str(invoice.id), method=data["method"], amount=data["amount"],
                idempotency_key=data["idempotency_key"], actor=request.user,
                received_amount=data.get("received_amount"), external_reference=data.get("external_reference", ""))
        except FinancialConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        invoice.refresh_from_db()
        return Response({"payment_id": str(payment.id), "invoice_id": str(invoice.id), "method": payment.method,
            "amount": str(payment.amount), "received_amount": str(payment.received_amount),
            "change_amount": str(payment.change_amount), "invoice_status": invoice.status,
            "outstanding_amount": str(invoice.outstanding_amount)}, status=201)
