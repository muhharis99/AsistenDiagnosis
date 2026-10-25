"""UI fase 3: diagnosis manual/coding dan antrean SATUSEHAT mock."""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
from sqlalchemy import select

from rme.models import Patient, ResumeMedical, Visit
from rme.security import require_permission
from rme.diagnosis_service import DiagnosisWorkflowError, available_icd10_terms, create_doctor_diagnosis, list_visit_diagnoses, verify_diagnosis_code
from rme.integrations.satusehat.service import MockIntegrationError, list_outbox, process_mock_outbox, queue_visit_for_mock
from rme.ui_phase4 import render_phase4_satusehat_readiness


def _has_permission(user, permission: str) -> bool:
    try:
        require_permission(user, permission)
        return True
    except PermissionError:
        return False


def render_diagnosis_panel(factory, user, visit_id: int) -> None:
    st.divider()
    st.subheader("Diagnosis dokter & verifikasi ICD-10")
    st.caption("Tidak mengambil kandidat AI secara otomatis. Dokter menetapkan diagnosis; Perekam Medis memverifikasi kode sebelum mock SATUSEHAT.")
    try:
        with factory() as session:
            rows = list_visit_diagnoses(session, user, visit_id)
    except PermissionError:
        st.info("Peran Anda tidak memiliki izin melihat diagnosis pada panel ini.")
        return
    except DiagnosisWorkflowError as exc:
        st.warning(str(exc))
        return

    if _has_permission(user, "diagnosis:create"):
        terms = available_icd10_terms()
        if not terms:
            st.warning("Registry belum memiliki kode ICD-10 edisi 2010 berstatus source-verified. Tambahkan data yang telah ditinjau pada data/icd10_seed_2010.csv.")
        else:
            lookup = {term.code: term for term in terms}
            with st.form(f"doctor_diagnosis_{visit_id}"):
                code = st.selectbox(
                    "Kode dari registry ICD-10 2010",
                    options=[term.code for term in terms],
                    format_func=lambda item: f"{item} — {lookup[item].display}",
                )
                label = st.text_input("Diagnosis klinis yang ditetapkan dokter", max_chars=2000)
                confirmed = st.checkbox("Saya dokter DPJP telah menilai dan menegaskan diagnosis ini secara mandiri (bukan otomatis dari AI).")
                submit = st.form_submit_button("Catat diagnosis dokter")
            if submit:
                try:
                    with factory() as session:
                        row = create_doctor_diagnosis(session, user, visit_id, clinical_label=label, icd10_code=code, confirmed=confirmed)
                    st.success(f"Diagnosis #{row.id} tersimpan sebagai {row.status}; verifikasi coding masih pending.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Diagnosis tidak disimpan: {exc}")

    if rows:
        st.markdown("**Diagnosis tercatat pada kunjungan**")
        st.dataframe(pd.DataFrame([{
            "ID": row.id, "Diagnosis dokter": row.clinical_label, "ICD-10": row.icd10_code,
            "Deskripsi registry": row.icd10_display, "Edisi": row.icd10_edition,
            "Status dokter": row.status, "Verifikasi coder": "Terverifikasi" if row.code_verified else "Pending",
        } for row in rows]), use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada diagnosis dokter pada kunjungan ini.")

    if _has_permission(user, "icd:verify"):
        pending = [row for row in rows if row.status == "confirmed" and not row.code_verified]
        for row in pending:
            with st.expander(f"Verifikasi coding diagnosis #{row.id} · {row.icd10_code}"):
                with st.form(f"verify_icd10_{row.id}"):
                    note = st.text_area("Catatan verifikasi kode terhadap dokumentasi dokter (wajib)", max_chars=2000)
                    submit_verify = st.form_submit_button("Verifikasi kode ICD-10")
                if submit_verify:
                    try:
                        with factory() as session:
                            saved = verify_diagnosis_code(session, user, row.id, note)
                        st.success(f"Kode diagnosis #{saved.id} diverifikasi.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Verifikasi gagal: {exc}")


def render_satusehat_panel(factory, user) -> None:
    st.header("Integrasi SATUSEHAT — Fase 3 / MOCK")
    st.warning("MODE MOCK SAJA. Tidak ada OAuth, HTTP, atau pengiriman data ke SATUSEHAT. ID Patient/Encounter/Practitioner pada payload merupakan placeholder demo, bukan nomor IHS.")
    st.caption("Prerekuisit antrean: kunjungan finished, resume final, consent pembukaan/pemanfaatan data aktif, diagnosis confirmed, dan kode ICD-10 diverifikasi Perekam Medis.")
    render_phase4_satusehat_readiness(factory, user)
    if not _has_permission(user, "satusehat:read"):
        if _has_permission(user, "satusehat:mapping:manage") or _has_permission(user, "satusehat:mapping:read"):
            st.info("Peran ini hanya dapat mengelola/membaca mapping teknis; tidak diberi akses ke outbox atau payload klinis.")
        else:
            st.error("Peran Anda tidak memiliki izin melihat antrean integrasi.")
        return
    if _has_permission(user, "satusehat:manage"):
        with factory() as session:
            finished = session.scalars(select(Visit).where(Visit.status == "finished", Visit.is_demo.is_(True))
                                      .order_by(Visit.finished_at.desc(), Visit.id.desc()).limit(100)).all()
            options = {}
            for visit in finished:
                patient = session.get(Patient, visit.patient_id)
                resume = session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id == visit.id))
                options[f"{visit.visit_number} · {patient.medical_record_no if patient else 'RM tidak ditemukan'} · resume {'final' if resume and resume.status == 'final' else 'belum final'}"] = visit.id
        if options:
            labels = list(options)
            with st.form("queue_satusehat_mock"):
                selected = st.selectbox("Kunjungan selesai", labels)
                submit = st.form_submit_button("Bangun resource FHIR dan antrekan (mock)")
            if submit:
                try:
                    with factory() as session:
                        queued = queue_visit_for_mock(session, user, options[selected])
                    st.success(f"{len(queued)} resource berhasil diperiksa dan masuk/ada di outbox mock.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Belum dapat masuk outbox: {exc}")
        else:
            st.info("Belum ada kunjungan finished.")

    try:
        with factory() as session:
            outbox = list_outbox(session, user)
    except Exception as exc:
        st.error(str(exc))
        return
    if outbox:
        st.markdown("### Status outbox")
        st.dataframe(pd.DataFrame([{
            "ID": row.id, "Kunjungan": row.visit_id, "Resource": row.resource_type,
            "Status": row.status, "Attempt": row.attempt_count,
            "SHA-256": row.payload_sha256, "Respons": row.response_summary or "—",
        } for row in outbox]), use_container_width=True, hide_index=True)
        if _has_permission(user, "satusehat:manage"):
            queued_options = {f"#{row.id} · {row.resource_type} · {row.status}": row.id for row in outbox if row.status in {"queued", "failed"}}
            if queued_options:
                with st.form("process_satusehat_mock"):
                    selected_id = st.selectbox("Resource yang akan diproses pada simulator lokal", list(queued_options))
                    process = st.form_submit_button("Simulasikan respons berhasil (tanpa jaringan)")
                if process:
                    try:
                        with factory() as session:
                            result = process_mock_outbox(session, user, queued_options[selected_id])
                        st.success(f"Outbox #{result.id}: {result.status}. {result.response_summary}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Simulasi gagal: {exc}")
        chosen = st.selectbox("Preview payload JSON (data fiktif)", [row.id for row in outbox], format_func=lambda item: next(f"#{row.id} · {row.resource_type} · {row.status}" for row in outbox if row.id == item))
        selected_row = next(row for row in outbox if row.id == chosen)
        with st.expander("Lihat payload untuk inspeksi lokal"):
            st.code(json.dumps(json.loads(selected_row.payload_json), ensure_ascii=False, indent=2), language="json")
            st.caption(f"Hash SHA-256: {selected_row.payload_sha256}. Payload ini bukan bukti lolos validator profil SATUSEHAT.")
    else:
        st.info("Outbox masih kosong. Kunjungan tidak dapat diantrikan sampai semua prasyarat terpenuhi.")
