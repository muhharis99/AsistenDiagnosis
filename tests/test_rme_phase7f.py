"""Phase 7F tests for audit hash-chain tamper detection."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rme.models import AuditLog, Base, Role, User
from rme.security import _iso, _payload, append_audit, verify_audit_chain


def _audit_context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        role = Role(code="perekam_medis", name="Perekam Medis")
        session.add(role)
        session.flush()
        user = User(
            username="audit_test_user",
            password_hash="test-only-not-a-real-password-hash",
            display_name="Audit Test User",
            role_id=role.id,
            active=True,
            is_demo=True,
        )
        session.add(user)
        session.commit()
        user_id = user.id
    return engine, factory, user_id


def _event(session, actor, action: str, entity_id: str):
    return append_audit(
        session,
        actor,
        action,
        "OutboxSync",
        entity_id,
        {"status": "uncertain", "payload_body_logged": False},
    )


def _digest(row, previous_hash: str) -> str:
    raw = _payload(
        row.actor_username,
        row.action,
        row.entity_type,
        row.entity_id,
        _iso(row.occurred_at),
        row.details_json,
        previous_hash,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def test_audit_chain_accepts_empty_and_intact_chains():
    engine, factory, user_id = _audit_context()
    with factory() as session:
        assert verify_audit_chain(session) == (True, None)
        actor = session.get(User, user_id)
        _event(session, actor, "phase7f.event.one", "101")
        _event(session, actor, "phase7f.event.two", "102")
        session.commit()

    with factory() as session:
        assert verify_audit_chain(session) == (True, None)
    engine.dispose()


def test_audit_chain_reports_first_changed_details():
    engine, factory, user_id = _audit_context()
    with factory() as session:
        actor = session.get(User, user_id)
        first = _event(session, actor, "phase7f.event.one", "201")
        _event(session, actor, "phase7f.event.two", "202")
        session.commit()
        first_id = first.id

    with factory() as session:
        row = session.get(AuditLog, first_id)
        row.details_json = json.dumps({"status": "succeeded", "payload_body_logged": False})
        session.commit()

    with factory() as session:
        valid, failed_id = verify_audit_chain(session)
        assert valid is False
        assert failed_id == first_id
    engine.dispose()


def test_audit_chain_reports_changed_hash():
    engine, factory, user_id = _audit_context()
    with factory() as session:
        actor = session.get(User, user_id)
        first = _event(session, actor, "phase7f.event.one", "301")
        session.commit()
        first_id = first.id

    with factory() as session:
        row = session.get(AuditLog, first_id)
        row.entry_hash = "f" * 64
        session.commit()

    with factory() as session:
        valid, failed_id = verify_audit_chain(session)
        assert valid is False
        assert failed_id == first_id
    engine.dispose()


def test_audit_chain_reports_broken_predecessor_link():
    engine, factory, user_id = _audit_context()
    with factory() as session:
        actor = session.get(User, user_id)
        _event(session, actor, "phase7f.event.one", "401")
        second = _event(session, actor, "phase7f.event.two", "402")
        session.commit()
        second_id = second.id

    with factory() as session:
        row = session.get(AuditLog, second_id)
        row.previous_hash = "e" * 64
        session.commit()

    with factory() as session:
        valid, failed_id = verify_audit_chain(session)
        assert valid is False
        assert failed_id == second_id
    engine.dispose()
