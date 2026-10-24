"""Pemuatan, pembersihan, dan EDA untuk dua modul asisten diagnosis."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.datasets import fetch_openml

from config import CONFIG_DIR, DATA_DIR, OUTPUT_DIR, RANDOM_STATE

PIMA_COLUMNS = [
    "Pregnancies", "Glucose", "BloodPressure", "SkinThickness", "Insulin",
    "BMI", "DiabetesPedigreeFunction", "Age", "Outcome"
]
PIMA_ZERO_AS_MISSING = ["Glucose", "BloodPressure", "SkinThickness", "Insulin", "BMI"]


def normalize_column_name(value: str) -> str:
    """Seragamkan nama kolom ke snake_case."""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def load_json(path: Path) -> dict[str, Any]:
    """Baca konfigurasi JSON; error ditampilkan secara jelas."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_symptom_mapping() -> dict[str, dict[str, Any]]:
    """Muat pemetaan nama gejala ke Bahasa Indonesia."""
    return load_json(CONFIG_DIR / "symptom_mapping_id.json")


def load_disease_mapping() -> dict[str, dict[str, Any]]:
    """Muat pemetaan nama penyakit ke Bahasa Indonesia."""
    return load_json(CONFIG_DIR / "disease_mapping_id.json")


def symptom_label(feature: str, mapping: dict[str, dict[str, Any]] | None = None) -> str:
    """Terjemahkan nama gejala; label fallback ditandai perlu ditinjau."""
    mapping = mapping or load_symptom_mapping()
    key = normalize_column_name(feature)
    item = mapping.get(key)
    if item:
        return f"{item['label_id']} ⚠ perlu ditinjau medis"
    return f"{key.replace('_', ' ').capitalize()} ⚠ perlu ditinjau medis"


def disease_label(label: str, mapping: dict[str, dict[str, Any]] | None = None) -> str:
    """Terjemahkan nama penyakit; terjemahan bukan verifikasi diagnosis."""
    mapping = mapping or load_disease_mapping()
    original = str(label).strip()
    item = mapping.get(original)
    if item:
        return f"{item['label_id']} ⚠ perlu ditinjau medis"
    # Beberapa sumber mengubah kapitalisasi/ruang; coba kunci yang dinormalisasi.
    norm = normalize_column_name(original)
    for key, value in mapping.items():
        if normalize_column_name(key) == norm:
            return f"{value['label_id']} ⚠ perlu ditinjau medis"
    return f"{original} ⚠ terjemahan perlu ditinjau tenaga medis"


def make_demo_symptom_data(n_per_class: int = 28, seed: int = RANDOM_STATE) -> pd.DataFrame:
    """Buat data sintetis untuk menguji jalannya kode, bukan untuk inferensi medis."""
    rng = np.random.default_rng(seed)
    symptoms = [
        "itching", "skin_rash", "continuous_sneezing", "chills", "joint_pain",
        "stomach_pain", "vomiting", "fatigue", "cough", "high_fever", "breathlessness",
        "headache", "nausea", "loss_of_appetite", "back_pain", "diarrhoea", "mild_fever",
        "yellowing_of_eyes", "chest_pain", "dizziness", "slurred_speech", "loss_of_balance",
        "altered_sensorium", "seizure", "shortness_of_breath", "vomiting_blood",
        "weight_loss", "excessive_hunger", "polyuria", "runny_nose", "redness_of_eyes", "muscle_pain"
    ]
    labels = [f"DATA DEMO — pola sintetis {chr(65 + i)}" for i in range(8)]
    prototypes = [
        ["itching", "skin_rash"], ["continuous_sneezing", "runny_nose", "cough"],
        ["chills", "high_fever", "headache", "muscle_pain"],
        ["stomach_pain", "vomiting", "nausea", "loss_of_appetite"],
        ["fatigue", "weight_loss", "excessive_hunger", "polyuria"],
        ["breathlessness", "cough", "chest_pain"],
        ["joint_pain", "back_pain", "dizziness", "loss_of_balance"],
        ["chest_pain", "slurred_speech", "altered_sensorium", "seizure"]
    ]
    rows: list[dict[str, int | str]] = []
    for label, proto in zip(labels, prototypes):
        for _ in range(n_per_class):
            row: dict[str, int | str] = {s: int(rng.random() < (0.72 if s in proto else 0.035)) for s in symptoms}
            # Beberapa gejala latar membuat data demo tidak terlalu mudah, tetapi tetap sintetis.
            for _j in range(int(rng.integers(0, 3))):
                row[str(rng.choice(symptoms))] = 1
            row["prognosis"] = label
            rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.sample(frac=1, random_state=seed).reset_index(drop=True)


def clean_symptom_dataframe(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Bersihkan kolom dan baris; hitung duplikat sebelum menghapusnya."""
    source_rows = len(frame)
    data = frame.copy()
    # Buang kolom kosong generik dan kolom dengan nilai seluruhnya kosong.
    data = data.loc[:, [not str(c).strip().lower().startswith("unnamed") for c in data.columns]]
    data = data.dropna(axis=1, how="all")
    data.columns = [normalize_column_name(str(c)) for c in data.columns]
    duplicated_columns = list(data.columns[data.columns.duplicated(keep="first")])
    data = data.loc[:, ~data.columns.duplicated(keep="first")]

    target_candidates = ["prognosis", "disease", "diagnosis", "target", "label"]
    target = next((candidate for candidate in target_candidates if candidate in data.columns), None)
    if target is None:
        raise ValueError("Kolom target tidak ditemukan. Diharapkan kolom 'prognosis'.")
    if target != "prognosis":
        data = data.rename(columns={target: "prognosis"})
    data["prognosis"] = data["prognosis"].astype(str).str.strip()
    data = data[data["prognosis"].ne("") & data["prognosis"].ne("nan")].copy()

    feature_columns = [c for c in data.columns if c != "prognosis"]
    for col in feature_columns:
        numeric = pd.to_numeric(data[col], errors="coerce").fillna(0)
        # Dataset gejala seharusnya biner. Nilai non-biner dipetakan >0 ke 1, dilaporkan.
        data[col] = (numeric > 0).astype(np.uint8)
    duplicates = int(data.duplicated(keep="first").sum())
    data = data.drop_duplicates(keep="first").reset_index(drop=True)
    report = {
        "source_rows": source_rows,
        "rows_after_cleaning": len(data),
        "duplicate_rows_removed": duplicates,
        "duplicate_columns_removed": duplicated_columns,
        "feature_count": len(feature_columns),
        "class_count": int(data["prognosis"].nunique()),
        "class_counts": data["prognosis"].value_counts().sort_index().to_dict(),
    }
    return data, report


def find_local_file(directory: Path, filenames: list[str]) -> Path | None:
    """Cari file dengan mengabaikan kapitalisasi nama."""
    if not directory.exists():
        return None
    by_lower = {p.name.lower(): p for p in directory.iterdir() if p.is_file()}
    for name in filenames:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return None


def load_symptom_data(data_dir: Path = DATA_DIR, allow_demo: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Muat Training.csv lokal; jika tidak ada, buat data DEMO sintetis."""
    path = find_local_file(data_dir, ["Training.csv", "training.csv", "train.csv", "symptoms.csv"])
    if path:
        raw = pd.read_csv(path)
        cleaned, report = clean_symptom_dataframe(raw)
        report.update({"source": str(path), "dataset_mode": "KAGGLE_LOCAL", "is_demo": False})
        return cleaned, report
    if not allow_demo:
        raise FileNotFoundError("Training.csv tidak ditemukan di folder data/.")
    raw = make_demo_symptom_data()
    cleaned, report = clean_symptom_dataframe(raw)
    report.update({"source": "generator sintetis lokal", "dataset_mode": "DATA DEMO SINTETIS", "is_demo": True,
                   "note": "Data DEMO hanya menguji perangkat lunak; dilarang menafsirkan metriknya sebagai kinerja medis."})
    return cleaned, report


def load_pima_local_or_remote(data_dir: Path = DATA_DIR, allow_demo: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Muat Pima dari CSV lokal, OpenML, URL publik; jika gagal, hasilkan DATA DEMO."""
    local = find_local_file(data_dir, ["diabetes.csv", "pima.csv", "pima-indians-diabetes.csv"])
    if local:
        raw = pd.read_csv(local)
        source = str(local)
        mode = "PIMA_LOCAL"
    else:
        raw = None
        source = ""
        mode = "PIMA_REMOTE"
        try:
            fetched = fetch_openml(data_id=37, as_frame=True, parser="auto")
            raw = fetched.frame.copy()
            source = "OpenML data_id=37"
        except Exception as exc_openml:
            # Fallback URL alternatif, dengan kolom yang dikenal untuk file tanpa header.
            urls = [
                "https://raw.githubusercontent.com/jbrownlee/Datasets/master/pima-indians-diabetes.data.csv",
                "https://raw.githubusercontent.com/plotly/datasets/master/diabetes.csv",
            ]
            for url in urls:
                try:
                    if "jbrownlee" in url:
                        candidate = pd.read_csv(url, header=None, names=PIMA_COLUMNS)
                    else:
                        candidate = pd.read_csv(url)
                    raw = candidate
                    source = url
                    break
                except Exception:
                    continue
            if raw is None and not allow_demo:
                raise RuntimeError(f"OpenML dan URL fallback gagal: {exc_openml}") from exc_openml
    if raw is None:
        if not allow_demo:
            raise FileNotFoundError("Dataset Pima tidak tersedia dan data demo dimatikan.")
        raw = make_demo_pima_data()
        source = "generator sintetis lokal"
        mode = "DATA DEMO SINTETIS"

    # Samakan nama kolom untuk berbagai variasi sumber.
    aliases = {
        "pregnancies": "Pregnancies", "pregnancy": "Pregnancies", "number_of_pregnancies": "Pregnancies",
        "glucose": "Glucose", "bloodpressure": "BloodPressure", "blood_pressure": "BloodPressure",
        "skinthickness": "SkinThickness", "skin_thickness": "SkinThickness", "insulin": "Insulin",
        "bmi": "BMI", "diabetespedigreefunction": "DiabetesPedigreeFunction",
        "diabetes_pedigree_function": "DiabetesPedigreeFunction", "age": "Age",
        "outcome": "Outcome", "class": "Outcome", "target": "Outcome", "diabetes": "Outcome"
    }
    renames: dict[str, str] = {}
    for col in raw.columns:
        norm = normalize_column_name(str(col))
        if norm in aliases:
            renames[col] = aliases[norm]
    raw = raw.rename(columns=renames)
    if not set(PIMA_COLUMNS).issubset(raw.columns):
        # File headerless yang lain: gunakan kolom klasik jika terdapat tepat 9 kolom.
        if raw.shape[1] == 9:
            raw.columns = PIMA_COLUMNS
        else:
            raise ValueError(f"Kolom dataset Pima tidak lengkap. Kolom saat ini: {list(raw.columns)}")
    frame = raw[PIMA_COLUMNS].copy()
    for col in PIMA_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    # Outcome sumber OpenML kadang berupa tested_positive/tested_negative.
    if frame["Outcome"].dtype == object:
        frame["Outcome"] = frame["Outcome"].astype(str).str.strip().str.lower().map(
            {"tested_positive": 1, "positive": 1, "yes": 1, "true": 1,
             "tested_negative": 0, "negative": 0, "no": 0, "false": 0}
        )
    frame = frame.dropna(subset=["Outcome"]).copy()
    frame["Outcome"] = frame["Outcome"].astype(int)
    frame = frame[frame["Outcome"].isin([0, 1])].reset_index(drop=True)
    report = {
        "source": source, "dataset_mode": mode, "is_demo": mode.startswith("DATA DEMO"),
        "rows": len(frame), "features": PIMA_COLUMNS[:-1], "class_counts": frame["Outcome"].value_counts().to_dict()
    }
    return frame, report


def make_demo_pima_data(n: int = 768, seed: int = RANDOM_STATE) -> pd.DataFrame:
    """Hasilkan data numerik DEMO demi menguji pipeline; bukan simulasi klinis tervalidasi."""
    rng = np.random.default_rng(seed)
    age = rng.integers(21, 75, size=n)
    pregnancies = np.clip(rng.poisson(2.5, size=n), 0, 15)
    glucose = np.clip(rng.normal(115, 27, size=n), 50, 200)
    blood = np.clip(rng.normal(72, 12, size=n), 35, 125)
    skin = np.clip(rng.normal(25, 9, size=n), 5, 60)
    insulin = np.clip(rng.lognormal(4.3, 0.6, size=n), 10, 500)
    bmi = np.clip(rng.normal(31, 7, size=n), 15, 55)
    pedigree = np.clip(rng.lognormal(-1.0, 0.7, size=n), 0.05, 2.5)
    logit = -1.6 + 0.025 * (glucose - 100) + 0.035 * (bmi - 27) + 0.018 * (age - 35) + 0.10 * pregnancies + 0.30 * pedigree
    prob = 1 / (1 + np.exp(-logit))
    outcome = rng.binomial(1, prob)
    frame = pd.DataFrame({
        "Pregnancies": pregnancies, "Glucose": glucose, "BloodPressure": blood,
        "SkinThickness": skin, "Insulin": insulin, "BMI": bmi,
        "DiabetesPedigreeFunction": pedigree, "Age": age, "Outcome": outcome
    })
    # Masukkan nol tidak valid secara sengaja agar mekanisme missing-data dapat diuji.
    for col in PIMA_ZERO_AS_MISSING:
        frame.loc[rng.choice(frame.index, size=max(1, n // 70), replace=False), col] = 0
    return frame


def prepare_pima_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Pisahkan fitur dan label; tandai nol yang tak masuk akal sebagai NaN."""
    X = frame[PIMA_COLUMNS[:-1]].copy()
    for col in PIMA_ZERO_AS_MISSING:
        X.loc[X[col].eq(0), col] = np.nan
    y = frame["Outcome"].astype(int).copy()
    return X, y


def create_symptom_eda(frame: pd.DataFrame, report: dict[str, Any], out_dir: Path = OUTPUT_DIR) -> dict[str, pd.DataFrame]:
    """Simpan distribusi kelas, prevalensi gejala, gejala lintas kelas, dan korelasi."""
    out_dir.mkdir(parents=True, exist_ok=True)
    X = frame.drop(columns="prognosis")
    y = frame["prognosis"]
    class_counts = y.value_counts().rename_axis("prognosis").reset_index(name="jumlah")
    feature_prevalence = X.mean().sort_values(ascending=False).rename("proporsi_baris").rename_axis("gejala").reset_index()
    by_disease = frame.groupby("prognosis")[X.columns.tolist()].mean()
    cross_disease = (by_disease.gt(0).sum(axis=0)).sort_values(ascending=False).rename("jumlah_penyakit_dengan_gejala").rename_axis("gejala").reset_index()
    top_cols = feature_prevalence.head(min(20, len(feature_prevalence)))["gejala"].tolist()

    fig, ax = plt.subplots(figsize=(12, 6))
    class_counts.sort_values("jumlah").plot.barh(x="prognosis", y="jumlah", ax=ax, legend=False)
    ax.set_title("Distribusi label penyakit / kelas")
    ax.set_xlabel("Jumlah baris unik")
    fig.tight_layout(); fig.savefig(out_dir / "symptom_class_distribution.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 7))
    feature_prevalence.head(20).sort_values("proporsi_baris").plot.barh(x="gejala", y="proporsi_baris", ax=ax, legend=False)
    ax.set_title("20 gejala paling sering muncul")
    ax.set_xlabel("Proporsi sampel")
    fig.tight_layout(); fig.savefig(out_dir / "symptom_common_features.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 7))
    cross_disease.head(20).sort_values("jumlah_penyakit_dengan_gejala").plot.barh(x="gejala", y="jumlah_penyakit_dengan_gejala", ax=ax, legend=False)
    ax.set_title("Gejala yang muncul pada paling banyak kelas")
    ax.set_xlabel("Jumlah kelas dengan prevalensi > 0")
    fig.tight_layout(); fig.savefig(out_dir / "symptom_cross_class_features.png", dpi=130); plt.close(fig)

    corr = X[top_cols].corr()
    fig, ax = plt.subplots(figsize=(13, 10))
    im = ax.imshow(corr.values, aspect="auto", cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(top_cols))); ax.set_xticklabels(top_cols, rotation=90, fontsize=7)
    ax.set_yticks(range(len(top_cols))); ax.set_yticklabels(top_cols, fontsize=7)
    ax.set_title("Korelasi 20 gejala dengan proporsi tertinggi")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(out_dir / "symptom_feature_correlation.png", dpi=130); plt.close(fig)

    class_counts.to_csv(out_dir / "symptom_class_counts.csv", index=False)
    feature_prevalence.to_csv(out_dir / "symptom_feature_prevalence.csv", index=False)
    cross_disease.to_csv(out_dir / "symptom_cross_class_prevalence.csv", index=False)
    pd.DataFrame([report]).to_json(out_dir / "symptom_data_report.json", orient="records", indent=2, force_ascii=False)
    return {"class_counts": class_counts, "feature_prevalence": feature_prevalence, "cross_disease_prevalence": cross_disease, "correlation": corr}


def create_pima_eda(frame: pd.DataFrame, report: dict[str, Any], out_dir: Path = OUTPUT_DIR) -> None:
    """Simpan ringkasan EDA data numerik skrining."""
    out_dir.mkdir(parents=True, exist_ok=True)
    X, y = prepare_pima_features(frame)
    summary = frame.describe().T
    summary.to_csv(out_dir / "screening_descriptive_statistics.csv")
    X_missing_audit, _ = prepare_pima_features(frame)
    X_missing_audit.isna().sum().rename("missing_after_zero_recode").to_csv(out_dir / "screening_missing_report.csv")
    fig, ax = plt.subplots(figsize=(6, 4))
    y.value_counts().sort_index().plot.bar(ax=ax)
    ax.set_title("Distribusi kelas Outcome")
    ax.set_xlabel("Outcome (0/1)"); ax.set_ylabel("Jumlah")
    fig.tight_layout(); fig.savefig(out_dir / "screening_class_distribution.png", dpi=130); plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 7))
    corr = frame[PIMA_COLUMNS].corr(numeric_only=True)
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(corr.columns))); ax.set_xticklabels(corr.columns, rotation=60, ha="right")
    ax.set_yticks(range(len(corr.columns))); ax.set_yticklabels(corr.columns)
    ax.set_title("Korelasi fitur dataset skrining")
    fig.colorbar(im, ax=ax); fig.tight_layout(); fig.savefig(out_dir / "screening_correlation.png", dpi=130); plt.close(fig)
    X.describe().T.to_csv(out_dir / "screening_feature_summary_after_zero_recode.csv")
    pd.DataFrame([report]).to_json(out_dir / "screening_data_report.json", orient="records", indent=2, force_ascii=False)
