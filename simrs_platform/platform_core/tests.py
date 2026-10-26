import pytest
from django.core.exceptions import ValidationError

from platform_core.audit import record_audit_event, verify_audit_chain

pytestmark = pytest.mark.django_db


def test_audit_hash_chain_and_append_only(django_user_model):
    user = django_user_model.objects.create_user(username="audit-test", password="not-used")
    event = record_audit_event(
        actor=user,
        event_type="test.read",
        subject_type="Fixture",
        subject_id="synthetic-1",
        metadata={"operation": "read"},
    )
    valid, failed_sequence = verify_audit_chain()
    assert valid is True
    assert failed_sequence is None
    event.event_type = "tampered"
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        event.delete()


def test_sensitive_keys_rejected_from_audit_metadata(django_user_model):
    user = django_user_model.objects.create_user(username="audit-privacy", password="not-used")
    with pytest.raises(ValidationError):
        record_audit_event(
            actor=user,
            event_type="test",
            subject_type="Fixture",
            subject_id="synthetic-2",
            metadata={"patient_name": "Synthetic Person"},
        )
