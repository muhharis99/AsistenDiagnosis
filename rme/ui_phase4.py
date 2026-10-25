"""UI manajemen mapping SATUSEHAT dan preflight sandbox lokal."""
from __future__ import annotations

import os
import pandas as pd
import streamlit as st
from sqlalchemy import select

from rme.models import Visit
from rme.integrations.satusehat.mapping import (
    build_visit_sandbox_preflight,
    list_satusehat_mappings,
    sandbox_configuration_checks,
    upsert_satusehat_mapping,
    verify_satusehat_mapping,
)
from rme.security import require_permission


def _has_permission(user, permission: str) -> bool:
    try:
        require_permission(user, permission)
        return True
    except PermissionError:
        return False


def render_phase4_satusehat_readiness(factory, user) -> None:
    st.subheader("Fase 4 — Mapping identitas dan preflight sandbox")
    st.caption("Panel ini tidak meminta token dan tidak melakukan koneksi jaringan. Semua nilai kredensial hanya diperiksa keberadaannya.")
    config_checks = sandbox_configuration_checks(os.environ)
    st.dataframe(pd.DataFrame([{
        "Pemeriksaan": item["item"],
        "Status": "OK" if item["passed"] else "Belum siap",
        "Catatan": item["detail"],
    } for item in config_checks]), use_container_width=True, hide_index=True)

    if _has_permission(user, "satusehat:mapping:manage"):
        st.markdown("### Tambah/perbarui mapping sandbox")
        st.caption("Isi ID yang diperoleh dari master atau respons SATUSEHAT sandbox. Setiap perubahan membuat mapping kembali berstatus belum diverifikasi.")
        with st.form("satusehat_mapping_upsert"):
            resource_type = st.selectbox("Jenis resource", ["Patient", "Practitioner", "Organization", "Location", "Encounter"])
            local_key = st.text_input("Kunci lokal (ID pasien/dokter/fasilitas/kunjungan atau facility_id:poli)", max_chars=180)
            external_id = st.text_input("SATUSEHAT ID dari sandbox", max_chars=128)
            source = st.text_input("Sumber mapping (URL/dokumen atau nomor respons)", max_chars=500)
            submit = st.form_submit_button("Simpan mapping sebagai belum diverifikasi")
        if submit:
            try:
                with factory() as session:
                    saved = upsert_satusehat_mapping(
                        session, user, resource_type=resource_type, local_key=local_key,
                        external_id=external_id, source=source,
                    )
                st.success(f"Mapping #{saved.id} tersimpan. Statusnya belum diverifikasi.")
                st.rerun()
            except Exception as exc:
                st.error(f"Mapping tidak disimpan: {exc}")

    if _has_permission(user, "satusehat:mapping:read"):
        try:
            with factory() as session:
                mappings = list_satusehat_mappings(session, user)
        except Exception as exc:
            st.error(f"Daftar mapping tidak dapat dibuka: {exc}")
            mappings = []
        if mappings:
            st.markdown("### Daftar mapping")
            st.dataframe(pd.DataFrame([{
                "ID": row.id, "Resource": row.resource_type, "Kunci lokal": row.local_key,
                "ID SATUSEHAT": row.external_id, "Environment": row.environment,
                "Verified": row.verified, "Sumber": row.source,
            } for row in mappings]), use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada mapping sandbox.")

        if mappings and _has_permission(user, "satusehat:mapping:manage"):
            unverified = [row for row in mappings if not row.verified]
            if unverified:
                by_id = {f"#{row.id} · {row.resource_type} · key {row.local_key}": row.id for row in unverified}
                with st.form("satusehat_mapping_verify"):
                    selected = st.selectbox("Mapping yang diperiksa", list(by_id))
                    note = st.text_area("Catatan pemeriksaan sumber dan kecocokan ID (wajib)", max_chars=2000)
                    verify = st.form_submit_button("Tandai mapping terverifikasi")
                if verify:
                    try:
                        with factory() as session:
                            saved = verify_satusehat_mapping(session, user, by_id[selected], note)
                        st.success(f"Mapping #{saved.id} ditandai terverifikasi.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Verifikasi mapping gagal: {exc}")

    if _has_permission(user, "satusehat:read"):
        with factory() as session:
            visits = session.scalars(
                select(Visit).where(Visit.is_demo.is_(True), Visit.status == "finished")
                .order_by(Visit.finished_at.desc(), Visit.id.desc()).limit(100)
            ).all()
            options = {f"Kunjungan ID {visit.id} — finished": visit.id for visit in visits}
        st.markdown("### Preflight untuk satu kunjungan")
        if not options:
            st.info("Belum ada kunjungan selesai untuk diperiksa.")
        else:
            with st.form("satusehat_sandbox_preflight"):
                visit_label = st.selectbox("Kunjungan demo", list(options))
                run = st.form_submit_button("Periksa konfigurasi, consent, coding, dan mapping")
            if run:
                try:
                    with factory() as session:
                        result = build_visit_sandbox_preflight(session, user, options[visit_label], os.environ)
                    st.dataframe(pd.DataFrame([{
                        "Item": check["item"], "Status": "OK" if check["passed"] else "TERHALANG",
                        "Detail": check["detail"],
                    } for check in result["checks"]]), use_container_width=True, hide_index=True)
                    if result["ready"]:
                        st.success("Checklist konfigurasi/mapping lolos pemeriksaan lokal. Ini bukan tanda data berhasil dikirim.")
                    else:
                        st.warning("Preflight belum lengkap. Perbaiki item yang terhalang.")
                    st.caption(str(result["notice"]))
                    st.caption("Fase 4 tidak mengaktifkan OAuth atau HTTP; proses pengiriman sandbox belum diimplementasikan.")
                except Exception as exc:
                    st.error(f"Preflight gagal: {exc}")
