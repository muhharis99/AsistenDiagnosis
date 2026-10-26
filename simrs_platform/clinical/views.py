from __future__ import annotations

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from clinical.models import ClinicalNote, Encounter
from clinical.services import ClinicalConflict, append_clinical_note, create_encounter, record_diagnosis
from frontoffice.models import Registration
from identity.models import RoleAssignment
from platform_core.audit import record_audit_event
from platform_core.authorization import has_scoped_role


CLINICAL_READ_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE,
    RoleAssignment.Role.AUDITOR,
}
CLINICAL_WRITE_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DOCTOR,
    RoleAssignment.Role.NURSE,
}
DOCTOR_ROLES = {RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.DOCTOR}


class EncounterCreateRequest(serializers.Serializer):
    registration_id = serializers.UUIDField()
    encounter_type = serializers.ChoiceField(choices=Encounter.EncounterType.choices)
    chief_complaint = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ClinicalNoteRequest(serializers.Serializer):
    note_type = serializers.ChoiceField(choices=ClinicalNote.NoteType.choices)
    subjective = serializers.CharField(required=False, allow_blank=True)
    objective = serializers.CharField(required=False, allow_blank=True)
    assessment = serializers.CharField(required=False, allow_blank=True)
    plan = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not any(
            attrs.get(key, "").strip()
            for key in ("subjective", "objective", "assessment", "plan")
        ):
            raise serializers.ValidationError("Isi setidaknya satu bagian catatan klinis.")
        return attrs


class DiagnosisRequest(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    display = serializers.CharField(max_length=240)
    is_primary = serializers.BooleanField(default=False)


def encounter_data(encounter):
    return {
        "id": str(encounter.id),
        "registration_id": str(encounter.registration_id),
        "registration_no": encounter.registration.registration_no,
        "patient_mrn": encounter.registration.patient.mrn,
        "unit_id": str(encounter.registration.unit_id),
        "unit_code": encounter.registration.unit.code,
        "encounter_type": encounter.encounter_type,
        "status": encounter.status,
        "chief_complaint": encounter.chief_complaint,
        "opened_at": encounter.opened_at.isoformat(),
        "created_at": encounter.created_at.isoformat(),
    }


def note_data(note):
    return {
        "id": str(note.id),
        "version": note.version,
        "note_type": note.note_type,
        "subjective": note.subjective,
        "objective": note.objective,
        "assessment": note.assessment,
        "plan": note.plan,
        "author_id": note.author_id,
        "signed_at": note.signed_at.isoformat(),
    }


class EncounterCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unit_id = request.query_params.get("unit_id", "").strip()
        if not unit_id:
            return Response({"detail": "unit_id wajib diisi."}, status=400)
        if not has_scoped_role(request.user, CLINICAL_READ_ROLES, unit_id=unit_id):
            return Response({"detail": "Akses encounter tidak diizinkan untuk unit ini."}, status=403)
        rows = (
            Encounter.objects.select_related(
                "registration", "registration__patient", "registration__unit"
            )
            .filter(registration__unit_id=unit_id)
            .order_by("-opened_at")[:100]
        )
        return Response({"items": [encounter_data(row) for row in rows]})

    def post(self, request):
        serializer = EncounterCreateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        registration = Registration.objects.select_related("unit").filter(
            pk=serializer.validated_data["registration_id"]
        ).first()
        if registration is None:
            return Response({"detail": "Registrasi tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, CLINICAL_WRITE_ROLES, unit_id=str(registration.unit_id)
        ):
            return Response({"detail": "Akses pembuatan encounter tidak diizinkan."}, status=403)
        try:
            encounter = create_encounter(
                registration_id=str(registration.id),
                encounter_type=serializer.validated_data["encounter_type"],
                chief_complaint=serializer.validated_data.get("chief_complaint", ""),
                actor=request.user,
            )
        except ClinicalConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        encounter = Encounter.objects.select_related(
            "registration", "registration__patient", "registration__unit"
        ).get(pk=encounter.pk)
        return Response(encounter_data(encounter), status=201)


class ClinicalNoteCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, encounter_id):
        encounter = Encounter.objects.select_related("registration__unit").filter(
            pk=encounter_id
        ).first()
        if encounter is None:
            return Response({"detail": "Encounter tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, CLINICAL_READ_ROLES, unit_id=str(encounter.registration.unit_id)
        ):
            return Response({"detail": "Akses catatan klinis tidak diizinkan."}, status=403)
        rows = encounter.notes.select_related("author").all()
        record_audit_event(
            actor=request.user,
            event_type="clinical.notes.read",
            subject_type="Encounter",
            subject_id=str(encounter.id),
            metadata={"note_count": rows.count()},
            organization_unit=encounter.registration.unit,
        )
        return Response({"items": [note_data(note) for note in rows]})

    def post(self, request, encounter_id):
        encounter = Encounter.objects.select_related("registration__unit").filter(
            pk=encounter_id
        ).first()
        if encounter is None:
            return Response({"detail": "Encounter tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, CLINICAL_WRITE_ROLES, unit_id=str(encounter.registration.unit_id)
        ):
            return Response({"detail": "Akses penulisan catatan klinis tidak diizinkan."}, status=403)
        serializer = ClinicalNoteRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        try:
            note = append_clinical_note(
                encounter_id=str(encounter.id),
                note_type=data["note_type"],
                subjective=data.get("subjective", ""),
                objective=data.get("objective", ""),
                assessment=data.get("assessment", ""),
                plan=data.get("plan", ""),
                actor=request.user,
            )
        except ClinicalConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(note_data(note), status=201)


class DiagnosisCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, encounter_id):
        encounter = Encounter.objects.select_related("registration__unit").filter(
            pk=encounter_id
        ).first()
        if encounter is None:
            return Response({"detail": "Encounter tidak ditemukan."}, status=404)
        if not has_scoped_role(
            request.user, DOCTOR_ROLES, unit_id=str(encounter.registration.unit_id)
        ):
            return Response({"detail": "Pencatatan diagnosis memerlukan role dokter."}, status=403)
        serializer = DiagnosisRequest(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        try:
            row = record_diagnosis(
                encounter_id=str(encounter.id), actor=request.user, **serializer.validated_data
            )
        except ClinicalConflict as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            {
                "id": str(row.id),
                "code": row.code,
                "display": row.display,
                "is_primary": row.is_primary,
                "created_at": row.created_at.isoformat(),
            },
            status=201,
        )
