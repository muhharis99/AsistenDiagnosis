from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from platform_core.models import AuditChainHead, AuditEvent

GENESIS = "0" * 64
FORBIDDEN_AUDIT_KEYS = {
    "nik",
    "name",
    "full_name",
    "patient_name",
    "clinical_note",
    "payload",
    "token",
    "secret",
    "password",
    "authorization",
    "request_body",
}


def _validate_metadata(metadata: dict[str, Any]) -> None:
    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).strip().lower()
                if normalized in FORBIDDEN_AUDIT_KEYS:
                    raise ValidationError(
                        f"Audit metadata tidak boleh menyimpan data sensitif pada key: {path + normalized}"
                    )
                walk(child, path + normalized + ".")
        elif isinstance(value, list):
            for child in value:
                walk(child, path)

    walk(metadata)


def _material(
    *,
    sequence: int,
    previous_hash: str,
    actor_id: int | None,
    event_type: str,
    subject_type: str,
    subject_id: str,
    organization_unit_id: str | None,
    metadata: dict[str, Any],
    created_at,
) -> bytes:
    document = {
        "sequence": sequence,
        "previous_hash": previous_hash,
        "actor_id": actor_id,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "organization_unit_id": organization_unit_id,
        "metadata": metadata,
        "created_at": created_at.isoformat(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@transaction.atomic
def record_audit_event(
    *,
    actor: Any = None,
    event_type: str,
    subject_type: str,
    subject_id: str,
    metadata: dict[str, Any] | None = None,
    organization_unit=None,
) -> AuditEvent:
    metadata = metadata or {}
    _validate_metadata(metadata)
    AuditChainHead.objects.get_or_create(
        singleton_id=1, defaults={"last_sequence": 0, "last_hash": GENESIS}
    )
    head = AuditChainHead.objects.select_for_update().get(singleton_id=1)
    sequence = head.last_sequence + 1
    previous_hash = head.last_hash
    created_at = timezone.now()
    actor_id = actor.pk if getattr(actor, "is_authenticated", False) else None
    organization_unit_id = str(organization_unit.pk) if organization_unit else None
    event_hash = hashlib.sha256(
        _material(
            sequence=sequence,
            previous_hash=previous_hash,
            actor_id=actor_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            organization_unit_id=organization_unit_id,
            metadata=metadata,
            created_at=created_at,
        )
    ).hexdigest()
    event = AuditEvent.objects.create(
        sequence=sequence,
        actor_id=actor_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        organization_unit=organization_unit,
        metadata=metadata,
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    head.last_sequence = sequence
    head.last_hash = event_hash
    head.save(update_fields=["last_sequence", "last_hash", "updated_at"])
    return event


def verify_audit_chain() -> tuple[bool, int | None]:
    expected_previous = GENESIS
    expected_sequence = 1
    for event in AuditEvent.objects.order_by("sequence").iterator():
        if event.sequence != expected_sequence or event.previous_hash != expected_previous:
            return False, event.sequence
        expected_hash = hashlib.sha256(
            _material(
                sequence=event.sequence,
                previous_hash=event.previous_hash,
                actor_id=event.actor_id,
                event_type=event.event_type,
                subject_type=event.subject_type,
                subject_id=event.subject_id,
                organization_unit_id=str(event.organization_unit_id)
                if event.organization_unit_id
                else None,
                metadata=event.metadata,
                created_at=event.created_at,
            )
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, event.event_hash):
            return False, event.sequence
        expected_previous = event.event_hash
        expected_sequence += 1
    return True, None
