"""Regression tests for duplicate transmission claims."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from test_rme_phase5 import (
    GOOD_ENV,
    FakeTransport,
    context,
    map_visit,
    prepare_outbox,
)
from rme.integrations.satusehat.client import SATUSEHATClient
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    transmit_outbox_item_sandbox,
)
from rme.models import SATUSEHATTransmission


def test_outbox_with_existing_sending_claim_does_not_call_http(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    with factory() as session:
        session.add(SATUSEHATTransmission(
            outbox_id=outbox_ids["Condition"],
            status="sending",
            attempt_count=1,
            last_attempt_by=users["rekam_medis_demo"].id,
            is_demo=True,
        ))
        session.commit()

    transport = FakeTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="rekonsiliasi manual"):
            transmit_outbox_item_sandbox(
                session,
                users["rekam_medis_demo"],
                outbox_ids["Condition"],
                client=client,
                confirmed_demo_only=True,
            )

    remote_calls = [
        call for call in transport.calls
        if call[1].startswith(GOOD_ENV["SATUSEHAT_BASE_URL"])
    ]
    assert remote_calls == []


def test_failed_transmission_claim_is_atomic_and_only_one_retry_can_win(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    with factory() as session:
        session.add(SATUSEHATTransmission(
            outbox_id=outbox_ids["Condition"],
            status="failed",
            attempt_count=1,
            last_attempt_by=users["rekam_medis_demo"].id,
            is_demo=True,
        ))
        session.commit()

    # Exercise the database compare-and-set predicate directly: after the first
    # claim switches failed -> sending, a second claim must update zero rows.
    from sqlalchemy import update
    with factory() as session:
        first = session.execute(
            update(SATUSEHATTransmission)
            .where(
                SATUSEHATTransmission.outbox_id == outbox_ids["Condition"],
                SATUSEHATTransmission.status == "failed",
            )
            .values(status="sending")
        )
        assert first.rowcount == 1
        session.commit()

    with factory() as session:
        second = session.execute(
            update(SATUSEHATTransmission)
            .where(
                SATUSEHATTransmission.outbox_id == outbox_ids["Condition"],
                SATUSEHATTransmission.status == "failed",
            )
            .values(status="sending")
        )
        assert second.rowcount == 0
        session.rollback()

    with factory() as session:
        row = session.scalar(select(SATUSEHATTransmission).where(
            SATUSEHATTransmission.outbox_id == outbox_ids["Condition"]
        ))
        assert row.status == "sending"
        assert row.attempt_count == 1
