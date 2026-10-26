from __future__ import annotations

from datetime import date
from cryptography.fernet import InvalidToken
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from frontoffice.models import QueueTicket, Registration
from frontoffice.services import WorkflowConflict, arrive_registration, create_registration, transition_queue
from identity.models import RoleAssignment
from mpi.services import decrypt_value
from platform_core.audit import record_audit_event
from platform_core.authorization import has_scoped_role

REGISTRATION_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.REGISTRAR, RoleAssignment.Role.MEDICAL_RECORDS}
QUEUE_READ_ROLES = REGISTRATION_ROLES | {RoleAssignment.Role.DOCTOR, RoleAssignment.Role.NURSE}
QUEUE_MANAGE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.REGISTRAR, RoleAssignment.Role.NURSE}
CARE_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.DOCTOR, RoleAssignment.Role.NURSE}

class RegistrationRequest(serializers.Serializer):
    patient_id = serializers.UUIDField()
    unit_id = serializers.UUIDField()
    visit_date = serializers.DateField(required=False)

class QueueActionRequest(serializers.Serializer):
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True)

def patient_name(patient):
    try:
        return decrypt_value(patient.full_name_ciphertext)
    except (InvalidToken, RuntimeError, ValueError):
        return "Identitas belum dapat didekripsi"

def registration_data(row):
    return {"id": str(row.id), "registration_no": row.registration_no, "patient_id": str(row.patient_id),
        "mrn": row.patient.mrn, "patient_name": patient_name(row.patient), "unit_id": str(row.unit_id),
        "unit_code": row.unit.code, "visit_date": row.visit_date.isoformat(), "status": row.status,
        "created_at": row.created_at.isoformat()}

class RegistrationCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        unit_id = request.query_params.get("unit_id", "").strip()
        raw_date = request.query_params.get("visit_date", timezone.localdate().isoformat())
        if not unit_id:
            return Response({"detail": "unit_id wajib diisi."}, status=400)
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            return Response({"detail": "visit_date harus YYYY-MM-DD."}, status=400)
        if not has_scoped_role(request.user, QUEUE_READ_ROLES, unit_id=unit_id):
            record_audit_event(actor=request.user, event_type="access.denied", subject_type="RegistrationList",
                subject_id="unit-scope", metadata={"operation": "read"})
            return Response({"detail": "Akses registrasi tidak diizinkan untuk unit ini."}, status=403)
        rows = list(Registration.objects.select_related("patient", "unit").filter(unit_id=unit_id, visit_date=day).order_by("created_at")[:500])
        record_audit_event(actor=request.user, event_type="frontoffice.registration.list", subject_type="RegistrationList",
            subject_id=unit_id, metadata={"visit_date": day.isoformat(), "result_count": len(rows)})
        return Response({"items": [registration_data(row) for row in rows], "count": len(rows), "limit": 500})
    def post(self, request):
        serializer = RegistrationRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        if not has_scoped_role(request.user, REGISTRATION_ROLES, unit_id=str(data["unit_id"])):
            record_audit_event(actor=request.user, event_type="access.denied", subject_type="Registration",
                subject_id="create", metadata={"operation": "create"})
            return Response({"detail": "Akses pendaftaran tidak diizinkan untuk unit ini."}, status=403)
        try:
            row = create_registration(patient_id=str(data["patient_id"]), unit_id=str(data["unit_id"]),
                visit_date=data.get("visit_date", timezone.localdate()), actor=request.user)
        except (ValueError, RuntimeError) as exc:
            return Response({"detail": str(exc)}, status=400)
        row = Registration.objects.select_related("patient", "unit").get(pk=row.pk)
        return Response(registration_data(row), status=201)

class ArriveRegistrationView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, registration_id):
        row = Registration.objects.select_related("unit").filter(pk=registration_id).first()
        if row is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(request.user, REGISTRATION_ROLES, unit_id=str(row.unit_id)):
            return Response({"detail": "Akses antrean tidak diizinkan untuk unit ini."}, status=403)
        try:
            ticket = arrive_registration(registration_id=str(row.id), actor=request.user)
        except WorkflowConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"id": str(ticket.id), "queue_code": ticket.queue_code, "number": ticket.number,
            "status": ticket.status, "registration_id": str(ticket.registration_id)}, status=201)

class QueueCollectionView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        unit_id = request.query_params.get("unit_id", "").strip()
        raw_date = request.query_params.get("queue_date", timezone.localdate().isoformat())
        if not unit_id:
            return Response({"detail": "unit_id wajib diisi."}, status=400)
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            return Response({"detail": "queue_date harus YYYY-MM-DD."}, status=400)
        if not has_scoped_role(request.user, QUEUE_READ_ROLES, unit_id=unit_id):
            return Response({"detail": "Akses antrean tidak diizinkan untuk unit ini."}, status=403)
        rows = list(QueueTicket.objects.select_related("unit", "registration", "registration__patient").filter(
            unit_id=unit_id, queue_date=day).order_by("number")[:500])
        record_audit_event(actor=request.user, event_type="frontoffice.queue.list", subject_type="QueueList",
            subject_id=unit_id, metadata={"queue_date": day.isoformat(), "result_count": len(rows)})
        return Response({"items": [{"id": str(t.id), "queue_code": t.queue_code, "number": t.number, "status": t.status,
            "registration_id": str(t.registration_id), "registration_no": t.registration.registration_no,
            "mrn": t.registration.patient.mrn, "patient_name": patient_name(t.registration.patient)} for t in rows],
            "count": len(rows), "limit": 500})

class QueueActionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, ticket_id, action):
        ticket = QueueTicket.objects.filter(pk=ticket_id).first()
        if ticket is None:
            return Response({"detail": "Tiket antrean tidak ditemukan."}, status=404)
        roles = QUEUE_MANAGE_ROLES if action in {"call", "cancel"} else CARE_ROLES
        if not has_scoped_role(request.user, roles, unit_id=str(ticket.unit_id)):
            return Response({"detail": "Akses perubahan antrean tidak diizinkan."}, status=403)
        serializer = QueueActionRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            updated = transition_queue(ticket_id=str(ticket.id), action=action, actor=request.user,
                reason=serializer.validated_data.get("reason", ""))
        except WorkflowConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"id": str(updated.id), "queue_code": updated.queue_code, "status": updated.status})
