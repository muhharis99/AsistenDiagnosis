"""UI for explicit, synthetic-data-only sandbox MPI and FHIR submissions."""
from __future__ import annotations

import json
import os
import pandas as pd
import streamlit as st
from sqlalchemy import select

from rme.integrations.satusehat.client import SATUSEHATClient, SATUSEHATClientError
from rme.integrations.satusehat.live_service import (
    SATUSEHATWorkflowError,
    list_transmissions,
    search_demo_patient_mpi,
    transmit_outbox_item_sandbox,
    queue_visit_phase6_resources,
)
from rme.models import OutboxSync, Patient, SATUSEHATTransmission, Visit
from rme.security import require_permission


def _allowed(user, permission: str) -> bool:
    try:
        require_permission(user, permission)
        return True
    except PermissionError:
        return False


def render_phase5_sandbox_tools(factory, user, cipher) -> None:
    if not _allowed(user, "satusehat:manage"):
        return

    st.subheader("Fase 5 — API Sandbox (permintaan jaringan eksplisit)")
    enabled = (os.getenv("SATUSEHAT_ENABLE_NETWORK", "false").strip().lower() in {"true", "1", "yes"})
    if not enabled:
        st.warning("Jaringan masih nonaktif. Fitur ini baru memanggil SATUSEHAT jika mode sandbox, kredensial, TLS, dan SATUSEHAT_ENABLE_NETWORK=true disiapkan di .env lokal.")
    else:
        st.warning("Permintaan berikut benar-benar akan mencapai SATUSEHAT STAGING. Gunakan data uji sintetis saja; jangan gunakan nama/NIK atau catatan dari pasien nyata.")
    st.caption("Klien dibatasi ke endpoint staging resmi, tidak mengikuti redirect, menggunakan TLS verification, dan tidak menampilkan atau mencatat client secret, access token, NIK, atau body respons mentah.")

    with st.expander("Fase 6 — Siapkan resource RME untuk outbox (tanpa jaringan)", expanded=True):
        with factory() as session:
            visits = session.scalars(
                select(Visit).where(Visit.is_demo.is_(True), Visit.status == "finished")
                .order_by(Visit.finished_at.desc(), Visit.id.desc()).limit(100)
            ).all()
            visit_options = {f"Kunjungan #{v.id} · {v.visit_number} · selesai": v.id for v in visits}
        if not visit_options:
            st.info("Belum ada kunjungan demo selesai.")
        else:
            with st.form("phase6_queue_resource_set"):
                chosen_visit = st.selectbox("Kunjungan untuk resource FHIR", list(visit_options))
                queue_resources = st.form_submit_button("Siapkan Encounter update, Observation, ClinicalImpression, Condition, dan Composition (mock)")
            if queue_resources:
                try:
                    with factory() as session:
                        rows = queue_visit_phase6_resources(session, user, visit_options[chosen_visit])
                    st.success(f"{len(rows)} resource diperiksa dan tersedia pada outbox lokal. Belum ada request jaringan.")
                    st.dataframe(pd.DataFrame([{
                        "Outbox": row.id, "Resource": row.resource_type,
                        "Status antrean": row.status, "Kunci idempotensi": row.idempotency_key,
                    } for row in rows]), use_container_width=True, hide_index=True)
                    st.caption("Urutan pengiriman yang disarankan: Condition → Observation → ClinicalImpression → Encounter update → Composition.")
                    st.caption("Encounter pada fase ini adalah PUT untuk Encounter sandbox yang ID-nya sudah dipetakan, bukan pembuatan Encounter baru.")
                except Exception as exc:
                    st.error(f"Outbox Fase 6 belum dibuat: {exc}")

    with st.expander("Pencarian ID Patient dari MPI sandbox", expanded=True):
        with factory() as session:
            patients = session.scalars(
                select(Patient).where(Patient.is_demo.is_(True))
                .order_by(Patient.created_at.desc(), Patient.id.desc()).limit(200)
            ).all()
            patient_labels = {
                f"{patient.medical_record_no} · pasien demo internal #{patient.id}": patient.id
                for patient in patients
            }
        if not patient_labels:
            st.info("Belum ada pasien demo untuk diuji.")
        else:
            with st.form("phase5_mpi_search"):
                patient_label = st.selectbox("Pasien demo internal", list(patient_labels))
                confirm_search = st.checkbox("Saya memastikan identitas/NIK pasien ini sepenuhnya fiktif dan disetujui untuk dikirim ke MPI sandbox.")
                submit_search = st.form_submit_button("Cari Patient di MPI sandbox", disabled=not enabled)
            if submit_search:
                try:
                    client = SATUSEHATClient()
                    with factory() as session:
                        result = search_demo_patient_mpi(
                            session, user, patient_labels[patient_label], cipher,
                            confirmed_demo_only=confirm_search, client=client,
                        )
                    st.write(f"Total hasil menurut MPI: {result['total']}")
                    if result["matches"]:
                        st.dataframe(pd.DataFrame(result["matches"]), use_container_width=True, hide_index=True)
                    else:
                        st.info("MPI tidak mengembalikan ID Patient yang dapat dibaca dari hasil pencarian.")
                    if result["ambiguous"]:
                        st.warning("Hasil bukan satu kecocokan tunggal. Jangan memasangkan ID otomatis; verifikasi hasil secara manual.")
                    else:
                        st.info("Satu ID ditemukan. Simpan ke mapping Patient setelah verifikasi manual sumber dan identitas.")
                except (SATUSEHATClientError, SATUSEHATWorkflowError, PermissionError) as exc:
                    st.error(f"Pencarian MPI tidak selesai: {exc}")
                except Exception:
                    st.error("Pencarian MPI gagal; detail teknis tidak ditampilkan untuk menghindari kebocoran data.")

    with st.expander("Kirim satu resource outbox ke sandbox", expanded=True):
        with factory() as session:
            queued = session.scalars(
                select(OutboxSync).where(
                    OutboxSync.is_demo.is_(True), OutboxSync.status == "queued",
                    OutboxSync.resource_type.in_(["Condition", "Observation", "ClinicalImpression", "Encounter", "Composition"]),
                ).order_by(OutboxSync.created_at, OutboxSync.id).limit(100)
            ).all()
            rank = {"Condition": 0, "Observation": 1, "ClinicalImpression": 2, "Encounter": 3, "Composition": 4}
            queued.sort(key=lambda row: (rank.get(row.resource_type, 99), row.created_at, row.id))
            transmissions = session.scalars(select(SATUSEHATTransmission).where(SATUSEHATTransmission.is_demo.is_(True))).all()
            terminal_ids = {row.outbox_id for row in transmissions if row.status in {"succeeded", "sending", "uncertain", "blocked"}}
            queued_options = {
                f"#{row.id} · {row.resource_type} · kunjungan #{row.visit_id}": row.id
                for row in queued if row.id not in terminal_ids
            }
        if not queued_options:
            st.info("Tidak ada outbox demo berstatus queued untuk dikirim.")
        else:
            with st.form("phase5_submit_resource"):
                selected = st.selectbox("Resource (satu kali pengiriman)", list(queued_options))
                confirm_send = st.checkbox("Saya memastikan payload berisi data uji sintetis saja dan menyetujui pengiriman satu resource ke SATUSEHAT STAGING.")
                submit_send = st.form_submit_button("Kirim satu resource", disabled=not enabled)
            if submit_send:
                try:
                    client = SATUSEHATClient()
                    with factory() as session:
                        result = transmit_outbox_item_sandbox(
                            session, user, queued_options[selected], client=client,
                            confirmed_demo_only=confirm_send,
                        )
                    st.write(f"Status transmisi: **{result.status}** · HTTP {result.http_status or '—'}")
                    st.write(f"ID resource eksternal: {result.external_resource_id or 'belum tersedia'}")
                    st.caption(result.response_summary or "Tidak ada ringkasan respons.")
                    if result.status == "uncertain":
                        st.error("Jangan tekan kirim lagi. Status masih belum pasti; lakukan rekonsiliasi manual di sandbox.")
                    elif result.status == "succeeded":
                        st.success("Resource sudah menerima respons sukses dari sandbox.")
                    elif result.status == "failed":
                        st.warning("Sandbox menolak payload. Tinjau kode OperationOutcome dan perbaiki resource sebelum mencoba lagi.")
                except (SATUSEHATClientError, SATUSEHATWorkflowError, PermissionError) as exc:
                    st.error(f"Transmisi tidak dilakukan: {exc}")
                except Exception:
                    st.error("Transmisi gagal; detail teknis tidak ditampilkan. Periksa audit trail dan status transmisi.")

    if _allowed(user, "satusehat:read"):
        with factory() as session:
            records = list_transmissions(session, user)
        if records:
            st.markdown("### Riwayat transmisi tanpa body respons")
            st.dataframe(pd.DataFrame([{
                "Outbox ID": row.outbox_id,
                "Status": row.status,
                "Percobaan": row.attempt_count,
                "HTTP": row.http_status or "—",
                "ID SATUSEHAT": row.external_resource_id or "—",
                "Kode OperationOutcome": ", ".join(json.loads(row.operation_outcome_codes_json or "[]")) or "—",
                "Ringkasan": row.response_summary or "—",
            } for row in records]), use_container_width=True, hide_index=True)
            st.caption("Status uncertain berarti server mungkin sudah menerima POST tetapi respons tak dapat dipastikan; sistem mencegah retry otomatis untuk menghindari duplikasi.")
