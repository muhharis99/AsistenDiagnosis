"""Phase 7F tests for audit hash-chain tamper detection."""
from __future__ import annotations

import json
import hashlib
from datetime import timezone

from rme.models import AuditLog
from rme.security import _iso, _payload, append_audit, verify_audit_chain


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


def test_audit_chain_accepts_empty_and_intact_chains(context):
    factory, _, users = context
    with factory() as session:
        assert verify_audit_chain(session) == (True, None)
        _event(session, users["rekam_medis_demo"], "phase7f.event.one", "101")
        _event(session, users["rekam_medis_demo"], "phase7f.event.two", "102")
        session.commit()

    with factory() as session:
        assert verify_audit_chain(session) == (True, None)


def test_audit_chain_reports_first_changed_details(context):
    factory, _, users = context
    with factory() as session:
        first = _event(session, users["rekam_medis_demo"], "phase7f.event.one", "201")
        _event(session, users["rekam_medis_demo"], "phase7f.event.two", "202")
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


def test_audit_chain_reports_changed_hash(context):
    factory, _, users = context
    with factory() as session:
        first = _event(session, users["rekam_medis_demo"], "phase7f.event.one", "301")
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


def test_audit_chain_reports_broken_predecessor_link(context):
    factory, _, users = context
    with factory() as session:
        _event(session, users["rekam_medis_demo"], "phase7f.event.one", "401")
        second = _event(session, users["rekam_medis_demo"], "phase7f.event.two", "402")
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
