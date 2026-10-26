from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from claims.models import Claim, ClaimAdjudication, ClaimCollection
from claims.services import ClaimConflict, adjudicate_claim, collect_claim_balance, create_claim, submit_claim
from frontoffice.models import Registration
from identity.models import RoleAssignment
from payer.models import RegistrationCoverage
from platform_core.audit import record_audit_event
from platform_core.authorization import has_scoped_role
from receivables.models import ReceivableLedgerEntry


CLAIM_READ_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.INSURANCE_BILLING,
    RoleAssignment.Role.PAYER_REVIEWER,
    RoleAssignment.Role.CASHIER,
    RoleAssignment.Role.AUDITOR,
}
CLAIM_CREATE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.INSURANCE_BILLING}
ADJUDICATE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.PAYER_REVIEWER}
REMITTANCE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.INSURANCE_BILLING}
PATIENT_PAYMENT_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.CASHIER}


class ClaimCreateRequest(serializers.Serializer):
    registration_id = serializers.UUIDField()
    coverage_assignment_id = serializers.IntegerField()


class AdjudicationRequest(serializers.Serializer):
    allowed_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    denied_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    patient_responsibility = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))
    external_reference = serializers.CharField(max_length=120)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CollectionRequest(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    external_reference = serializers.CharField(max_length=120)
    idempotency_key = serializers.CharField(max_length=120)


def claim_data(claim):
    adjudication = claim.adjudication
    lines = claim.lines.all()
    return {
        "id": str(claim.id),
        "claim_no": claim.claim_no,
        "registration_id": str(claim.registration_id),
        "registration_no": claim.registration.registration_no,
        "invoice_id": str(claim.invoice_id),
        "payer_code": claim.coverage_assignment.coverage.plan.payer.code,
        "plan_code": claim.coverage_assignment.coverage.plan.code,
        "coverage_priority": claim.coverage_assignment.priority,
        "status": claim.status,
        "claimed_amount": str(claim.claimed_amount),
        "allowed_amount": str(adjudication.allowed_amount) if adjudication else "0.00",
        "denied_amount": str(adjudication.denied_amount) if adjudication else "0.00",
        "patient_responsibility": str(adjudication.patient_responsibility) if adjudication else "0.00",
        "payer_balance": str(claim.payer_balance),
        "patient_balance": str(claim.patient_balance),
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "created_at": claim.created_at.isoformat(),
        "lines": [
            {
                "code": line.code_snapshot,
                "display": line.display_snapshot,
                "quantity": line.quantity,
                "claimed_amount": str(line.claimed_amount),
            }
            for line in lines
        ],
    }


class ClaimCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        registration_id = request.query_params.get("registration_id", "").strip()
        claim_no = request.query_params.get("claim_no", "").strip()
        if bool(registration_id) == bool(claim_no):
            return Response({"detail": "Isi tepat satu parameter: registration_id atau claim_no."}, status=400)
        query = Claim.objects.select_related(
            "registration", "registration__unit", "invoice",
            "coverage_assignment__coverage__plan__payer"
        ).prefetch_related("lines", "adjudications")
        if registration_id:
            registration = Registration.objects.filter(pk=registration_id).first()
            if registration is None:
                return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
            if not has_scoped_role(request.user, CLAIM_READ_ROLES, unit_id=str(registration.unit_id)):
                return Response({"detail": "Akses klaim tidak diizinkan untuk unit ini."}, status=403)
            rows = query.filter(registration=registration).order_by("coverage_assignment__priority")
            return Response({"items": [claim_data(row) for row in rows]})
        claim = query.filter(claim_no=claim_no).first()
        if claim is None:
            return Response({"detail": "Klaim tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CLAIM_READ_ROLES, unit_id=str(claim.registration.unit_id)):
            return Response({"detail": "Akses klaim tidak diizinkan untuk unit ini."}, status=403)
        record_audit_event(
            actor=request.user,
            event_type="claims.claim.read",
            subject_type="Claim",
            subject_id=str(claim.id),
            metadata={"claim_no": claim.claim_no, "claim_status": claim.status},
            organization_unit=claim.registration.unit,
        )
        return Response(claim_data(claim))

    def post(self, request):
        serializer = ClaimCreateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        registration = Registration.objects.filter(pk=data["registration_id"]).first()
        assignment = RegistrationCoverage.objects.select_related("registration").filter(
            pk=data["coverage_assignment_id"], registration_id=data["registration_id"]
        ).first()
        if registration is None or assignment is None:
            return Response({"detail": "Registrasi atau penetapan penjamin tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, CLAIM_CREATE_ROLES, unit_id=str(registration.unit_id)
        ):
            return Response({"detail": "Pembuatan klaim memerlukan role penjamin di unit ini."}, status=403)
        try:
            claim = create_claim(actor=request.user, **data)
        except ClaimConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        claim = Claim.objects.select_related(
            "registration", "invoice", "coverage_assignment__coverage__plan__payer"
        ).prefetch_related("lines", "adjudications").get(pk=claim.pk)
        return Response(claim_data(claim), status=201)


class ClaimSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, claim_id):
        claim = Claim.objects.select_related("registration__unit").filter(pk=claim_id).first()
        if claim is None:
            return Response({"detail": "Klaim tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, CLAIM_CREATE_ROLES, unit_id=str(claim.registration.unit_id)
        ):
            return Response({"detail": "Pengajuan klaim memerlukan role penjamin di unit ini."}, status=403)
        try:
            row = submit_claim(claim_id=str(claim.id), actor=request.user)
        except ClaimConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        row = Claim.objects.select_related(
            "registration", "invoice", "coverage_assignment__coverage__plan__payer"
        ).prefetch_related("lines", "adjudications").get(pk=row.pk)
        return Response(claim_data(row))


class ClaimAdjudicationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, claim_id):
        claim = Claim.objects.select_related("registration__unit").filter(pk=claim_id).first()
        if claim is None:
            return Response({"detail": "Klaim tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, ADJUDICATE_ROLES, unit_id=str(claim.registration.unit_id)
        ):
            return Response({"detail": "Adjudikasi memerlukan role penelaah penjamin."}, status=403)
        serializer = AdjudicationRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            row = adjudicate_claim(claim_id=str(claim.id), actor=request.user, **serializer.validated_data)
        except ClaimConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({
            "id": str(row.id),
            "claim_id": str(row.claim_id),
            "version": row.version,
            "allowed_amount": str(row.allowed_amount),
            "denied_amount": str(row.denied_amount),
            "patient_responsibility": str(row.patient_responsibility),
            "external_reference": row.external_reference,
        }, status=201)


class ClaimCollectionReceiptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, claim_id, collection_type):
        if collection_type == "remittances":
            actual_type = ClaimCollection.CollectionType.PAYER_REMITTANCE
            roles = REMITTANCE_ROLES
        elif collection_type == "patient-payments":
            actual_type = ClaimCollection.CollectionType.PATIENT_PAYMENT
            roles = PATIENT_PAYMENT_ROLES
        else:
            return Response({"detail": "Jenis penerimaan tidak dikenal."}, status=404)
        claim = Claim.objects.select_related("registration__unit").filter(pk=claim_id).first()
        if claim is None:
            return Response({"detail": "Klaim tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, roles, unit_id=str(claim.registration.unit_id)):
            return Response({"detail": "Role tidak diizinkan mencatat penerimaan ini."}, status=403)
        serializer = CollectionRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            row = collect_claim_balance(
                claim_id=str(claim.id),
                collection_type=actual_type,
                actor=request.user,
                **serializer.validated_data,
            )
        except ClaimConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        claim.refresh_from_db()
        return Response({
            "collection_id": str(row.id),
            "claim_id": str(claim.id),
            "collection_type": row.collection_type,
            "amount": str(row.amount),
            "payer_balance": str(claim.payer_balance),
            "patient_balance": str(claim.patient_balance),
            "claim_status": claim.status,
        }, status=201)


class ReceivableSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        registration_id = request.query_params.get("registration_id", "").strip()
        if not registration_id:
            return Response({"detail": "registration_id wajib diisi."}, status=400)
        registration = Registration.objects.filter(pk=registration_id).first()
        if registration is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, CLAIM_READ_ROLES, unit_id=str(registration.unit_id)):
            return Response({"detail": "Akses piutang tidak diizinkan untuk unit ini."}, status=403)
        entries = ReceivableLedgerEntry.objects.filter(claim__registration=registration)
        result = {}
        for account_type in ReceivableLedgerEntry.AccountType.values:
            filtered = entries.filter(account_type=account_type)
            totals = filtered.values("direction").annotate(total=Sum("amount"))
            by_direction = {x["direction"]: x["total"] or Decimal("0.00") for x in totals}
            result[account_type.lower()] = str(
                by_direction.get(ReceivableLedgerEntry.Direction.DEBIT, Decimal("0.00"))
                - by_direction.get(ReceivableLedgerEntry.Direction.CREDIT, Decimal("0.00"))
            )
        return Response({"registration_id": str(registration.id), "balances": result})
