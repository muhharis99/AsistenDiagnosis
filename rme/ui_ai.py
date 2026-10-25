"""Panel Asisten Diagnosis; seluruh keluaran adalah saran, bukan diagnosis final."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import streamlit as st
from sqlalchemy import select
from config import SYMPTOM_METADATA_PATH
from data import disease_label, load_disease_mapping, load_symptom_mapping, symptom_label
from rme.ai_service import AIConsentRequired, AIWorkflowError, ai_consent_granted, read_symptom_metadata, request_symptom_suggestion, review_ai_suggestion
from rme.models import AISuggestion, AISuggestionReview, AuditLog, Patient, User, Visit
from rme.schemas import AISuggestionReviewInput
from safety import detect_red_flags, load_safety_config, red_flag_message

ACTIONS = {
 "accepted_as_working_hypothesis": "Catat sebagai kandidat hipotesis kerja",
 "modified": "Ubah saran (catatan dokter)",
 "ignored": "Abaikan saran",
}

def _list_json(raw: str) -> list[dict[str, Any]]:
    try:
        obj=json.loads(raw)
        return obj if isinstance(obj,list) else []
    except (TypeError,json.JSONDecodeError):
        return []

def render_ai_panel(factory, user: User, visit: Visit, patient: Patient, age: int) -> None:
    """Panel tersedia untuk dokter berwenang; inference diperiksa kembali di service."""
    st.subheader("Asisten Diagnosis (AI)")
    st.warning("SARAN AI — BUKAN DIAGNOSIS. Diagnosis akhir ditetapkan dokter; pengkodean diverifikasi Perekam Medis.")
    if not user.role or user.role.code != "dokter":
        st.info("Panel ini hanya tersedia untuk Dokter (DPJP).")
        return
    if visit.dpjp_user_id is not None and visit.dpjp_user_id != user.id:
        st.error("Kunjungan ditugaskan kepada DPJP lain.")
        return
    safety=load_safety_config()
    # Baca alert keselamatan dari audit agar tetap tampak setelah session/browser refresh.
    with factory() as session:
        flag_logs=session.scalars(
            select(AuditLog).where(
                AuditLog.action=="ai.red_flag_blocked",
                AuditLog.entity_type=="Visit",
                AuditLog.entity_id==str(visit.id),
            ).order_by(AuditLog.id.asc())
        ).all()
    persisted_ids=set()
    for log in flag_logs:
        try:
            persisted_ids.update(str(x) for x in json.loads(log.details_json).get("red_flag_ids",[]))
        except (json.JSONDecodeError,TypeError):
            continue
    catalog={str(item["id"]):item for item in safety.get("red_flags",[])}
    persisted_flags=[catalog[key] for key in sorted(persisted_ids) if key in catalog]
    if persisted_flags:
        st.error(red_flag_message(persisted_flags,safety))
        st.error("Peringatan gawat darurat telah tercatat untuk kunjungan ini. Inferensi AI tetap diblokir; tindak lanjuti keadaan klinis di luar aplikasi.")
        return
    last_flag=st.session_state.get("rme_active_red_flags")
    if isinstance(last_flag,dict) and last_flag.get("visit_id")==visit.id:
        st.error(red_flag_message(last_flag.get("flags",[]),safety))
        st.error("Model tidak dijalankan. Segera ke IGD atau hubungi 112 / 119; jangan menunggu aplikasi.")
    # Pemeriksaan red flag selalu dapat dipakai, termasuk ketika consent AI belum aktif.
    with st.form(f"rme_emergency_check_{visit.id}"):
        emergency_ids=st.multiselect(
            "Pemeriksaan keselamatan: pilih tanda gawat darurat yang diketahui",
            options=[x["id"] for x in safety.get("red_flags",[])],
            format_func=lambda x: next((item["label"] for item in safety.get("red_flags",[]) if item["id"]==x),x),
        )
        check_emergency=st.form_submit_button("Periksa red flag (tidak menjalankan model)")
    if check_emergency:
        matched=detect_red_flags([],emergency_ids,safety)
        st.session_state["rme_active_red_flags"]={"visit_id":visit.id,"flags":matched} if matched else None
        if matched:
            try:
                # Service memblokir red flag sebelum memeriksa consent atau memuat model.
                with factory() as session:
                    result=request_symptom_suggestion(session,user,visit.id,[],explicit_red_flags=emergency_ids)
                st.session_state["rme_ai_feedback"]={"visit_id":visit.id,**result}
            except Exception:
                st.session_state["rme_ai_feedback"]={"visit_id":visit.id,"status":"red_flag_blocked","message":"Red flag terdeteksi; model tidak dijalankan."}
        st.rerun()

    feedback=st.session_state.get("rme_ai_feedback")
    if isinstance(feedback,dict) and feedback.get("visit_id")==visit.id:
        status=feedback.get("status")
        if status in {"special_population_blocked","insufficient_information"}:
            st.info("**Belum cukup informasi / hasil ditahan.** "+str(feedback.get("message","Konsultasikan langsung ke tenaga kesehatan.")))
            for q in feedback.get("followup_questions",[]): st.write("- "+str(q.get("question",q.get("label","Pertanyaan lanjutan"))))
        if status=="error": st.error(str(feedback.get("message","Permintaan AI gagal.")))

    metadata=read_symptom_metadata()
    features=[str(x) for x in metadata.get("feature_names",[])]
    if not features:
        st.error("Metadata fitur model tidak ditemukan; jalankan training gejala.")
        return
    if bool(metadata.get("is_demo",metadata.get("dataset",{}).get("is_demo",True))):
        st.error("DATA DEMO SINTETIS: hasil hanya menguji alur perangkat lunak dan tidak memiliki makna klinis.")
    else:
        st.info("Model belum tervalidasi klinis pada populasi lokal; skor bukan diagnosis.")
    with factory() as session:
        consent=ai_consent_granted(session,patient.id)
    if consent: st.success("Persetujuan AI-assist aktif.")
    else: st.error("Persetujuan AI-assist belum aktif; inferensi dinonaktifkan sampai persetujuan tercatat.")
    if age<18 or age>=65:
        st.warning("Kelompok usia ini tidak divalidasi oleh prototipe. Service akan menahan inferensi.")
    symptom_map=load_symptom_mapping()
    flag_labels={x["id"]:x["label"] for x in safety.get("red_flags",[])}
    with st.form(f"ai_request_{visit.id}"):
        selected=st.multiselect("Gejala yang benar-benar diketahui",features,format_func=lambda x:symptom_label(x,symptom_map))
        flags=st.multiselect("Tandai gejala gawat darurat",list(flag_labels),format_func=lambda x:flag_labels[x])
        groups=st.multiselect("Kelompok khusus",["Ibu hamil","Penyakit kronis"])
        submitted=st.form_submit_button("Susun dugaan diagnosis banding",type="primary",disabled=not consent)
    if submitted:
        matched=detect_red_flags(selected,flags,safety)
        st.session_state["rme_active_red_flags"]={"visit_id":visit.id,"flags":matched} if matched else None
        try:
            with factory() as session:
                result=request_symptom_suggestion(session,user,visit.id,selected,explicit_red_flags=flags,special_groups=groups)
            st.session_state["rme_ai_feedback"]={"visit_id":visit.id,**result}
            if result.get("status")=="red_flag_blocked":
                st.session_state["rme_active_red_flags"]={"visit_id":visit.id,"flags":result.get("red_flags",matched)}
        except (AIConsentRequired,AIWorkflowError,PermissionError,ValueError) as exc:
            st.session_state["rme_ai_feedback"]={"visit_id":visit.id,"status":"error","message":str(exc)}
        except Exception:
            st.session_state["rme_ai_feedback"]={"visit_id":visit.id,"status":"error","message":"Galat internal. Tidak ada diagnosis resmi yang diubah."}
        st.rerun()

    feedback=st.session_state.get("rme_ai_feedback")
    if isinstance(feedback,dict) and feedback.get("visit_id")==visit.id:
        if feedback.get("status")=="generated":
            st.success("Saran tersimpan untuk tinjauan dokter. Diagnosis resmi tidak dibuat otomatis.")
        elif feedback.get("status") in {"red_flag_blocked","special_population_blocked","insufficient_information","error"}:
            return
    with factory() as session:
        suggestion=session.scalar(select(AISuggestion).where(AISuggestion.visit_id==visit.id).order_by(AISuggestion.id.desc()).limit(1))
        reviews=session.scalars(select(AISuggestionReview).where(AISuggestionReview.suggestion_id==suggestion.id).order_by(AISuggestionReview.id.desc()).limit(10)).all() if suggestion else []
    if suggestion is None:
        st.info("Belum ada saran AI pada kunjungan ini.")
        return
    if suggestion.status=="insufficient_information":
        st.info("**Belum cukup informasi.** Skor top-1 di bawah ambang empiris; sistem menahan dugaan.")
        for q in _list_json(suggestion.followup_questions_json): st.write("- "+str(q.get("question",q.get("label","Pertanyaan lanjutan"))))
        return
    candidates=_list_json(suggestion.output_candidates_json)
    explanations=_list_json(suggestion.explanations_json)
    followups=_list_json(suggestion.followup_questions_json)
    disease_map=load_disease_mapping()
    st.markdown("#### Tiga dugaan diagnosis banding")
    st.caption(f"Skor top-1 {suggestion.max_probability:.1%}; ambang penahanan {suggestion.confidence_threshold:.1%}. Bukan probabilitas klinis tervalidasi.")
    for i,c in enumerate(candidates,1):
        st.markdown(f"**{i}. {disease_label(str(c.get('label','')),disease_map)} — {float(c.get('probability',0)):.1%}**")
    st.markdown("#### Faktor dan pertanyaan lanjutan")
    for i,e in enumerate(explanations,1):
        with st.expander(str(e.get("disease",f"Kandidat {i}"))):
            present=e.get("supporting_symptoms",[])
            absent=e.get("commonly_seen_but_not_selected",[])
            st.write("Gejala pilihan yang sering muncul pada sampel kelas:",", ".join(str(x.get("label",x.get("id"))) for x in present) or "Tidak ada fitur menonjol.")
            st.write("Gejala lazim di sampel kelas namun belum dipilih:",", ".join(str(x.get("label",x.get("id"))) for x in absent) or "Tidak ada fitur tambahan yang memenuhi kriteria.")
            st.caption(str(e.get("note","Prevalensi data bukan kriteria diagnosis.")))
    for q in followups:
        st.write(f"- {q.get('question',q.get('label','Pertanyaan lanjutan'))} (information gain={float(q.get('information_gain',0)):.3f})")
    st.info("Kode ICD-10 belum dipilih pada Fase 2. Label penyakit belum merupakan diagnosis terverifikasi.")
    st.markdown("#### Tinjauan dokter — tidak mengubah diagnosis resmi")
    if not candidates:
        return
    labels=[str(x.get("label","")) for x in candidates]
    with st.form(f"ai_review_{suggestion.id}"):
        action=st.selectbox("Aksi",list(ACTIONS),format_func=lambda x:ACTIONS[x])
        selected_candidate=st.selectbox("Kandidat",labels,format_func=lambda x:disease_label(x,disease_map))
        modified=st.text_input("Saran versi dokter (khusus aksi Ubah)")
        reason=st.text_area("Alasan (wajib untuk Ubah/Abaikan)")
        save=st.form_submit_button("Catat tinjauan")
    if save:
        payload={"action":action,"selected_candidate":selected_candidate if action=="accepted_as_working_hypothesis" else None,
                 "modified_candidate":modified if action=="modified" else None,
                 "reason":reason if action in {"modified","ignored"} else None}
        try:
            with factory() as session:
                review_ai_suggestion(session,user,suggestion.id,AISuggestionReviewInput(**payload))
            st.success("Tinjauan tercatat dalam audit; tidak ada diagnosis resmi yang dibuat.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if reviews:
        st.markdown("#### Riwayat tinjauan")
        for item in reviews:
            st.write(f"- {item.action} · {item.created_at} · {item.selected_candidate or item.modified_candidate or '—'}")
            if item.reason: st.caption("Alasan: "+item.reason)
    with st.expander("Metadata dan jejak model"):
        st.write("Versi model:",suggestion.model_version)
        st.write("Versi kode:",suggestion.code_version)
        st.code(f"Model SHA-256: {suggestion.model_artifact_sha256}\nData latih SHA-256: {suggestion.training_data_sha256}")
        st.write("Dibuat UTC:",suggestion.created_at.isoformat())


def render_ai_evaluation() -> None:
    """Tampilkan status dataset/model dan artefak evaluasi yang sudah disimpan."""
    from config import OUTPUT_DIR, SCREENING_METADATA_PATH
    st.header("Evaluasi Model Asisten Diagnosis")
    symptom_meta=read_symptom_metadata()
    if not symptom_meta:
        st.info("Metadata model gejala belum tersedia. Jalankan python train_symptom.py.")
    else:
        is_demo=bool(symptom_meta.get("is_demo",symptom_meta.get("dataset",{}).get("is_demo",True)))
        if is_demo:
            st.error("DATA DEMO SINTETIS: metrik berikut hanya memeriksa pipeline software, bukan performa klinis.")
        st.subheader("Modul A — diagnosis berbasis gejala")
        st.write("Model:",symptom_meta.get("model","Belum diketahui"))
        st.write("Sumber:",symptom_meta.get("dataset",{}).get("source","Tidak tercatat"))
        st.write("Waktu training UTC:",symptom_meta.get("trained_at_utc","Tidak tercatat"))
        st.json(symptom_meta.get("selected_test_metrics",{}))
        st.caption("Ambang penahanan dugaan statistik, bukan ambang klinis: "+str(symptom_meta.get("confidence_threshold","Tidak tersedia")))
        for filename,caption in [
            ("symptom_confusion_matrix.png","Confusion matrix"),
            ("symptom_calibration_curve.png","Kurva reliabilitas"),
            ("symptom_permutation_importance.png","Permutation importance global"),
            ("symptom_robustness_tests.csv","Uji ketahanan"),
        ]:
            path=OUTPUT_DIR/filename
            if not path.exists(): continue
            st.markdown("**"+caption+"**")
            if path.suffix.lower()==".png":
                st.image(str(path),caption=caption,use_container_width=True)
            else:
                import pandas as pd
                st.dataframe(pd.read_csv(path),use_container_width=True,hide_index=True)
    st.divider()
    st.subheader("Modul B — skrining diabetes")
    try:
        meta=json.loads(Path(SCREENING_METADATA_PATH).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):
        meta={}
    if not meta:
        st.info("Metadata skrining belum tersedia. Jalankan python train_screening.py.")
    else:
        if bool(meta.get("is_demo",meta.get("data",{}).get("is_demo",True))):
            st.error("DATA DEMO SINTETIS: metrik tidak menunjukkan kemampuan mendeteksi diabetes pada pasien nyata.")
        st.write("Model:",meta.get("model","Belum diketahui"))
        st.write("Waktu training UTC:",meta.get("trained_at_utc","Tidak tercatat"))
        st.json(meta.get("test_metrics",{}))
        for filename,caption in [
            ("screening_confusion_matrix.png","Confusion matrix"),
            ("screening_roc_curve.png","Kurva ROC"),
            ("screening_calibration_curve.png","Kurva reliabilitas"),
            ("screening_permutation_importance.png","Permutation importance global"),
        ]:
            path=OUTPUT_DIR/filename
            if path.exists():
                st.markdown("**"+caption+"**")
                st.image(str(path),caption=caption,use_container_width=True)
    st.warning("Model card dan metrik adalah ringkasan teknis. Validasi klinis lokal, kalibrasi eksternal dan review tenaga medis tetap diperlukan.")
