"""Antarmuka Streamlit untuk diagnosis banding gejala dan skrining risiko."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import streamlit as st

from config import (DISCLAIMER, OUTPUT_DIR, SCREENING_METADATA_PATH, SCREENING_MODEL_PATH,
                    SYMPTOM_METADATA_PATH, SYMPTOM_MODEL_PATH)
from data import (disease_label, load_disease_mapping, load_json, load_symptom_mapping,
                  symptom_label)
from explain import (explain_screening_individual, explain_symptom_candidates,
                     insufficient_information, ordered_topk, suggest_followup_symptoms)
from safety import detect_red_flags, load_safety_config, red_flag_message, static_population_warnings

st.set_page_config(page_title="Asisten Diagnosis — Prototipe", page_icon="🩺", layout="wide")


def _load_json_safe(path: Path) -> dict[str, Any]:
    """Baca JSON model; kembalikan objek kosong apabila training belum dijalankan."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_bundle(path: Path) -> dict[str, Any] | None:
    """Muat bundle joblib jika tersedia."""
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception as exc:
        st.error(f"Model tidak dapat dimuat: {exc}")
        return None


def _show_disclaimer() -> None:
    """Tampilkan disclaimer di dekat setiap keluaran prediksi."""
    st.warning("⚠️ " + DISCLAIMER)


def _show_static_warnings(safety_config: dict[str, Any]) -> None:
    """Tampilkan peringatan kelompok khusus secara konsisten."""
    for warning in static_population_warnings(safety_config):
        st.info("Peringatan: " + warning)


def _read_csv_if_exists(filename: str) -> pd.DataFrame | None:
    """Baca hasil evaluasi jika berkas tersedia."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _display_image(filename: str, caption: str) -> None:
    """Tampilkan grafik keluaran training yang tersedia."""
    path = OUTPUT_DIR / filename
    if path.exists():
        st.image(str(path), caption=caption, use_container_width=True)


safety_config = load_safety_config()
symptom_bundle = _load_bundle(SYMPTOM_MODEL_PATH)
screening_bundle = _load_bundle(SCREENING_MODEL_PATH)
symptom_metadata = _load_json_safe(SYMPTOM_METADATA_PATH)
screening_metadata = _load_json_safe(SCREENING_METADATA_PATH)

st.title("🩺 Asisten Diagnosis — Prototipe Riset")
st.caption("Dua modul: diagnosis banding berbasis gejala dan skrining risiko diabetes berbasis data numerik.")

# Peringatan terakhir selalu ditempatkan sebelum seluruh tab; aturan ini independen dari ML.
if "last_red_flags" not in st.session_state:
    st.session_state["last_red_flags"] = []
if "last_patient_group" not in st.session_state:
    st.session_state["last_patient_group"] = []
if st.session_state["last_red_flags"]:
    st.error(red_flag_message(st.session_state["last_red_flags"], safety_config))
    st.error("Jangan menunggu hasil aplikasi. Segera ke IGD atau hubungi 112 / 119.")
if st.session_state["last_patient_group"]:
    st.error("Peringatan kelompok khusus: hasil aplikasi tidak boleh dijadikan acuan untuk " + ", ".join(st.session_state["last_patient_group"]) + ". Konsultasikan langsung ke dokter/fasilitas kesehatan.")
_show_static_warnings(safety_config)

if symptom_bundle and symptom_bundle.get("is_demo"):
    st.warning("MODE DATA DEMO: Modul gejala dilatih dari data sintetis. Dugaan penyakit dan metriknya hanya memeriksa alur perangkat lunak; jangan digunakan untuk menilai pasien.")
if screening_bundle and screening_bundle.get("is_demo"):
    st.warning("MODE DATA DEMO: Modul skrining dilatih dari data numerik sintetis. Probabilitas bukan perkiraan klinis diabetes.")

(tab_symptom, tab_screening, tab_eval, tab_about) = st.tabs([
    "Diagnosis Gejala", "Skrining Risiko", "Hasil Evaluasi Model", "Tentang & Keterbatasan"
])

with tab_symptom:
    st.subheader("Modul A — Diagnosis banding berbasis gejala")
    st.write("Pilih gejala yang benar-benar dialami. Sistem menyusun hingga tiga dugaan statistik; bukan diagnosis pasti.")
    if symptom_bundle is None:
        st.error("Model Modul A belum tersedia. Jalankan `python train_symptom.py` terlebih dahulu.")
    else:
        feature_names = list(symptom_bundle["feature_names"])
        symptom_map = load_symptom_mapping()
        with st.form("symptom_form", clear_on_submit=False):
            selected = st.multiselect(
                "Cari dan pilih gejala",
                options=feature_names,
                format_func=lambda feature: symptom_label(feature, symptom_map),
                help="Nama yang tidak ada dalam kamus terjemahan ditandai untuk ditinjau tenaga medis."
            )
            st.markdown("**Pemeriksaan red flag keselamatan (di luar model)**")
            all_red_flag_labels = {item["id"]: item["label"] for item in safety_config.get("red_flags", [])}
            explicit_flags = st.multiselect(
                "Tandai bila ada gejala gawat darurat berikut, meskipun tidak ada dalam pilihan di atas",
                options=list(all_red_flag_labels),
                format_func=lambda flag_id: all_red_flag_labels[flag_id],
            )
            patient_group = st.multiselect(
                "Kelompok khusus (peringatan statis)",
                options=["Bayi/anak kecil", "Ibu hamil", "Lansia", "Penyakit kronis"],
                help="Kelompok ini tidak tercakup dengan baik dalam dataset; konsultasikan langsung ke dokter."
            )
            submit_symptom = st.form_submit_button("Susun diagnosis banding")
        if submit_symptom:
            flags = detect_red_flags(selected, explicit_flags, safety_config)
            st.session_state["last_red_flags"] = flags
            st.session_state["last_symptoms"] = list(selected)
            st.session_state["last_explicit_flags"] = list(explicit_flags)
            st.session_state["last_patient_group"] = list(patient_group)
            st.session_state["symptom_form_submitted"] = True
            st.rerun()
        # Render hasil terakhir hanya dalam memori sesi; tidak ditulis ke disk atau database.
        if st.session_state.get("symptom_form_submitted") and not st.session_state.get("last_red_flags"):
            selected_last = list(st.session_state.get("last_symptoms", []))
            if st.session_state.get("last_patient_group"):
                st.error("Hasil ditahan: prototipe ini tidak sesuai sebagai acuan untuk kelompok berikut: " + ", ".join(st.session_state["last_patient_group"]) + ". Konsultasikan langsung ke dokter/fasilitas kesehatan.")
                _show_disclaimer()
            elif not selected_last:
                st.info("**Belum cukup informasi.** Belum ada gejala yang dipilih. Pilih sedikitnya tiga gejala yang benar-benar dialami sebelum meminta dugaan statistik.")
                _show_disclaimer()
            elif len(set(selected_last)) < 3:
                st.info("**Belum cukup informasi.** Pilih sedikitnya tiga gejala yang benar-benar dialami. Sistem tidak memunculkan dugaan dari gejala yang terlalu sedikit.")
                st.write("Jangan menambahkan gejala yang sebenarnya tidak dialami hanya untuk mendapatkan keluaran.")
                _show_disclaimer()
            else:
                feature_names = list(symptom_bundle["feature_names"])
                x_row = pd.DataFrame([[1 if f in selected_last else 0 for f in feature_names]], columns=feature_names)
                model = symptom_bundle["model"]
                probabilities = model.predict_proba(x_row)[0]
                top = ordered_topk(probabilities, model.classes_, k=3)
                top_prob = top[0]["probability"] if top else 0.0
                hold, reason = insufficient_information(selected_last, top_prob, symptom_bundle["confidence_threshold"])
                if hold:
                    st.info("**Belum cukup informasi.** " + reason)
                    st.write("Tambahkan informasi yang benar-benar diketahui dan konsultasikan keluhan ke tenaga kesehatan.")
                    _show_disclaimer()
                else:
                    disease_map = load_disease_mapping()
                    explanations = explain_symptom_candidates(
                        symptom_bundle["X_train"], symptom_bundle["y_train"], selected_last, top
                    )
                    st.markdown("### Tiga dugaan diagnosis banding")
                    confidence = "Tinggi" if top_prob >= 0.85 else "Sedang" if top_prob >= max(0.65, float(symptom_bundle["confidence_threshold"])) else "Rendah"
                    st.metric("Tingkat keyakinan statistik model", confidence)
                    st.caption(f"Ambang penahanan dugaan empiris: {symptom_bundle['confidence_threshold']:.1%}. Ambang ini diturunkan dari prediksi OOF terkalibrasi dan bukan ambang klinis.")
                    for rank, item in enumerate(top, start=1):
                        st.markdown(f"**{rank}. {disease_label(item['label'], disease_map)} — {item['probability']:.1%}**")
                    st.caption("Probabilitas menunjukkan skor model di antara kelas dataset, bukan probabilitas klinis tervalidasi.")
                    st.markdown("#### Penjelasan kandidat")
                    for item in explanations:
                        with st.expander(item["disease"]):
                            supported = item["supporting_symptoms"]
                            absent = item["commonly_seen_but_not_selected"]
                            st.write("**Gejala pilihan yang sering muncul pada sampel kelas ini:**")
                            st.write(", ".join(f"{x['label']} ({x['training_prevalence']:.0%})" for x in supported) if supported else "Tidak ditemukan gejala pilihan yang menonjol pada sampel training kelas ini.")
                            st.write("**Gejala yang sering muncul dalam sampel kelas tetapi belum dipilih:**")
                            st.write(", ".join(f"{x['label']} ({x['training_prevalence']:.0%})" for x in absent) if absent else "Tidak ada gejala tambahan dengan prevalensi >=30% yang belum dipilih pada data training.")
                            st.caption(item["note"])
                    st.markdown("#### Tiga pertanyaan lanjutan yang paling membedakan kandidat")
                    questions = suggest_followup_symptoms(symptom_bundle["X_train"], symptom_bundle["y_train"], top, selected_last, n_questions=3)
                    if questions:
                        for q in questions:
                            st.write(f"- {q['question']} (information gain={q['information_gain']:.3f})")
                    else:
                        st.write("Data tidak cukup untuk menghitung pertanyaan pembeda. Perlu tinjauan tenaga medis.")
                    disease_info = load_json(Path(__file__).resolve().parent / "config" / "disease_info.json").get("default", {})
                    st.markdown("#### Saran umum non-resep")
                    st.write(disease_info.get("description", "Perlu ditinjau tenaga medis."))
                    for advice in disease_info.get("general_advice", []):
                        st.write(f"- {advice}")
                    _show_disclaimer()
        if st.session_state.get("last_red_flags"):
            st.error(red_flag_message(st.session_state["last_red_flags"], safety_config))
            st.write("Model tidak dijalankan untuk menghasilkan dugaan dalam hasil ini karena ada red flag.")
            _show_disclaimer()

with tab_screening:
    st.subheader("Modul B — Skrining indikasi risiko diabetes")
    st.write("Model berbasis data numerik Pima; dataset sumber terbatas pada perempuan keturunan Pima berusia 21 tahun ke atas.")
    if screening_bundle is None:
        st.error("Model Modul B belum tersedia. Jalankan `python train_screening.py` terlebih dahulu.")
    else:
        with st.form("screening_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            with c1:
                pregnancies = st.number_input("Jumlah kehamilan (Pregnancies)", min_value=0, max_value=20, value=1, step=1)
                glucose = st.number_input("Glukosa (mg/dL)", min_value=20.0, max_value=500.0, value=110.0, step=1.0)
                blood = st.number_input("Tekanan darah diastolik (mmHg)", min_value=20.0, max_value=250.0, value=72.0, step=1.0)
                skin = st.number_input("Ketebalan lipatan kulit (mm)", min_value=0.0, max_value=100.0, value=25.0, step=1.0)
            with c2:
                insulin = st.number_input("Insulin (unit sesuai dataset; nilai 0 dianggap hilang)", min_value=0.0, max_value=1000.0, value=80.0, step=1.0)
                bmi = st.number_input("BMI (kg/m²)", min_value=10.0, max_value=80.0, value=27.0, step=0.1)
                pedigree = st.number_input("Diabetes Pedigree Function", min_value=0.0, max_value=3.0, value=0.4, step=0.01)
                age = st.number_input("Usia (tahun; dataset sumber usia >=21)", min_value=21, max_value=120, value=35, step=1)
            screening_special_group = st.multiselect(
                "Pilih bila pasien termasuk kelompok yang perlu konsultasi langsung",
                options=["Ibu hamil", "Penyakit kronis"],
                help="Untuk lansia (>=65 tahun), hasil akan ditahan otomatis."
            )
            submit_screen = st.form_submit_button("Hitung indikasi risiko")
        if submit_screen and (int(age) >= 65 or screening_special_group):
            groups = list(screening_special_group)
            if int(age) >= 65:
                groups.append("Lansia (usia >=65 tahun)")
            st.error("Hasil skrining ditahan karena pasien termasuk kelompok yang memerlukan penilaian langsung: " + ", ".join(groups) + ". Konsultasikan ke dokter/fasilitas kesehatan.")
            _show_disclaimer()
        elif submit_screen:
            feature_names = list(screening_bundle["feature_names"])
            values = {"Pregnancies": pregnancies, "Glucose": glucose, "BloodPressure": blood,
                      "SkinThickness": skin, "Insulin": insulin, "BMI": bmi,
                      "DiabetesPedigreeFunction": pedigree, "Age": age}
            row = pd.DataFrame([{name: float(values[name]) for name in feature_names}], columns=feature_names)
            # Nol pada variabel yang tidak masuk akal ditangani oleh pipeline/imputer sama seperti training.
            for col in ("Glucose", "BloodPressure", "SkinThickness", "Insulin", "BMI"):
                if float(row.loc[0, col]) == 0:
                    row.loc[0, col] = np.nan
            model = screening_bundle["model"]
            probability = float(model.predict_proba(row)[0][1])
            threshold = float(screening_bundle["threshold"])
            low_cut = float(screening_bundle["category_low_cut"])
            high_cut = float(screening_bundle["category_high_cut"])
            category = "Rendah" if probability < low_cut else "Sedang" if probability < high_cut else "Tinggi"
            st.markdown("### Hasil skrining")
            st.metric("Probabilitas skor model", f"{probability:.1%}")
            st.metric("Kategori relatif model", category)
            st.caption(f"Threshold keputusan: {threshold:.3f}. Batas kategori berasal dari tertil probabilitas OOF train ({low_cut:.3f}; {high_cut:.3f}), bukan batas klinis.")
            if probability >= threshold:
                st.info("Skor melewati threshold skrining model. Pertimbangkan konsultasi ke dokter/fasilitas kesehatan untuk penilaian dan pemeriksaan yang sesuai.")
            else:
                st.info("Skor di bawah threshold skrining model; hasil ini tidak menyingkirkan diabetes. Konsultasikan keluhan atau faktor risiko dengan tenaga kesehatan.")
            st.markdown("#### Faktor yang mengubah skor model dibanding median data training")
            impacts = explain_screening_individual(model, values, feature_names, screening_bundle.get("reference_medians"))
            for item in impacts:
                st.write(f"- **{item['feature']}**: {item['direction']} (perubahan skor komparatif {item['absolute_change']:.1%}).")
            st.caption("Analisis satu fitur pada satu waktu dan bukan penjelasan kausal. Probabilitas belum tervalidasi untuk pasien Indonesia.")
            _show_disclaimer()

with tab_eval:
    st.subheader("Evaluasi model")
    st.write("Tabel dan grafik dibentuk oleh skrip training. Jika menggunakan DATA DEMO, semua metrik hanya menguji alur kode dan tidak menunjukkan performa klinis.")
    st.markdown("### Modul A — Diagnosis gejala")
    st.markdown("**EDA: sebaran kelas, gejala umum, gejala lintas kelas, dan korelasi**")
    _display_image("symptom_class_distribution.png", "Sebaran kelas/gejala diagnosis")
    eda_col1, eda_col2 = st.columns(2)
    with eda_col1:
        _display_image("symptom_common_features.png", "Gejala yang sering muncul")
        _display_image("symptom_cross_class_features.png", "Gejala yang digunakan banyak kelas")
    with eda_col2:
        _display_image("symptom_feature_correlation.png", "Korelasi antar gejala")
    df_a = _read_csv_if_exists("symptom_model_comparison.csv")
    if df_a is not None:
        st.dataframe(df_a, use_container_width=True)
    else:
        st.info("Belum ada hasil. Jalankan `python train_symptom.py`.")
    selected_a = _read_csv_if_exists("symptom_selected_model_test_metrics.csv")
    if selected_a is not None:
        st.markdown("**Metrik test model terpilih (model terkalibrasi)**")
        st.dataframe(selected_a, use_container_width=True)
    _display_image("symptom_confusion_matrix.png", "Confusion matrix model terpilih (Modul A)")
    _display_image("symptom_calibration_curve.png", "Kurva reliabilitas top-1 (Modul A)")
    _display_image("symptom_permutation_importance.png", "Permutation importance global (Modul A)")
    robustness = _read_csv_if_exists("symptom_robustness_tests.csv")
    if robustness is not None:
        st.markdown("**Uji ketahanan gejala**")
        st.dataframe(robustness, use_container_width=True)
        st.caption("Penurunan pada gangguan buatan mengukur sensitivitas model terhadap manipulasi fitur, bukan bukti performa klinis.")
    recalls = _read_csv_if_exists("symptom_recall_per_disease.csv")
    if recalls is not None:
        st.markdown("**Recall per penyakit/kelas**")
        st.dataframe(recalls, use_container_width=True)
    confusions = _read_csv_if_exists("symptom_top_confusions.csv")
    if confusions is not None:
        st.markdown("**Pasangan kelas yang paling sering tertukar**")
        st.dataframe(confusions, use_container_width=True)

    st.markdown("### Modul B — Skrining diabetes")
    st.markdown("**EDA: distribusi label dan korelasi fitur numerik**")
    _display_image("screening_class_distribution.png", "Distribusi kelas skrining")
    _display_image("screening_correlation.png", "Korelasi fitur numerik skrining")
    df_b = _read_csv_if_exists("screening_model_comparison.csv")
    if df_b is not None:
        st.dataframe(df_b, use_container_width=True)
    else:
        st.info("Belum ada hasil. Jalankan `python train_screening.py`.")
    selected_b = _read_csv_if_exists("screening_selected_test_metrics.csv")
    if selected_b is not None:
        st.markdown("**Metrik test model terpilih (model terkalibrasi; berbeda dari tabel model dasar di atas)**")
        st.dataframe(selected_b, use_container_width=True)
    _display_image("screening_confusion_matrix.png", "Confusion matrix skrining")
    _display_image("screening_roc_curve.png", "Kurva ROC skrining")
    _display_image("screening_calibration_curve.png", "Kurva reliabilitas probabilitas skrining")
    _display_image("screening_permutation_importance.png", "Permutation importance global skrining")
    st.caption("Pada skrining, threshold lebih rendah dapat menaikkan recall namun biasanya juga menaikkan false positive dan menurunkan precision. Periksa metrik dan confusion matrix bersamaan.")
    with st.expander("Metadata eksperimen"):
        st.json({"modul_A": symptom_metadata, "modul_B": screening_metadata})

with tab_about:
    st.subheader("Tentang, sumber data, dan keterbatasan")
    st.markdown("""
    **Modul A — diagnosis banding berbasis gejala** menggunakan dataset *Disease Prediction Using Machine Learning* dari Kaggle (pemilik kaushil268), yang umumnya dilaporkan memiliki `Training.csv` 4.920 baris, 132 fitur gejala, dan 41 kelas. File `Testing.csv` dipakai hanya untuk sanity check opsional, bukan evaluasi utama. Penggunaan data lokal dan pemetaan nama diwajibkan karena file Kaggle perlu diunduh manual.

    **Modul B — skrining numerik diabetes** menggunakan dataset Pima Indians Diabetes: CSV lokal, OpenML, URL cadangan, atau data sintetis DEMO bila sumber tidak tersedia. Nol pada Glucose, BloodPressure, SkinThickness, Insulin, dan BMI dianggap hilang; imputasi dilakukan di dalam pipeline.

    **Keterbatasan penting**
    - Dataset gejala sangat bersih dan memiliki tepat 120 baris per kelas pada versi yang banyak beredar; kemungkinan bukan rekam medis klinis yang representatif. Akurasi mendekati 100% pada data ini bukan bukti performa klinis.
    - Dataset gejala tidak memuat usia, jenis kelamin, durasi, tingkat keparahan, riwayat penyakit, obat, pemeriksaan fisik, maupun hasil laboratorium.
    - Dataset Pima terbatas pada perempuan keturunan Pima berusia 21 tahun ke atas; hasil belum tentu mewakili populasi Indonesia.
    - Probabilitas model bukan probabilitas klinis tervalidasi. Kalibrasi pada dataset kecil/bersih dapat tidak stabil.
    - Semua terjemahan, nama penyakit, pemetaan red flag, dan teks medis pada file konfigurasi ditandai **perlu ditinjau tenaga medis** sebelum penggunaan yang lebih luas.
    - Aplikasi belum tervalidasi klinis dan bukan alat kesehatan berizin. Diperlukan validasi dokter, data lokal Indonesia, evaluasi keselamatan, keamanan, dan kajian regulasi.
    - Input pasien hanya diproses dalam memori sesi oleh aplikasi; kode tidak menyimpan input ke file/database dan tidak mengirimkannya ke layanan pihak ketiga. Hindari memasukkan data identitas pada prototipe.
    - Informasi kesehatan termasuk data pribadi spesifik menurut UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi. Pernyataan ini bukan sertifikasi kepatuhan hukum; penggunaan operasional perlu kajian hukum, keamanan, akses, retensi, dan tata kelola data. Teks UU: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022

    **Sumber keselamatan dan informasi umum**
    - Kemenkes RI, tanda stroke dan tindakan cepat: https://keslan.kemkes.go.id/view_artikel/4465/kenali-stroke-iskemik-dan-bertindak-cepat
    - Kemenkes RI, PSC 119: https://kemkes.go.id/id/layanan/psc-119
    - Komdigi, layanan panggilan darurat 112 (cakupan diselenggarakan pemerintah daerah): https://layanan112.komdigi.go.id/tentang
    - WHO, informasi diabetes: https://www.who.int/news-room/questions-and-answers/item/diabetes
    - BPK RI, UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
    - Dataset gejala Kaggle: https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
    - Dataset Pima di OpenML: https://www.openml.org/search?type=data
    """)
    _show_disclaimer()
