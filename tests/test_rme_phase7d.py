"""Phase 7D regression tests for outbox integrity and stale source snapshots."""
from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import select

from test_rme_phase6 import GOOD_ENV, FakeTransport, context, create_finished_visit
from rme.integrations.satusehat.client import SATUSEHATClient
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    prepare_sandbox_payload,
    queue_visit_phase6_resources,
    transmit_outbox_item_sandbox,
)
from rme.models import Diagnosis, OutboxSync


def queue_resources(context):
    factory, _, users = context
    visit_id = create_finished_visit(context)
    with factory() as session:
        rows = queue_visit_phase6_resources(session, users["rekam_medis_demo"], visit_id)
        ids = {row.resource_type: row.id for row in rows}
    return factory, users, visit_id, ids


def rewrite_payload(outbox, payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    outbox.payload_json = canonical
    outbox.payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def client_with_transport():
    transport = FakeTransport()
    return SATUSEHATClient(GOOD_ENV, transport=transport), transport


def test_payload_hash_mismatch_blocks_transmission_before_any_http_call(context):
    factory, users, _, ids = queue_resources(context)
    with factory() as session:
        row = session.get(OutboxSync, ids["Condition"])
        row.payload_json = row.payload_json + " "
        session.commit()

    client, transport = client_with_transport()
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="Hash payload"):
            transmit_outbox_item_sandbox(
                session, users["rekam_medis_demo"], ids["Condition"],
                client=client, confirmed_demo_only=True,
            )
    assert transport.calls == []


def test_invalid_json_is_rejected_even_when_its_hash_matches(context):
    factory, users, _, ids = queue_resources(context)
    raw = '{"resourceType":'
    with factory() as session:
        row = session.get(OutboxSync, ids["Condition"])
        row.payload_json = raw
        row.payload_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        session.commit()

    client, transport = client_with_transport()
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="JSON yang valid"):
            prepare_sandbox_payload(session, users["rekam_medis_demo"], ids["Condition"], client)
    assert transport.calls == []


def test_resource_type_must_match_outbox_metadata(context):
    factory, users, _, ids = queue_resources(context)
    with factory() as session:
        row = session.get(OutboxSync, ids["Condition"])
        payload = json.loads(row.payload_json)
        payload["resourceType"] = "Observation"
        rewrite_payload(row, payload)
        session.commit()

    client, transport = client_with_transport()
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="Jenis resource"):
            prepare_sandbox_payload(session, users["rekam_medis_demo"], ids["Condition"], client)
    assert transport.calls == []


def test_rehashed_payload_cannot_reference_another_patient(context):
    factory, users, visit_id, ids = queue_resources(context)
    with factory() as session:
        visit = session.get(__import__("rme.models", fromlist=["Visit"]).Visit, visit_id)
        row = session.get(OutboxSync, ids["Observation"])
        payload = json.loads(row.payload_json)
        payload["subject"]["reference"] = "Patient/demo-patient-999999"
        rewrite_payload(row, payload)
        session.commit()

    client, transport = client_with_transport()
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="Identitas Patient"):
            prepare_sandbox_payload(session, users["rekam_medis_demo"], ids["Observation"], client)
    assert transport.calls == []


def test_phase6_payload_is_blocked_when_source_diagnosis_changes_after_queue(context):
    factory, users, _, ids = queue_resources(context)
    with factory() as session:
        diagnosis = session.scalar(select(Diagnosis).where(Diagnosis.status == "confirmed"))
        assert diagnosis is not None
        diagnosis.clinical_label = "Label yang berubah setelah payload antrean dibuat"
        session.commit()

    client, transport = client_with_transport()
    with factory() as session:
        with pytest.raises(SATUSEHATWorkflowError, match="Data sumber klinis berubah"):
            prepare_sandbox_payload(session, users["rekam_medis_demo"], ids["Condition"], client)
    assert transport.calls == []
