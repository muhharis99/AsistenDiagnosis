"""Phase 7E tests for explicit read-only reconciliation after uncertain writes."""
from __future__ import annotations

import pytest

from test_rme_phase5 import (
    GOOD_ENV,
    FakeResponse,
    FakeTransport,
    context,
    map_visit,
    prepare_outbox,
)
from rme.integrations.satusehat.client import SATUSEHATClient
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    reconcile_uncertain_transmission,
    transmit_outbox_item_sandbox,
)
from rme.models import SATUSEHATTransmission
from sqlalchemy import select


class ReconciliationTransport(FakeTransport):
    def __init__(self, *, bundle_total=0, resources=None, fail_post=True):
        super().__init__(fail_post=fail_post)
        self.bundle_total = bundle_total
        self.resources = list(resources or [])

    def request(self, method, url, **kwargs):
        if method == "GET" and url.endswith("/Condition"):
            self.calls.append((method, url, kwargs))
            return FakeResponse(200, {
                "resourceType": "Bundle",
                "type": "searchset",
                "total": self.bundle_total,
                "entry": [{"resource": resource} for resource in self.resources],
            })
        return super().request(method, url, **kwargs)


def _uncertain_condition(context, transport):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    client = SATUSEHATClient(GOOD_ENV, transport=transport)
    with factory() as session:
        row = transmit_outbox_item_sandbox(
            session, users["rekam_medis_demo"], outbox_ids["Condition"],
            client=client, confirmed_demo_only=True,
        )
        assert row.status == "uncertain"
    post = next(call for call in transport.calls if call[0] == "POST" and call[1].endswith("/Condition"))
    identifier = post[2]["json"]["identifier"][0]
    return factory, users, outbox_ids["Condition"], client, identifier


def test_uncertain_post_reconciles_only_after_one_exact_server_match(context):
    transport = ReconciliationTransport(bundle_total=0)
    factory, users, outbox_id, client, identifier = _uncertain_condition(context, transport)
    transport.bundle_total = 1
    transport.resources = [{
        "resourceType": "Condition",
        "id": "condition-server-123",
        "identifier": [identifier],
    }]

    with factory() as session:
        result = reconcile_uncertain_transmission(
            session, users["rekam_medis_demo"], outbox_id,
            client=client, confirmed_demo_only=True,
        )
        assert result["status"] == "succeeded"
        assert result["reconciled"] is True
        assert result["external_resource_id"] == "condition-server-123"

    with factory() as session:
        tx = session.scalar(select(SATUSEHATTransmission).where(
            SATUSEHATTransmission.outbox_id == outbox_id
        ))
        assert tx.status == "succeeded"
        assert tx.external_resource_id == "condition-server-123"
        assert tx.attempt_count == 1

    collection_posts = [
        call for call in transport.calls
        if call[0] == "POST" and call[1].endswith("/Condition")
    ]
    reads = [call for call in transport.calls if call[0] == "GET" and call[1].endswith("/Condition")]
    assert len(collection_posts) == 1
    assert len(reads) == 1
    assert reads[0][2]["params"]["identifier"] == f'{identifier["system"]}|{identifier["value"]}'


def test_zero_search_results_keep_uncertain_and_do_not_retry_write(context):
    transport = ReconciliationTransport(bundle_total=0)
    factory, users, outbox_id, client, _ = _uncertain_condition(context, transport)

    with factory() as session:
        result = reconcile_uncertain_transmission(
            session, users["rekam_medis_demo"], outbox_id,
            client=client, confirmed_demo_only=True,
        )
        assert result["status"] == "uncertain"
        assert result["reconciled"] is False
        assert result["match_count"] == 0

    with factory() as session:
        tx = session.scalar(select(SATUSEHATTransmission).where(
            SATUSEHATTransmission.outbox_id == outbox_id
        ))
        assert tx.status == "uncertain"
        assert tx.attempt_count == 1

    collection_posts = [
        call for call in transport.calls
        if call[0] == "POST" and call[1].endswith("/Condition")
    ]
    assert len(collection_posts) == 1


def test_multiple_server_matches_remain_uncertain_for_manual_review(context):
    transport = ReconciliationTransport(bundle_total=0)
    factory, users, outbox_id, client, identifier = _uncertain_condition(context, transport)
    transport.bundle_total = 2
    transport.resources = [
        {"resourceType": "Condition", "id": "condition-server-123", "identifier": [identifier]},
        {"resourceType": "Condition", "id": "condition-server-456", "identifier": [identifier]},
    ]

    with factory() as session:
        result = reconcile_uncertain_transmission(
            session, users["rekam_medis_demo"], outbox_id,
            client=client, confirmed_demo_only=True,
        )
        assert result["status"] == "uncertain"
        assert result["reconciled"] is False
        assert result["match_count"] == 2

    with factory() as session:
        tx = session.scalar(select(SATUSEHATTransmission).where(
            SATUSEHATTransmission.outbox_id == outbox_id
        ))
        assert tx.status == "uncertain"
        assert tx.external_resource_id is None

    collection_posts = [
        call for call in transport.calls
        if call[0] == "POST" and call[1].endswith("/Condition")
    ]
    assert len(collection_posts) == 1


def test_reconciliation_rejects_a_transmission_that_is_not_uncertain(context):
    factory, _, users = context
    _, visit_id, outbox_ids = prepare_outbox(context)
    map_visit(context, visit_id)
    transport = ReconciliationTransport()
    client = SATUSEHATClient(GOOD_ENV, transport=transport)

    with pytest.raises(SATUSEHATWorkflowError, match="uncertain"):
        with factory() as session:
            reconcile_uncertain_transmission(
                session, users["rekam_medis_demo"], outbox_ids["Condition"],
                client=client, confirmed_demo_only=True,
            )

    assert transport.calls == []
