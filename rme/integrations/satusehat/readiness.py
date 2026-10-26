"""Read-only operational readiness summary for SATUSEHAT sandbox."""
from __future__ import annotations

import os
from typing import Mapping, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rme.integrations.satusehat.mapping import sandbox_configuration_checks
from rme.models import AuditLog, OutboxSync, SATUSEHATTransmission, User
from rme.security import append_audit, require_permission, verify_audit_chain


_TRUE_VALUES = {"true", "1", "yes"}
_OUTBOX_STATUSES = ("queued", "mock_accepted", "failed", "blocked")
_TRANSMISSION_STATUSES = ("sending", "succeeded", "failed", "uncertain", "blocked")


def _demo_status_counts(session: Session, model: Any, statuses: tuple[str, ...]) -> dict[str, int]:
    rows = session.execute(
        select(model.status, func.count(model.id))
        .where(model.is_demo.is_(True))
        .group_by(model.status)
    ).all()
    counts = {status: 0 for status in statuses}
    for status, count in rows:
        # Keep the report robust if a future migration adds a new permitted status.
        if isinstance(status, str):
            counts[status] = int(count)
    return counts


def build_sandbox_operational_readiness(
    session: Session,
    user: User,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a sanitized operational snapshot; never opens network or changes transmissions.

    This is a read-only assessment of integration configuration and local demo ledgers.
    It logs the administrative check to the existing audit chain, but does not touch
    outbox/transmission records, payloads, credentials, or database structure.
    """
    require_permission(user, "satusehat:read")
    values = os.environ if env is None else env

    config_checks = sandbox_configuration_checks(values)
    configuration_ready = all(bool(item.get("passed")) for item in config_checks)
    network_opt_in = (values.get("SATUSEHAT_ENABLE_NETWORK") or "false").strip().lower() in _TRUE_VALUES

    outbox_counts = _demo_status_counts(session, OutboxSync, _OUTBOX_STATUSES)
    transmission_counts = _demo_status_counts(session, SATUSEHATTransmission, _TRANSMISSION_STATUSES)
    unresolved_count = transmission_counts.get("sending", 0) + transmission_counts.get("uncertain", 0)

    audit_valid_before, failed_before = verify_audit_chain(session)
    reasons: list[str] = []
    if not configuration_ready:
        reasons.append("configuration_checks_failed")
    if not network_opt_in:
        reasons.append("network_opt_in_disabled")
    if unresolved_count:
        reasons.append("sending_or_uncertain_transmissions_need_review")
    if not audit_valid_before:
        reasons.append("audit_chain_integrity_failed")

    if not configuration_ready or not audit_valid_before:
        status = "BLOCKED"
    elif not network_opt_in or unresolved_count:
        status = "REVIEW_REQUIRED"
    else:
        status = "ELIGIBLE_FOR_OPERATOR_REVIEW"

    # Record the check without secrets, payload content, patient identifiers, or raw responses.
    append_audit(
        session,
        user,
        "satusehat.operational_readiness_checked",
        "System",
        "satusehat-sandbox",
        {
            "status": status,
            "configuration_ready": configuration_ready,
            "network_opt_in": network_opt_in,
            "outbox_counts": outbox_counts,
            "transmission_counts": transmission_counts,
            "audit_chain_valid_before_check": audit_valid_before,
            "network_calls_performed": False,
        },
    )
    session.commit()

    # Verify again so the snapshot covers the newly recorded check as well.
    audit_valid, failed_id = verify_audit_chain(session)
    if not audit_valid:
        if "audit_chain_integrity_failed" not in reasons:
            reasons.append("audit_chain_integrity_failed")
        status = "BLOCKED"

    return {
        "status": status,
        "configuration_ready": configuration_ready,
        "config_checks": config_checks,
        "network_opt_in": network_opt_in,
        "network_calls_performed": False,
        "outbox_counts": outbox_counts,
        "transmission_counts": transmission_counts,
        "unresolved_transmission_count": unresolved_count,
        "audit_chain_valid": audit_valid,
        "audit_first_invalid_entry_id": failed_id,
        "blocking_reasons": reasons,
        "notice": (
            "Pemeriksaan hanya membaca konfigurasi dan ledger demo lokal. "
            "Tidak ada request jaringan, OAuth, POST/PUT, atau perubahan status transmisi. "
            "Status ini bukan bukti koneksi atau penerimaan resource oleh SATUSEHAT."
        ),
    }
