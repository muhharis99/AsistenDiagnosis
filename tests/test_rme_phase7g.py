"""Regression tests for the Phase 7G sanitized operational readiness report."""
from __future__ import annotations

import json
import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from rme.bootstrap import seed_users
from rme.db import build_engine, initialize_database, session_factory
from rme.integrations.satusehat.readiness import build_sandbox_operational_readiness
from rme.models import AuditLog, OutboxSync, SATUSEHATTransmission, User
from rme.security import SensitiveFieldCipher
from rme.services import ensure_reference_data

from test_rme_phase5 import GOOD_ENV, prepare_outbox


@pytest.fixture()
def context():
    # Isolated in-memory database; test never needs SATUSEHAT credentials or a network.
    engine = build_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = session_factory(engine)
    with factory() as session:
        ensure_reference_data(session)
        seed_users(session)
    with factory() as session:
        users = {u.username: u for u in session.scalars(select(User)).all()}
    cipher = SensitiveFieldCipher(Fernet.generate_key().decode())
    yield factory, cipher, users
    engine.dispose()


def test_report_is_sanitized_and_network_off_is_review_required(context):
    factory, _, users = context
    env = dict(GOOD_ENV, SATUSEHAT_ENABLE_NETWORK="false")
    with factory() as session:
        report = build_sandbox_operational_readiness(
            session, users["rekam_medis_demo"], env
        )

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["configuration_ready"] is True
    assert report["network_opt_in"] is False
    assert report["network_calls_performed"] is False
    assert report["audit_chain_valid"] is True
    assert report["unresolved_transmission_count"] == 0
    serialized = json.dumps(report)
    assert GOOD_ENV["SATUSEHAT_CLIENT_SECRET"] not in serialized
    assert GOOD_ENV["SATUSEHAT_CLIENT_ID"] not in serialized
    assert "access_token" not in serialized.lower()


def test_invalid_configuration_blocks_sandbox_readiness(context):
    factory, _, users = context
    env = dict(
        GOOD_ENV,
        SATUSEHAT_BASE_URL="https://example.invalid/fhir",
        SATUSEHAT_TLS_VERIFY="false",
        SATUSEHAT_ENABLE_NETWORK="true",
    )
    with factory() as session:
        report = build_sandbox_operational_readiness(
            session, users["rekam_medis_demo"], env
        )

    assert report["status"] == "BLOCKED"
    assert report["configuration_ready"] is False
    assert "configuration_checks_failed" in report["blocking_reasons"]
    assert report["network_calls_performed"] is False


def test_unresolved_transmission_requires_operator_review(context):
    factory, _, users = context
    _, _, outbox_ids = prepare_outbox(context)
    with factory() as session:
        session.add(SATUSEHATTransmission(
            outbox_id=outbox_ids["Condition"],
            status="uncertain",
            attempt_count=1,
            last_attempt_by=users["rekam_medis_demo"].id,
            is_demo=True,
        ))
        session.commit()

    with factory() as session:
        report = build_sandbox_operational_readiness(
            session, users["rekam_medis_demo"], GOOD_ENV
        )

    assert report["status"] == "REVIEW_REQUIRED"
    assert report["transmission_counts"]["uncertain"] == 1
    assert report["unresolved_transmission_count"] == 1
    assert "sending_or_uncertain_transmissions_need_review" in report["blocking_reasons"]
    assert report["network_calls_performed"] is False


def test_tampered_audit_chain_blocks_readiness(context):
    factory, _, users = context
    with factory() as session:
        row = AuditLog(
            actor_id=users["rekam_medis_demo"].id,
            actor_username=users["rekam_medis_demo"].username,
            action="test.seed",
            entity_type="System",
            entity_id="demo",
            details_json='{"safe":true}',
            previous_hash="0" * 64,
            entry_hash="f" * 64,
        )
        session.add(row)
        session.commit()

    with factory() as session:
        report = build_sandbox_operational_readiness(
            session, users["rekam_medis_demo"], GOOD_ENV
        )

    assert report["status"] == "BLOCKED"
    assert report["audit_chain_valid"] is False
    assert report["audit_first_invalid_entry_id"] is not None
    assert "audit_chain_integrity_failed" in report["blocking_reasons"]


def test_readiness_check_does_not_change_outbox_or_transmission_rows(context):
    factory, _, users = context
    _, _, outbox_ids = prepare_outbox(context)
    with factory() as session:
        before = session.get(OutboxSync, outbox_ids["Condition"]).status
        tx_count_before = session.scalar(
            select(SATUSEHATTransmission.id).limit(1)
        )
        report = build_sandbox_operational_readiness(
            session, users["rekam_medis_demo"], dict(GOOD_ENV, SATUSEHAT_ENABLE_NETWORK="false")
        )
        after = session.get(OutboxSync, outbox_ids["Condition"]).status
        tx_count_after = session.scalar(
            select(SATUSEHATTransmission.id).limit(1)
        )

    assert before == after
    assert tx_count_before == tx_count_after
    assert report["network_calls_performed"] is False
