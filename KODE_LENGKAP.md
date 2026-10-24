# Kode Lengkap — Asisten Diagnosis

> Dokumen ini menggabungkan kode sumber proyek untuk dibaca/ditinjau. Untuk menjalankan, gunakan file terpisah di dalam arsip proyek. Model dan metrik bawaan yang disertakan berasal dari DATA DEMO SINTETIS saja, bukan dari dataset medis asli.

## Daftar file
- `config.py`
- `data.py`
- `train_symptom.py`
- `train_screening.py`
- `evaluate.py`
- `explain.py`
- `safety.py`
- `app.py`
- `requirements.txt`
- `config/red_flags.json`
- `config/symptom_mapping_id.json`
- `config/disease_mapping_id.json`
- `config/disease_info.json`
- `tests/conftest.py`
- `tests/test_safety.py`
- `tests/test_symptom_logic.py`
- `tests/test_screening.py`
- `data/README.md`
- `README.md`

---

## `config.py`

```python
"""Konfigurasi terpusat untuk prototipe Asisten Diagnosis."""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
MODEL_DIR = ROOT_DIR / "models"
OUTPUT_DIR = ROOT_DIR / "outputs"

SYMPTOM_MODEL_PATH = MODEL_DIR / "symptom_model.joblib"
SCREENING_MODEL_PATH = MODEL_DIR / "screening_model.joblib"
SYMPTOM_METADATA_PATH = MODEL_DIR / "symptom_metadata.json"
SCREENING_METADATA_PATH = MODEL_DIR / "screening_metadata.json"

RANDOM_STATE = 42
TEST_SIZE = 0.20
MAX_CV_FOLDS = 5

DISCLAIMER = (
    "Aplikasi ini hanya prototipe edukasi/riset dan alat bantu skrining. "
    "Hasil adalah dugaan statistik, bukan diagnosis dokter, bukan alat kesehatan berizin, "
    "dan tidak boleh menjadi satu-satunya dasar keputusan klinis."
)
```

---

## `data.py`

```python
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
```

---

## `train_symptom.py`

```python
"""Training dan evaluasi model diagnosis banding berbasis gejala."""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, brier_score_loss, confusion_matrix, f1_score,
                             precision_recall_fscore_support, top_k_accuracy_score)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict, train_test_split
from sklearn.naive_bayes import BernoulliNB
from sklearn.pipeline import Pipeline

from config import DATA_DIR, MAX_CV_FOLDS, MODEL_DIR, OUTPUT_DIR, RANDOM_STATE, SYMPTOM_METADATA_PATH, SYMPTOM_MODEL_PATH
from data import create_symptom_eda, disease_label, load_symptom_data
from safety import matched_red_flag_columns


def prepare_symptom_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, dict[str, Any]]:
    """Deduplikasi lebih dahulu, singkirkan kelas terlalu kecil, lalu split stratified."""
    # Fungsi load_symptom_data sudah menduplikasi lebih dahulu; fungsi ini defensif untuk pemanggil lain.
    data = frame.drop_duplicates(keep="first").reset_index(drop=True)
    counts = data["prognosis"].value_counts()
    rare = counts[counts < 3]
    dropped_labels = rare.index.astype(str).tolist()
    if dropped_labels:
        data = data[~data["prognosis"].isin(dropped_labels)].copy()
    if data["prognosis"].nunique() < 2:
        raise ValueError("Setelah deduplikasi/filter kelas langka, tersisa kurang dari dua kelas.")
    counts = data["prognosis"].value_counts()
    n_classes = int(data["prognosis"].nunique())
    test_n = max(int(np.ceil(0.20 * len(data))), n_classes)
    if test_n >= len(data) - n_classes:
        raise ValueError("Data terlalu sedikit untuk split stratified train/test yang layak.")
    X = data.drop(columns="prognosis")
    y = data["prognosis"].astype(str)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_n, random_state=RANDOM_STATE, stratify=y
    )
    # Jamin tidak ada baris fitur + label identik menyeberang train/test.
    train_rows = set(pd.concat([X_train.reset_index(drop=True), y_train.reset_index(drop=True).rename("prognosis")], axis=1).astype(str).agg("|".join, axis=1))
    test_rows = set(pd.concat([X_test.reset_index(drop=True), y_test.reset_index(drop=True).rename("prognosis")], axis=1).astype(str).agg("|".join, axis=1))
    overlap = train_rows.intersection(test_rows)
    if overlap:
        raise AssertionError(f"Ditemukan {len(overlap)} baris identik lintas train/test.")
    report = {
        "rows_after_deduplication_before_rare_class_filter": int(len(frame.drop_duplicates())),
        "rows_used": int(len(data)), "train_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        "classes_used": int(y.nunique()), "dropped_classes_less_than_3_rows": dropped_labels,
        "cross_split_exact_row_overlap": len(overlap),
        "minimum_train_class_count": int(y_train.value_counts().min()),
    }
    return X_train, X_test, y_train, y_test, report


def _candidate_models() -> list[tuple[str, Any, dict[str, list[Any]]]]:
    """Daftar baseline dan model dengan grid tuning yang sengaja ringkas."""
    return [
        ("DummyClassifier", DummyClassifier(strategy="most_frequent"), {}),
        ("BernoulliNB", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("clf", BernoulliNB())]),
         {"clf__alpha": [0.5, 1.0, 2.0]}),
        ("LogisticRegression", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                                          ("clf", LogisticRegression(max_iter=1800, class_weight="balanced", random_state=RANDOM_STATE))]),
         {"clf__C": [0.1, 1.0, 5.0]}),
        ("RandomForest", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                                    ("clf", RandomForestClassifier(class_weight="balanced_subsample", random_state=RANDOM_STATE, n_jobs=-1))]),
         {"clf__n_estimators": [100, 180], "clf__max_features": ["sqrt", 0.5], "clf__min_samples_leaf": [1, 2]}),
        ("GradientBoosting", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")),
                                        ("clf", GradientBoostingClassifier(random_state=RANDOM_STATE))]),
         {"clf__n_estimators": [50, 80], "clf__learning_rate": [0.05, 0.1], "clf__max_depth": [1, 2]}),
    ]


def _metric_row(name: str, y_true: pd.Series, predicted: np.ndarray, probabilities: np.ndarray,
                classes: np.ndarray, cv_macro_f1: float | None = None, cv_accuracy: float | None = None) -> dict[str, Any]:
    """Hitung metrik multiclass, termasuk top-3 dan Brier multi-class."""
    topk = min(3, probabilities.shape[1])
    try:
        top3 = top_k_accuracy_score(y_true, probabilities, k=topk, labels=classes)
    except Exception:
        order = np.argsort(probabilities, axis=1)[:, ::-1][:, :topk]
        top3 = float(np.mean([str(y_true.iloc[i]) in classes[order[i]] for i in range(len(y_true))]))
    class_index = {str(label): i for i, label in enumerate(classes)}
    onehot = np.zeros_like(probabilities, dtype=float)
    for i, label in enumerate(y_true.astype(str)):
        if label in class_index:
            onehot[i, class_index[label]] = 1.0
    return {
        "model": name, "cv_accuracy": cv_accuracy, "cv_macro_f1": cv_macro_f1,
        "test_accuracy_top1": float(accuracy_score(y_true, predicted)),
        "test_macro_f1": float(f1_score(y_true, predicted, average="macro", zero_division=0)),
        "test_top3_accuracy": float(top3),
        "test_multiclass_brier": float(np.mean(np.sum((probabilities - onehot) ** 2, axis=1))),
    }


def _top_confusions(cm: np.ndarray, classes: np.ndarray, n: int = 10) -> pd.DataFrame:
    """Cari pasangan kelas yang paling sering tertukar dari confusion matrix."""
    rows = []
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            if i != j and cm[i, j] > 0:
                rows.append({"label_asli": str(classes[i]), "diprediksi_sebagai": str(classes[j]), "jumlah": int(cm[i, j])})
    return pd.DataFrame(rows).sort_values("jumlah", ascending=False).head(n) if rows else pd.DataFrame(columns=["label_asli", "diprediksi_sebagai", "jumlah"])


def _robustness_tests(model: Any, X_test: pd.DataFrame, y_test: pd.Series, seed: int = RANDOM_STATE) -> pd.DataFrame:
    """Uji ketahanan saat fitur dihapus, ditambah positif palsu, atau tinggal 1-3 gejala."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    feature_names = list(X_test.columns)
    y_arr = y_test.astype(str).to_numpy()

    def add_result(name: str, X_mod: pd.DataFrame) -> None:
        probs = model.predict_proba(X_mod[feature_names])
        predicted = model.classes_[np.argmax(probs, axis=1)]
        order = np.argsort(probs, axis=1)[:, ::-1][:, :min(3, probs.shape[1])]
        top3 = float(np.mean([y_arr[i] in model.classes_[order[i]] for i in range(len(y_arr))]))
        rows.append({"scenario": name, "top1_accuracy": float(accuracy_score(y_arr, predicted)), "top3_accuracy": top3})

    base_probs = model.predict_proba(X_test[feature_names])
    base_pred = model.classes_[np.argmax(base_probs, axis=1)]
    base_order = np.argsort(base_probs, axis=1)[:, ::-1][:, :min(3, base_probs.shape[1])]
    base_top3 = float(np.mean([y_arr[i] in model.classes_[base_order[i]] for i in range(len(y_arr))]))
    rows.append({"scenario": "Baseline (tanpa gangguan)", "top1_accuracy": float(accuracy_score(y_arr, base_pred)), "top3_accuracy": base_top3})

    for fraction in (0.20, 0.35, 0.50):
        repetitions = []
        for rep in range(3):
            X_mod = X_test.copy()
            n_drop = max(1, int(round(len(feature_names) * fraction)))
            drop_cols = rng.choice(feature_names, size=min(n_drop, len(feature_names)), replace=False)
            X_mod.loc[:, drop_cols] = 0
            probabilities = model.predict_proba(X_mod[feature_names])
            predicted = model.classes_[np.argmax(probabilities, axis=1)]
            order = np.argsort(probabilities, axis=1)[:, ::-1][:, :min(3, probabilities.shape[1])]
            top3 = float(np.mean([y_arr[i] in model.classes_[order[i]] for i in range(len(y_arr))]))
            repetitions.append((accuracy_score(y_arr, predicted), top3))
        rows.append({"scenario": f"Hapus {int(fraction*100)}% fitur acak (rerata 3 ulangan)",
                     "top1_accuracy": float(np.mean([x[0] for x in repetitions])),
                     "top3_accuracy": float(np.mean([x[1] for x in repetitions]))})

    # Tambah 1-3 gejala positif palsu pada tiap baris, hanya pada fitur yang awalnya 0.
    X_noise = X_test.copy()
    for idx in X_noise.index:
        zeros = [c for c in feature_names if int(X_noise.at[idx, c]) == 0]
        if zeros:
            k = min(len(zeros), int(rng.integers(1, 4)))
            selected = rng.choice(zeros, size=k, replace=False)
            X_noise.loc[idx, selected] = 1
    add_result("Tambah 1-3 gejala acak", X_noise)

    # Pertahankan 1-3 gejala positif yang tersedia per baris; bila kosong, baris menjadi semua nol.
    for keep_n in (1, 2, 3):
        X_sparse = X_test.copy()
        for idx in X_sparse.index:
            present = [c for c in feature_names if int(X_sparse.at[idx, c]) == 1]
            X_sparse.loc[idx, :] = 0
            if present:
                keep = rng.choice(present, size=min(keep_n, len(present)), replace=False)
                X_sparse.loc[idx, keep] = 1
        add_result(f"Hanya {keep_n} gejala positif per baris", X_sparse)
    return pd.DataFrame(rows)


def main() -> None:
    """Jalankan pipeline training lengkap untuk Modul A."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True); OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frame, data_report = load_symptom_data()
    eda = create_symptom_eda(frame, data_report)
    X_train, X_test, y_train, y_test, split_report = prepare_symptom_split(frame)
    min_count = int(y_train.value_counts().min())
    folds = min(MAX_CV_FOLDS, min_count)
    if folds < 2:
        raise ValueError("Data train memiliki kelas dengan kurang dari dua sampel; stratified CV tidak mungkin dilakukan.")
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_STATE)
    model_results: list[dict[str, Any]] = []
    tuned_models: dict[str, Any] = {}
    fitted_models: dict[str, Any] = {}
    warnings_list: list[str] = []
    classes = np.unique(y_train.astype(str))

    for name, estimator, grid in _candidate_models():
        print(f"[Modul A] Memproses {name} ...", flush=True)
        if grid:
            search = GridSearchCV(estimator, grid, cv=cv, scoring="f1_macro", refit=True, n_jobs=-1, error_score="raise")
            search.fit(X_train, y_train)
            best = search.best_estimator_
            cv_f1 = float(search.best_score_)
            cv_acc_scores = []
            # CV accuracy direkonstruksi dari konfigurasi terbaik untuk perbandingan yang konsisten.
            from sklearn.model_selection import cross_val_score
            cv_acc_scores = cross_val_score(best, X_train, y_train, cv=cv, scoring="accuracy", n_jobs=-1)
            cv_acc = float(np.mean(cv_acc_scores))
            tuned_models[name] = {"best_params": search.best_params_, "best_cv_macro_f1": cv_f1}
        else:
            best = clone(estimator)
            from sklearn.model_selection import cross_val_score
            cv_f1 = float(np.mean(cross_val_score(best, X_train, y_train, cv=cv, scoring="f1_macro", n_jobs=-1)))
            cv_acc = float(np.mean(cross_val_score(best, X_train, y_train, cv=cv, scoring="accuracy", n_jobs=-1)))
            best.fit(X_train, y_train)
            tuned_models[name] = {"best_params": "baseline tanpa tuning", "best_cv_macro_f1": cv_f1}
        # Fit untuk perbandingan test, serta probabilitas multiclass.
        if not hasattr(best, "classes_"):
            best.fit(X_train, y_train)
        probs = best.predict_proba(X_test)
        predicted = best.classes_[np.argmax(probs, axis=1)]
        metrics = _metric_row(name, y_test, predicted, probs, best.classes_, cv_f1, cv_acc)
        model_results.append(metrics)
        fitted_models[name] = best

    results = pd.DataFrame(model_results).sort_values(["cv_macro_f1", "cv_accuracy"], ascending=False)
    results.to_csv(OUTPUT_DIR / "symptom_model_comparison.csv", index=False)
    # DummyClassifier hanya baseline: tidak boleh menjadi model deployment bila model lain tersedia.
    selectable = results[results["model"] != "DummyClassifier"]
    selected_name = str(selectable.sort_values(["cv_macro_f1", "cv_accuracy"], ascending=False).iloc[0]["model"])
    selected_raw = fitted_models[selected_name]
    # Ambang keyakinan empiris diturunkan dari probabilitas maksimum out-of-fold terkalibrasi.
    # Kalibrator pada tiap outer fold hanya melihat bagian train fold, bukan label baris validasi.
    calibration_status = "CalibratedClassifierCV sigmoid; threshold dari OOF kalibrasi bertingkat"
    try:
        nested_calibrator = CalibratedClassifierCV(estimator=clone(selected_raw), method="sigmoid", cv=cv, n_jobs=-1)
        oof_probs = cross_val_predict(nested_calibrator, X_train, y_train, cv=cv, method="predict_proba", n_jobs=-1)
        oof_max = oof_probs.max(axis=1)
        confidence_threshold = float(np.quantile(oof_max, 0.10))
        calibrated = CalibratedClassifierCV(estimator=clone(selected_raw), method="sigmoid", cv=cv, n_jobs=-1)
        calibrated.fit(X_train, y_train)
        model = calibrated
    except Exception as exc:
        warnings.warn(f"Kalibrasi bertingkat tidak stabil/gagal; menggunakan OOF model mentah: {exc}")
        oof_probs = cross_val_predict(clone(selected_raw), X_train, y_train, cv=cv, method="predict_proba", n_jobs=-1)
        oof_max = oof_probs.max(axis=1)
        confidence_threshold = float(np.quantile(oof_max, 0.10))
        try:
            calibrated = CalibratedClassifierCV(estimator=clone(selected_raw), method="sigmoid", cv=cv, n_jobs=-1)
            calibrated.fit(X_train, y_train)
            model = calibrated
        except Exception as exc2:
            warnings.warn(f"Kalibrasi gagal; memakai model mentah: {exc2}")
            model = clone(selected_raw).fit(X_train, y_train)
            calibration_status = f"GAGAL; model mentah digunakan: {exc2}"
        warnings_list.append(calibration_status)
    confidence_threshold = min(max(confidence_threshold, 0.0), 1.0)

    test_probs = model.predict_proba(X_test)
    model_classes = np.asarray(model.classes_)
    predicted = model_classes[np.argmax(test_probs, axis=1)]
    # Metrik kalibrasi model akhir dihitung pada test holdout dan tidak dipakai untuk tuning.
    final_metrics = _metric_row(selected_name + " (kalibrasi untuk aplikasi)", y_test, predicted, test_probs, model_classes)
    pd.DataFrame([final_metrics]).to_csv(OUTPUT_DIR / "symptom_selected_model_test_metrics.csv", index=False)
    cm = confusion_matrix(y_test, predicted, labels=model_classes)
    cm_df = pd.DataFrame(cm, index=model_classes, columns=model_classes)
    cm_df.to_csv(OUTPUT_DIR / "symptom_confusion_matrix.csv")
    fig, ax = plt.subplots(figsize=(max(8, len(model_classes)*0.28), max(7, len(model_classes)*0.25)))
    im = ax.imshow(cm, cmap="Blues", aspect="auto")
    ax.set_title(f"Confusion matrix — {selected_name}")
    ax.set_xlabel("Prediksi"); ax.set_ylabel("Label aktual")
    if len(model_classes) <= 20:
        ax.set_xticks(range(len(model_classes))); ax.set_xticklabels(model_classes, rotation=90, fontsize=7)
        ax.set_yticks(range(len(model_classes))); ax.set_yticklabels(model_classes, fontsize=7)
    fig.colorbar(im, ax=ax); fig.tight_layout(); fig.savefig(OUTPUT_DIR / "symptom_confusion_matrix.png", dpi=130); plt.close(fig)
    _top_confusions(cm, model_classes).to_csv(OUTPUT_DIR / "symptom_top_confusions.csv", index=False)

    # Recall per kelas untuk audit performa multikelas.
    _, recalls, _, support = precision_recall_fscore_support(y_test, predicted, labels=model_classes, zero_division=0)
    pd.DataFrame({"prognosis": model_classes, "recall": recalls, "support_test": support}).to_csv(OUTPUT_DIR / "symptom_recall_per_disease.csv", index=False)

    # Grafik reliabilitas berbasis confidence top-1: fraction correct per bin confidence.
    confidence = test_probs.max(axis=1)
    correct = (predicted.astype(str) == y_test.astype(str).to_numpy()).astype(int)
    bins = np.linspace(0, 1, 11)
    bin_idx = np.digitize(confidence, bins[1:-1], right=True)
    calibration_rows = []
    for b in range(10):
        sel = bin_idx == b
        if sel.any():
            calibration_rows.append({"bin": b, "count": int(sel.sum()), "mean_confidence": float(confidence[sel].mean()), "accuracy": float(correct[sel].mean())})
    calibration_df = pd.DataFrame(calibration_rows)
    calibration_df.to_csv(OUTPUT_DIR / "symptom_reliability_bins.csv", index=False)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", label="Kalibrasi ideal")
    if not calibration_df.empty:
        ax.plot(calibration_df["mean_confidence"], calibration_df["accuracy"], marker="o", label="Model")
    ax.set_xlabel("Rata-rata probabilitas tertinggi"); ax.set_ylabel("Akurasi top-1 bin")
    ax.set_title("Kurva reliabilitas top-1"); ax.legend(); fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "symptom_calibration_curve.png", dpi=130); plt.close(fig)

    # Permutation importance global pada test set; model multiclass dinilai dengan macro-F1.
    from sklearn.inspection import permutation_importance
    print("[Modul A] Menghitung permutation importance ...", flush=True)
    perm = permutation_importance(model, X_test, y_test, scoring="f1_macro", n_repeats=2, random_state=RANDOM_STATE, n_jobs=-1)
    importance = pd.DataFrame({"gejala": X_test.columns, "importance_mean": perm.importances_mean, "importance_std": perm.importances_std})
    importance.sort_values("importance_mean", ascending=False).to_csv(OUTPUT_DIR / "symptom_permutation_importance.csv", index=False)
    top_imp = importance.sort_values("importance_mean", ascending=True).tail(20)
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.barh(top_imp["gejala"], top_imp["importance_mean"], xerr=top_imp["importance_std"])
    ax.set_title("Permutation importance global (macro-F1)"); ax.set_xlabel("Penurunan macro-F1 setelah pengacakan")
    fig.tight_layout(); fig.savefig(OUTPUT_DIR / "symptom_permutation_importance.png", dpi=130); plt.close(fig)

    robustness = _robustness_tests(model, X_test, y_test)
    robustness.to_csv(OUTPUT_DIR / "symptom_robustness_tests.csv", index=False)
    # Uji sanity pada Testing.csv opsional, sama sekali tidak dipakai untuk pemilihan model.
    test_file = None
    if (DATA_DIR / "Testing.csv").exists():
        test_file = DATA_DIR / "Testing.csv"
    elif (DATA_DIR / "testing.csv").exists():
        test_file = DATA_DIR / "testing.csv"
    sanity_report: dict[str, Any] = {"used_for_model_selection": False, "status": "Testing.csv tidak ditemukan; sanity check dilewati."}
    if test_file:
        try:
            raw_testing = pd.read_csv(test_file)
            test_clean, test_report = __import__("data").clean_symptom_dataframe(raw_testing)
            common = [c for c in X_train.columns if c in test_clean.columns]
            if "prognosis" in test_clean and len(common) == len(X_train.columns):
                X_external = test_clean[X_train.columns]
                y_external = test_clean["prognosis"].astype(str)
                known = y_external.isin(model_classes)
                if known.any():
                    p_ext = model.predict_proba(X_external.loc[known])
                    y_hat = model.classes_[np.argmax(p_ext, axis=1)]
                    sanity_report = {"used_for_model_selection": False, "status": "HANYA sanity check; bukan evaluasi utama",
                                     "rows": int(known.sum()), "top1_accuracy_sanity_only": float(accuracy_score(y_external.loc[known], y_hat)),
                                     "source_report": test_report}
                else:
                    sanity_report = {"used_for_model_selection": False, "status": "Tidak ada label pada Testing.csv yang cocok dengan kelas train."}
        except Exception as exc:
            sanity_report = {"used_for_model_selection": False, "status": f"Sanity check gagal, tidak dipakai untuk evaluasi: {exc}"}

    report = {
        "model": selected_name, "model_path": str(SYMPTOM_MODEL_PATH), "dataset": data_report,
        "split": split_report, "cv_folds": folds, "cv_policy": f"Stratified {folds}-fold; diturunkan dari jumlah minimum kelas train",
        "model_search": tuned_models, "selected_test_metrics": final_metrics,
        "confidence_threshold": confidence_threshold,
        "threshold_rule": "Kuantil 10% maksimum probabilitas top-1 terkalibrasi dari prediksi out-of-fold bertingkat pada training; bukan ambang klinis.",
        "calibration": calibration_status,
        "calibration_note": "Brier multi-class dihitung pada holdout; kurva reliabilitas top-1 bersifat deskriptif. Data kecil/bersih dapat membuat kalibrasi tidak stabil.",
        "robustness_note": "Uji ketahanan pada test holdout yang sama; semua gangguan bersifat sintetis dan tidak mensimulasikan missingness klinis yang tervalidasi.",
        "robustness_scenarios": robustness.to_dict(orient="records"),
        "sanity_check_testing_csv": sanity_report,
        "feature_count": len(X_train.columns), "classes": [str(x) for x in model.classes_],
        "feature_names": list(X_train.columns), "training_data_medians": X_train.median().to_dict(),
        "red_flag_column_map": matched_red_flag_columns(X_train.columns),
        "warnings": warnings_list, "is_demo": bool(data_report.get("is_demo", False)),
        "trained_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": __import__("sys").version,
        "scikit_learn_version": sklearn.__version__, "numpy_version": np.__version__, "pandas_version": pd.__version__,
    }
    # Bundle menyertakan statistik training saja, bukan data input pasien.
    bundle = {"model": model, "feature_names": list(X_train.columns), "classes": [str(x) for x in model.classes_],
              "X_train": X_train.copy(), "y_train": y_train.copy(), "confidence_threshold": confidence_threshold,
              "is_demo": bool(data_report.get("is_demo", False)), "model_name": selected_name}
    joblib.dump(bundle, SYMPTOM_MODEL_PATH)
    SYMPTOM_METADATA_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\nHASIL MODUL A")
    print(results.to_string(index=False))
    print(f"Model aplikasi: {selected_name}; threshold empiris={confidence_threshold:.4f}; data_demo={data_report.get('is_demo', False)}")
    print(f"Metrik dan grafik tersimpan di {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
```

---

## `train_screening.py`

```python
"""Training dan evaluasi model skrining numerik diabetes."""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from typing import Any

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from config import MAX_CV_FOLDS, MODEL_DIR, OUTPUT_DIR, RANDOM_STATE, SCREENING_METADATA_PATH, SCREENING_MODEL_PATH
from data import create_pima_eda, load_pima_local_or_remote, prepare_pima_features


def calculate_binary_metrics(y_true: np.ndarray, y_pred: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    """Hitung metrik binary, termasuk specificity dan ROC-AUC."""
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = (int(x) for x in cm.ravel())
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall_sensitivity": float(recall_score(y_true, y_pred, zero_division=0)),
        "specificity": float(specificity),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)) if len(np.unique(y_true)) == 2 else float("nan"),
        "threshold": float(threshold), "tn": tn, "fp": fp, "fn": fn, "tp": tp,
    }


def choose_recall_threshold(y_true: np.ndarray, probabilities: np.ndarray, target_recall: float = 0.80) -> tuple[float, dict[str, Any]]:
    """Pilih threshold dengan precision terbaik di antara kandidat yang mencapai recall sasaran."""
    candidates = np.unique(np.concatenate(([0.0, 0.5, 1.0], probabilities.ravel())))
    records = []
    for threshold in candidates:
        pred = (probabilities >= threshold).astype(int)
        recall = float(recall_score(y_true, pred, zero_division=0))
        precision = float(precision_score(y_true, pred, zero_division=0))
        specificity = float(((y_true == 0) & (pred == 0)).sum() / max(1, (y_true == 0).sum()))
        records.append((float(threshold), precision, recall, specificity))
    eligible = [r for r in records if r[2] >= target_recall]
    if eligible:
        chosen = sorted(eligible, key=lambda r: (r[1], r[3], -r[0]), reverse=True)[0]
        rule = f"Precision tertinggi dengan recall OOF >= {target_recall:.0%}"
    else:
        chosen = sorted(records, key=lambda r: (r[2], r[1], r[3]), reverse=True)[0]
        rule = "Target recall tidak tercapai; pilih recall tertinggi lalu precision sebagai pemecah seri"
    return chosen[0], {"rule": rule, "oof_precision": chosen[1], "oof_recall": chosen[2], "oof_specificity": chosen[3], "target_recall": target_recall}


def _candidates() -> list[tuple[str, Any, dict[str, list[Any]], bool]]:
    """Model, grid tuning, dan penanda apakah memakai sample weight."""
    return [
        ("LogisticRegression", Pipeline([("imputer", SimpleImputer(strategy="median")),
                                         ("scaler", StandardScaler()),
                                         ("clf", LogisticRegression(max_iter=2500, class_weight="balanced", random_state=RANDOM_STATE))]),
         {"clf__C": [0.1, 1.0, 5.0]}, False),
        ("RandomForest", Pipeline([("imputer", SimpleImputer(strategy="median")),
                                   ("clf", RandomForestClassifier(class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1))]),
         {"clf__n_estimators": [120, 220], "clf__max_depth": [None, 8], "clf__min_samples_leaf": [1, 3]}, False),
        ("GradientBoosting", Pipeline([("imputer", SimpleImputer(strategy="median")),
                                        ("scaler", StandardScaler()),
                                        ("clf", GradientBoostingClassifier(random_state=RANDOM_STATE))]),
         {"clf__n_estimators": [50, 100], "clf__learning_rate": [0.05, 0.1], "clf__max_depth": [1, 2]}, True),
    ]


def main() -> None:
    """Latih dan evaluasi modul B, simpan model, metadata, serta grafik."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True); OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frame, data_report = load_pima_local_or_remote()
    create_pima_eda(frame, data_report)
    X, y = prepare_pima_features(frame)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=RANDOM_STATE, stratify=y
    )
    folds = min(MAX_CV_FOLDS, int(y_train.value_counts().min()))
    if folds < 2:
        raise ValueError("Jumlah kasus pada salah satu kelas terlalu sedikit untuk CV stratified.")
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_STATE)
    comparison_rows: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}
    cv_probs_by_model: dict[str, np.ndarray] = {}

    for name, estimator, param_grid, uses_sample_weight in _candidates():
        print(f"[Modul B] Memproses {name} ...", flush=True)
        search = GridSearchCV(estimator, param_grid, cv=cv, scoring="recall", refit=True, n_jobs=-1, error_score="raise")
        fit_kwargs: dict[str, Any] = {}
        if uses_sample_weight:
            # GradientBoostingClassifier tidak memiliki class_weight; bobot kelas diseimbangkan secara eksplisit.
            weights = compute_sample_weight(class_weight="balanced", y=y_train)
            fit_kwargs["clf__sample_weight"] = weights
        search.fit(X_train, y_train, **fit_kwargs)
        best = search.best_estimator_
        from sklearn.model_selection import cross_val_score
        cv_recall = float(np.mean(cross_val_score(best, X_train, y_train, cv=cv, scoring="recall", n_jobs=-1)))
        cv_auc = float(np.mean(cross_val_score(best, X_train, y_train, cv=cv, scoring="roc_auc", n_jobs=-1)))
        # OOF probabilitas untuk memilih threshold hanya dari bagian train.
        oof_prob = cross_val_predict(best, X_train, y_train, cv=cv, method="predict_proba", n_jobs=-1)[:, 1]
        threshold, threshold_info = choose_recall_threshold(y_train.to_numpy(), oof_prob)
        test_prob = best.predict_proba(X_test)[:, 1]
        pred = (test_prob >= threshold).astype(int)
        metrics = calculate_binary_metrics(y_test.to_numpy(), pred, test_prob, threshold)
        metrics.update({"model": name, "cv_recall_at_default_0_5": cv_recall, "cv_roc_auc": cv_auc,
                        "oof_recall_at_selected_threshold": threshold_info["oof_recall"],
                        "oof_precision_at_selected_threshold": threshold_info["oof_precision"],
                        "best_params": json.dumps(search.best_params_)})
        comparison_rows.append(metrics)
        candidates[name] = {"estimator": best, "threshold": threshold, "threshold_info": threshold_info,
                            "cv_recall": cv_recall, "cv_roc_auc": cv_auc, "best_params": search.best_params_}
        cv_probs_by_model[name] = oof_prob

    comparison = pd.DataFrame(comparison_rows).sort_values(
        ["oof_recall_at_selected_threshold", "oof_precision_at_selected_threshold", "cv_roc_auc"],
        ascending=False
    )
    comparison.to_csv(OUTPUT_DIR / "screening_model_comparison.csv", index=False)
    selected_name = str(comparison.iloc[0]["model"])
    selected = candidates[selected_name]
    raw_model = selected["estimator"]
    threshold = float(selected["threshold"])
    threshold_info = selected["threshold_info"]

    # Hasil OOF terkalibrasi dihitung di dalam train; digunakan untuk threshold dan kategori.
    # Nested CV membuat kalibrator tidak melihat label pada baris yang sedang diprediksi.
    calibration_status = "CalibratedClassifierCV sigmoid; threshold/kategori dari OOF kalibrasi bertingkat"
    try:
        nested_calibrator = CalibratedClassifierCV(estimator=raw_model, method="sigmoid", cv=cv, n_jobs=-1)
        calibrated_oof = cross_val_predict(nested_calibrator, X_train, y_train, cv=cv, method="predict_proba", n_jobs=-1)[:, 1]
        threshold, threshold_info = choose_recall_threshold(y_train.to_numpy(), calibrated_oof)
        calibrated = CalibratedClassifierCV(estimator=raw_model, method="sigmoid", cv=cv, n_jobs=-1)
        calibrated.fit(X_train, y_train)
        model = calibrated
        selected_oof = calibrated_oof
    except Exception as exc:
        warnings.warn(f"Kalibrasi bertingkat gagal; fallback ke threshold OOF model mentah: {exc}")
        selected_oof = cv_probs_by_model[selected_name]
        threshold, threshold_info = choose_recall_threshold(y_train.to_numpy(), selected_oof)
        try:
            calibrated = CalibratedClassifierCV(estimator=raw_model, method="sigmoid", cv=cv, n_jobs=-1)
            calibrated.fit(X_train, y_train)
            model = calibrated
        except Exception as exc2:
            warnings.warn(f"Kalibrasi gagal; memakai model tanpa kalibrasi: {exc2}")
            model = raw_model
            calibration_status = f"GAGAL; model mentah digunakan: {exc2}"

    # Tetapkan kategori risiko berdasarkan tertil probabilitas OOF terkalibrasi pada training.
    low_cut, high_cut = [float(x) for x in np.quantile(selected_oof, [1/3, 2/3])]
    if high_cut <= low_cut:
        high_cut = min(1.0, low_cut + 0.05)
    test_prob = model.predict_proba(X_test)[:, 1]
    test_pred = (test_prob >= threshold).astype(int)
    metrics_final = calculate_binary_metrics(y_test.to_numpy(), test_pred, test_prob, threshold)
    metrics_final.update({"model": selected_name, "cv_recall_at_default_0_5": selected["cv_recall"], "cv_roc_auc": selected["cv_roc_auc"]})
    pd.DataFrame([metrics_final]).to_csv(OUTPUT_DIR / "screening_selected_test_metrics.csv", index=False)
    cm = confusion_matrix(y_test, test_pred, labels=[0, 1])
    pd.DataFrame(cm, index=["Aktual negatif", "Aktual positif"], columns=["Prediksi negatif", "Prediksi positif"]).to_csv(OUTPUT_DIR / "screening_confusion_matrix.csv")
    fig, ax = plt.subplots(figsize=(5, 4)); im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Negatif", "Positif"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["Negatif", "Positif"])
    ax.set_xlabel("Prediksi"); ax.set_ylabel("Aktual"); ax.set_title("Confusion matrix — skrining")
    for i in range(2):
        for j in range(2): ax.text(j, i, str(cm[i, j]), ha="center", va="center")
    fig.colorbar(im, ax=ax); fig.tight_layout(); fig.savefig(OUTPUT_DIR / "screening_confusion_matrix.png", dpi=130); plt.close(fig)
    fpr, tpr, roc_thresholds = roc_curve(y_test, test_prob)
    fig, ax = plt.subplots(figsize=(6, 5)); ax.plot(fpr, tpr, label=f"{selected_name} (AUC={metrics_final['roc_auc']:.3f})")
    ax.plot([0, 1], [0, 1], linestyle="--"); ax.set_xlabel("False Positive Rate"); ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC curve — skrining diabetes"); ax.legend(); fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "screening_roc_curve.png", dpi=130); plt.close(fig)

    print("[Modul B] Menghitung permutation importance ...", flush=True)
    perm = permutation_importance(model, X_test, y_test, scoring="roc_auc", n_repeats=5, random_state=RANDOM_STATE, n_jobs=-1)
    importance = pd.DataFrame({"feature": X_test.columns, "importance_mean": perm.importances_mean, "importance_std": perm.importances_std})
    importance.sort_values("importance_mean", ascending=False).to_csv(OUTPUT_DIR / "screening_permutation_importance.csv", index=False)
    plot = importance.sort_values("importance_mean").tail(8)
    fig, ax = plt.subplots(figsize=(8, 5)); ax.barh(plot["feature"], plot["importance_mean"], xerr=plot["importance_std"])
    ax.set_xlabel("Penurunan ROC-AUC saat fitur diacak"); ax.set_title("Permutation importance — skrining")
    fig.tight_layout(); fig.savefig(OUTPUT_DIR / "screening_permutation_importance.png", dpi=130); plt.close(fig)

    # Reliabilitas sederhana pada probabilitas test; test hanya untuk evaluasi.
    bins = np.linspace(0, 1, 11); bin_idx = np.digitize(test_prob, bins[1:-1], right=True)
    reliability = []
    for bin_number in range(10):
        sel_mask = bin_idx == bin_number
        if sel_mask.any():
            reliability.append({"bin": bin_number, "count": int(sel_mask.sum()), "mean_probability": float(test_prob[sel_mask].mean()),
                                "observed_positive_rate": float(y_test.to_numpy()[sel_mask].mean())})
    reliability_df = pd.DataFrame(reliability)
    reliability_df.to_csv(OUTPUT_DIR / "screening_reliability_bins.csv", index=False)
    fig, ax = plt.subplots(figsize=(6, 6)); ax.plot([0, 1], [0, 1], linestyle="--", label="Ideal")
    if not reliability_df.empty: ax.plot(reliability_df["mean_probability"], reliability_df["observed_positive_rate"], marker="o", label="Model")
    ax.set_xlabel("Rata-rata probabilitas"); ax.set_ylabel("Proporsi positif teramati"); ax.set_title("Kurva reliabilitas skrining"); ax.legend()
    fig.tight_layout(); fig.savefig(OUTPUT_DIR / "screening_calibration_curve.png", dpi=130); plt.close(fig)

    # Median training disimpan sebagai referensi penjelasan, bukan input pasien.
    medians = X_train.median(numeric_only=True).to_dict()
    bundle = {"model": model, "feature_names": list(X_train.columns), "threshold": threshold,
              "category_low_cut": low_cut, "category_high_cut": high_cut, "reference_medians": medians,
              "is_demo": bool(data_report.get("is_demo", False)), "model_name": selected_name}
    joblib.dump(bundle, SCREENING_MODEL_PATH)
    metadata = {
        "model": selected_name, "data": data_report, "train_rows": len(X_train), "test_rows": len(X_test),
        "cv_folds": folds, "best_params": selected["best_params"], "cv_recall_at_default_0_5": selected["cv_recall"],
        "cv_roc_auc": selected["cv_roc_auc"], "test_metrics": metrics_final,
        "threshold": threshold, "threshold_selection": threshold_info,
        "category_thresholds": {"rendah_batas_atas": low_cut, "sedang_batas_atas": high_cut,
                                 "method": "Tertil probabilitas OOF pada training; bukan batas klinis."},
        "calibration": calibration_status,
        "calibration_note": "Probabilitas dan kalibrasi dievaluasi pada holdout; validasi klinis/populasi lokal tetap diperlukan.",
        "class_weight_note": "Logistic Regression dan Random Forest menggunakan class_weight='balanced'; GradientBoosting memakai sample_weight seimbang karena tidak memiliki parameter class_weight yang sama.",
        "feature_names": list(X_train.columns), "training_medians": medians,
        "is_demo": bool(data_report.get("is_demo", False)), "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": __import__("sys").version, "scikit_learn_version": sklearn.__version__,
        "numpy_version": np.__version__, "pandas_version": pd.__version__,
    }
    SCREENING_METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\nHASIL MODUL B")
    print(comparison.to_string(index=False))
    print(f"Model terpilih={selected_name}, threshold={threshold:.3f}, data_demo={data_report.get('is_demo', False)}")
    print(f"Metrik dan grafik tersimpan di {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
```

---

## `evaluate.py`

```python
"""Ringkasan evaluasi untuk kedua modul dari file keluaran training."""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from config import OUTPUT_DIR


def main() -> None:
    """Tampilkan tabel perbandingan dan mengingatkan bila data adalah demo."""
    for filename, title in [
        ("symptom_model_comparison.csv", "Modul A — Diagnosis gejala"),
        ("screening_model_comparison.csv", "Modul B — Skrining diabetes"),
    ]:
        path = OUTPUT_DIR / filename
        print(f"\n{title}")
        if path.exists():
            print(pd.read_csv(path).to_string(index=False))
        else:
            print(f"Belum ada hasil. Jalankan training yang sesuai; file belum ditemukan: {path}")
    for report in ["symptom_data_report.json", "screening_data_report.json"]:
        path = OUTPUT_DIR / report
        if path.exists():
            data = pd.read_json(path).iloc[0].to_dict()
            if bool(data.get("is_demo", False)) or str(data.get("dataset_mode", "")).startswith("DATA DEMO"):
                print(f"PERINGATAN: {report} menggunakan DATA DEMO sintetis. Metrik tidak mempunyai makna kinerja klinis.")


if __name__ == "__main__":
    main()
```

---

## `explain.py`

```python
"""Penjelasan model, pertanyaan lanjutan, dan faktor yang memengaruhi prediksi."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import mutual_info_score

from data import disease_label, symptom_label, load_disease_mapping, load_symptom_mapping


def ordered_topk(probabilities: Iterable[float], classes: Iterable[str], k: int = 3) -> list[dict[str, Any]]:
    """Urutkan probabilitas dari terbesar dan kembalikan sampai k kandidat."""
    probs = np.asarray(list(probabilities), dtype=float).ravel()
    labels = np.asarray(list(classes), dtype=object).ravel()
    if probs.size != labels.size or probs.size == 0:
        return []
    probs = np.clip(probs, 0.0, None)
    total = probs.sum()
    if total <= 0:
        probs = np.full(probs.size, 1.0 / probs.size)
    else:
        probs = probs / total
    order = np.argsort(probs)[::-1][:max(1, min(k, len(probs)))]
    return [{"label": str(labels[i]), "probability": float(probs[i])} for i in order]


def insufficient_information(selected_symptoms: Iterable[str], top_probability: float, threshold: float) -> tuple[bool, str]:
    """Tahan prediksi bila gejala sedikit atau probabilitas tertinggi di bawah threshold empiris."""
    n_selected = len(set(selected_symptoms or []))
    if n_selected < 3:
        return True, "Gejala yang dipilih kurang dari 3. Tambahkan gejala yang benar-benar dialami; jangan menebak gejala."
    if float(top_probability) < float(threshold):
        return True, (
            f"Probabilitas tertinggi ({top_probability:.1%}) di bawah ambang empiris ({threshold:.1%}) "
            "yang dihitung dari prediksi validasi internal. Model menahan dugaan dan meminta informasi tambahan."
        )
    return False, ""


def explain_symptom_candidates(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    selected_symptoms: Iterable[str],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tampilkan gejala terpilih yang mendukung dan gejala lazim yang belum dipilih."""
    mapping_symptom = load_symptom_mapping()
    mapping_disease = load_disease_mapping()
    selected = set(selected_symptoms or [])
    prevalence = X_train.groupby(y_train).mean()
    explanations: list[dict[str, Any]] = []
    for candidate in candidates:
        label = candidate["label"]
        if label not in prevalence.index:
            continue
        rates = prevalence.loc[label].sort_values(ascending=False)
        present = [s for s in selected if s in rates.index]
        present_sorted = sorted(present, key=lambda s: float(rates.get(s, 0.0)), reverse=True)[:5]
        missing = [s for s in rates.index if s not in selected and float(rates[s]) >= 0.30]
        missing_sorted = sorted(missing, key=lambda s: float(rates[s]), reverse=True)[:5]
        explanations.append({
            "disease": disease_label(str(label), mapping_disease),
            "probability": float(candidate["probability"]),
            "supporting_symptoms": [
                {"id": s, "label": symptom_label(s, mapping_symptom), "training_prevalence": float(rates[s])}
                for s in present_sorted
            ],
            "commonly_seen_but_not_selected": [
                {"id": s, "label": symptom_label(s, mapping_symptom), "training_prevalence": float(rates[s])}
                for s in missing_sorted
            ],
            "note": "Prevalensi berasal dari dataset, bukan kriteria diagnosis atau hubungan sebab-akibat.",
        })
    return explanations


def suggest_followup_symptoms(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    candidates: list[dict[str, Any]],
    selected_symptoms: Iterable[str],
    n_questions: int = 3,
) -> list[dict[str, Any]]:
    """Pilih gejala dengan information gain tertinggi pada kandidat penyakit teratas."""
    if len(candidates) < 2:
        return []
    candidate_labels = [c["label"] for c in candidates[:3]]
    mask = y_train.isin(candidate_labels)
    X_sub = X_train.loc[mask]
    y_sub = y_train.loc[mask]
    if y_sub.nunique() < 2:
        return []
    selected = set(selected_symptoms or [])
    scores: list[tuple[str, float]] = []
    base_entropy = _entropy(y_sub.astype(str).to_numpy())
    for feature in X_train.columns:
        if feature in selected or X_sub[feature].nunique(dropna=False) < 2:
            continue
        feature_values = X_sub[feature].astype(int).to_numpy()
        mutual_info = float(mutual_info_score(y_sub.astype(str).to_numpy(), feature_values))
        # MI dihitung dalam nat; setara information gain untuk target diskret.
        scores.append((feature, mutual_info if np.isfinite(mutual_info) else 0.0))
    scores.sort(key=lambda item: item[1], reverse=True)
    mapping = load_symptom_mapping()
    return [
        {"id": feature, "label": symptom_label(feature, mapping), "information_gain": score,
         "question": f"Apakah gejala berikut juga dialami: {symptom_label(feature, mapping)}?"}
        for feature, score in scores[:n_questions]
    ]


def _entropy(labels: np.ndarray) -> float:
    """Entropi empiris untuk informasi tambahan."""
    if len(labels) == 0:
        return 0.0
    _, counts = np.unique(labels, return_counts=True)
    probabilities = counts / counts.sum()
    return float(-(probabilities * np.log(probabilities + 1e-12)).sum())


def explain_screening_individual(model: Any, values: dict[str, float], feature_names: list[str], reference_medians: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Perkirakan arah perubahan skor dengan mengganti satu fitur ke median referensi model."""
    row = pd.DataFrame([{name: float(values[name]) for name in feature_names}], columns=feature_names)
    baseline = reference_medians or getattr(model, "reference_medians", None)
    if baseline is None:
        baseline = {name: float(row[name].median()) for name in feature_names}
    # Baseline median disimpan pada bundle oleh train_screening.py.
    base_row = pd.DataFrame([{name: float(baseline[name]) for name in feature_names}], columns=feature_names)
    base_prob = float(model.predict_proba(base_row)[0][1])
    input_prob = float(model.predict_proba(row)[0][1])
    changes: list[dict[str, Any]] = []
    for feature in feature_names:
        altered = row.copy()
        altered.loc[0, feature] = float(baseline[feature])
        p_alt = float(model.predict_proba(altered)[0][1])
        delta = input_prob - p_alt
        changes.append({"feature": feature, "change_vs_median": delta,
                        "direction": "menaikkan skor dibanding median" if delta > 0 else "menurunkan skor dibanding median" if delta < 0 else "hampir tidak mengubah skor",
                        "absolute_change": abs(delta)})
    # Bandingkan skor input aktual dengan skor saat fitur diubah ke median.
    out = []
    for item in changes:
        impact = item["change_vs_median"]
        out.append({**item, "input_probability": input_prob, "baseline_probability": base_prob,
                    "interpretation": "Perubahan satu fitur pada model; bukan kausalitas klinis."})
    return sorted(out, key=lambda item: item["absolute_change"], reverse=True)[:5]
```

---

## `safety.py`

```python
"""Lapisan keselamatan berbasis aturan yang selalu dijalankan di luar model."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from config import CONFIG_DIR


def _normalize_text(value: str) -> str:
    """Normalisasi kata untuk pencocokan gejala red flag."""
    text = str(value).strip().lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_safety_config(path: Path | None = None) -> dict[str, Any]:
    """Muat aturan red flag dan peringatan kelompok khusus."""
    config_path = path or (CONFIG_DIR / "red_flags.json")
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def detect_red_flags(
    selected_symptoms: Iterable[str] | None = None,
    explicit_red_flags: Iterable[str] | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Kembalikan red flag yang cocok; tidak melihat atau bergantung pada prediksi ML."""
    config = config or load_safety_config()
    selected = {_normalize_text(s) for s in (selected_symptoms or []) if str(s).strip()}
    explicit = {_normalize_text(s) for s in (explicit_red_flags or []) if str(s).strip()}
    matched: list[dict[str, Any]] = []
    for flag in config.get("red_flags", []):
        candidates = {_normalize_text(flag.get("id", "")), _normalize_text(flag.get("label", ""))}
        candidates.update(_normalize_text(x) for x in flag.get("aliases", []))
        candidates.update(_normalize_text(x) for x in flag.get("dataset_columns", []))
        terms = selected | explicit
        hit = any(term and any(term == candidate or term in candidate or candidate in term
                                for candidate in candidates if candidate)
                  for term in terms if term)
        # Cegah kecocokan substring kosong.
        if hit:
            matched.append({**flag, "review_status": config.get("review_status", "PERLU DITINJAU TENAGA MEDIS")})
    # Hilangkan ID ganda jika satu red flag cocok pada beberapa alias.
    unique: dict[str, dict[str, Any]] = {item["id"]: item for item in matched}
    return list(unique.values())


def red_flag_message(flags: Iterable[dict[str, Any]], config: dict[str, Any] | None = None) -> str:
    """Buat peringatan gawat darurat yang tidak bergantung pada hasil prediksi."""
    flags = list(flags)
    if not flags:
        return ""
    config = config or load_safety_config()
    names = ", ".join(item.get("label", item.get("id", "gejala gawat darurat")) for item in flags)
    return f"🚨 **PERINGATAN GAWAT DARURAT: {names}.** {config.get('display_message', 'Segera cari pertolongan darurat.') }"


def static_population_warnings(config: dict[str, Any] | None = None) -> list[str]:
    """Peringatan kelompok pasien yang tidak sesuai untuk prototipe ini."""
    config = config or load_safety_config()
    return list(config.get("static_warnings", []))


def matched_red_flag_columns(feature_columns: Iterable[str], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Laporkan cakupan pemetaan red flag ke fitur yang betul-betul ada dalam dataset."""
    config = config or load_safety_config()
    available = {_normalize_text(c): str(c) for c in feature_columns}
    results: dict[str, Any] = {}
    for flag in config.get("red_flags", []):
        found = []
        for candidate in flag.get("dataset_columns", []):
            normalized = _normalize_text(candidate)
            if normalized in available:
                found.append(available[normalized])
        results[flag["id"]] = {
            "label": flag["label"],
            "columns_found": found,
            "manual_ui_control_available": True,
            "needs_medical_review": True,
        }
    return results
```

---

## `app.py`

```python
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
```

---

## `requirements.txt`

```text
# Disarankan Python 3.10-3.12 untuk kompatibilitas pustaka ilmiah.
pandas>=2.1,<3.0
numpy>=1.24,<3.0
scikit-learn>=1.4,<2.0
matplotlib>=3.8,<4.0
joblib>=1.3,<2.0
streamlit>=1.36,<2.0
pytest>=8.0,<10.0
```

---

## `config/red_flags.json`

```json
{
  "review_status": "PERLU DITINJAU TENAGA MEDIS",
  "display_message": "GEJALA GAWAT DARURAT TERPILIH. Jangan menunggu hasil model. Segera ke IGD atau hubungi 112 / 119. Ketersediaan layanan 112 bergantung pada implementasi pemerintah daerah; 119 adalah layanan darurat kesehatan PSC.",
  "red_flags": [
    {"id":"chest_pain","label":"Nyeri dada","dataset_columns":["chest_pain"],"aliases":["nyeri dada","chest pain"],"needs_medical_review":true},
    {"id":"severe_breathlessness","label":"Sesak napas berat","dataset_columns":["breathlessness","shortness_of_breath","dyspnea"],"aliases":["sesak napas berat","sesak napas","breathlessness","shortness of breath","dyspnea"],"needs_medical_review":true},
    {"id":"reduced_consciousness","label":"Penurunan kesadaran","dataset_columns":["altered_sensorium","coma","loss_of_consciousness"],"aliases":["penurunan kesadaran","altered sensorium","coma","loss of consciousness"],"needs_medical_review":true},
    {"id":"sudden_paralysis_face","label":"Kelumpuhan atau wajah mencong mendadak","dataset_columns":["weakness_of_one_body_side","paralysis","slurred_speech"],"aliases":["kelumpuhan mendadak","wajah mencong","weakness of one body side","paralysis","slurred speech","bicara pelo mendadak"],"needs_medical_review":true},
    {"id":"seizure","label":"Kejang","dataset_columns":["seizures","seizure","convulsion"],"aliases":["kejang","seizures","seizure","convulsion"],"needs_medical_review":true},
    {"id":"severe_bleeding","label":"Perdarahan hebat","dataset_columns":["stomach_bleeding","bloody_stool","blood_in_sputum"],"aliases":["perdarahan hebat","severe bleeding","hemorrhage"],"needs_medical_review":true},
    {"id":"vomiting_blood","label":"Muntah darah","dataset_columns":["vomiting_blood","hematemesis"],"aliases":["muntah darah","vomiting blood","hematemesis"],"needs_medical_review":true}
  ],
  "static_warnings": [
    "Untuk bayi/anak kecil, ibu hamil, lansia, atau orang dengan penyakit kronis, jangan jadikan hasil aplikasi sebagai acuan; langsung konsultasikan ke dokter atau fasilitas kesehatan."
  ],
  "sources": [
    {"title":"Kemenkes RI — Kenali stroke iskemik dan bertindak cepat","url":"https://keslan.kemkes.go.id/view_artikel/4465/kenali-stroke-iskemik-dan-bertindak-cepat"},
    {"title":"Kemenkes RI — PSC 119","url":"https://kemkes.go.id/id/layanan/psc-119"},
    {"title":"Komdigi — Tentang Layanan Panggilan Darurat 112","url":"https://layanan112.komdigi.go.id/tentang"}
  ]
}
```

---

## `config/symptom_mapping_id.json`

```json
{
  "itching": {
    "id": "itching",
    "label_id": "Gatal",
    "aliases": [
      "gatal"
    ],
    "needs_medical_review": true
  },
  "skin_rash": {
    "id": "skin_rash",
    "label_id": "Ruam kulit",
    "aliases": [
      "ruam",
      "ruam kulit"
    ],
    "needs_medical_review": true
  },
  "nodal_skin_eruptions": {
    "id": "nodal_skin_eruptions",
    "label_id": "Lesi kulit berbintil",
    "aliases": [],
    "needs_medical_review": true
  },
  "continuous_sneezing": {
    "id": "continuous_sneezing",
    "label_id": "Bersin terus-menerus",
    "aliases": [
      "bersin terus-menerus"
    ],
    "needs_medical_review": true
  },
  "shivering": {
    "id": "shivering",
    "label_id": "Menggigil",
    "aliases": [
      "menggigil"
    ],
    "needs_medical_review": true
  },
  "chills": {
    "id": "chills",
    "label_id": "Merasa kedinginan/menggigil",
    "aliases": [],
    "needs_medical_review": true
  },
  "joint_pain": {
    "id": "joint_pain",
    "label_id": "Nyeri sendi",
    "aliases": [
      "nyeri sendi"
    ],
    "needs_medical_review": true
  },
  "stomach_pain": {
    "id": "stomach_pain",
    "label_id": "Nyeri perut",
    "aliases": [
      "sakit perut"
    ],
    "needs_medical_review": true
  },
  "acidity": {
    "id": "acidity",
    "label_id": "Rasa asam/terbakar di lambung",
    "aliases": [],
    "needs_medical_review": true
  },
  "ulcers_on_tongue": {
    "id": "ulcers_on_tongue",
    "label_id": "Luka pada lidah",
    "aliases": [],
    "needs_medical_review": true
  },
  "muscle_wasting": {
    "id": "muscle_wasting",
    "label_id": "Penyusutan massa otot",
    "aliases": [],
    "needs_medical_review": true
  },
  "vomiting": {
    "id": "vomiting",
    "label_id": "Muntah",
    "aliases": [
      "muntah"
    ],
    "needs_medical_review": true
  },
  "burning_micturition": {
    "id": "burning_micturition",
    "label_id": "Nyeri/perih saat berkemih",
    "aliases": [],
    "needs_medical_review": true
  },
  "spotting_urination": {
    "id": "spotting_urination",
    "label_id": "Bercak darah saat berkemih",
    "aliases": [],
    "needs_medical_review": true
  },
  "fatigue": {
    "id": "fatigue",
    "label_id": "Kelelahan",
    "aliases": [
      "lelah"
    ],
    "needs_medical_review": true
  },
  "weight_gain": {
    "id": "weight_gain",
    "label_id": "Berat badan bertambah",
    "aliases": [],
    "needs_medical_review": true
  },
  "anxiety": {
    "id": "anxiety",
    "label_id": "Rasa cemas",
    "aliases": [],
    "needs_medical_review": true
  },
  "cold_hands_and_feets": {
    "id": "cold_hands_and_feets",
    "label_id": "Tangan dan kaki terasa dingin",
    "aliases": [],
    "needs_medical_review": true
  },
  "mood_swings": {
    "id": "mood_swings",
    "label_id": "Perubahan suasana hati",
    "aliases": [],
    "needs_medical_review": true
  },
  "weight_loss": {
    "id": "weight_loss",
    "label_id": "Berat badan menurun tanpa sebab jelas",
    "aliases": [],
    "needs_medical_review": true
  },
  "restlessness": {
    "id": "restlessness",
    "label_id": "Gelisah",
    "aliases": [],
    "needs_medical_review": true
  },
  "lethargy": {
    "id": "lethargy",
    "label_id": "Lesu",
    "aliases": [],
    "needs_medical_review": true
  },
  "patches_in_throat": {
    "id": "patches_in_throat",
    "label_id": "Bercak pada tenggorokan",
    "aliases": [],
    "needs_medical_review": true
  },
  "irregular_sugar_level": {
    "id": "irregular_sugar_level",
    "label_id": "Kadar gula tidak teratur",
    "aliases": [],
    "needs_medical_review": true
  },
  "cough": {
    "id": "cough",
    "label_id": "Batuk",
    "aliases": [
      "batuk"
    ],
    "needs_medical_review": true
  },
  "high_fever": {
    "id": "high_fever",
    "label_id": "Demam tinggi",
    "aliases": [
      "demam tinggi"
    ],
    "needs_medical_review": true
  },
  "sunken_eyes": {
    "id": "sunken_eyes",
    "label_id": "Mata cekung",
    "aliases": [],
    "needs_medical_review": true
  },
  "breathlessness": {
    "id": "breathlessness",
    "label_id": "Sesak napas",
    "aliases": [
      "sesak napas"
    ],
    "needs_medical_review": true
  },
  "sweating": {
    "id": "sweating",
    "label_id": "Berkeringat",
    "aliases": [],
    "needs_medical_review": true
  },
  "dehydration": {
    "id": "dehydration",
    "label_id": "Tanda dehidrasi",
    "aliases": [],
    "needs_medical_review": true
  },
  "indigestion": {
    "id": "indigestion",
    "label_id": "Gangguan pencernaan",
    "aliases": [],
    "needs_medical_review": true
  },
  "headache": {
    "id": "headache",
    "label_id": "Sakit kepala",
    "aliases": [
      "sakit kepala"
    ],
    "needs_medical_review": true
  },
  "yellowish_skin": {
    "id": "yellowish_skin",
    "label_id": "Kulit tampak kekuningan",
    "aliases": [],
    "needs_medical_review": true
  },
  "dark_urine": {
    "id": "dark_urine",
    "label_id": "Warna urine gelap",
    "aliases": [],
    "needs_medical_review": true
  },
  "nausea": {
    "id": "nausea",
    "label_id": "Mual",
    "aliases": [
      "mual"
    ],
    "needs_medical_review": true
  },
  "loss_of_appetite": {
    "id": "loss_of_appetite",
    "label_id": "Nafsu makan menurun",
    "aliases": [],
    "needs_medical_review": true
  },
  "pain_behind_the_eyes": {
    "id": "pain_behind_the_eyes",
    "label_id": "Nyeri di belakang mata",
    "aliases": [],
    "needs_medical_review": true
  },
  "back_pain": {
    "id": "back_pain",
    "label_id": "Nyeri punggung",
    "aliases": [],
    "needs_medical_review": true
  },
  "constipation": {
    "id": "constipation",
    "label_id": "Sembelit",
    "aliases": [],
    "needs_medical_review": true
  },
  "abdominal_pain": {
    "id": "abdominal_pain",
    "label_id": "Nyeri abdomen",
    "aliases": [],
    "needs_medical_review": true
  },
  "diarrhoea": {
    "id": "diarrhoea",
    "label_id": "Diare",
    "aliases": [
      "diare"
    ],
    "needs_medical_review": true
  },
  "mild_fever": {
    "id": "mild_fever",
    "label_id": "Demam ringan",
    "aliases": [],
    "needs_medical_review": true
  },
  "yellow_urine": {
    "id": "yellow_urine",
    "label_id": "Urine berwarna kuning pekat",
    "aliases": [],
    "needs_medical_review": true
  },
  "yellowing_of_eyes": {
    "id": "yellowing_of_eyes",
    "label_id": "Bagian putih mata menguning",
    "aliases": [],
    "needs_medical_review": true
  },
  "acute_liver_failure": {
    "id": "acute_liver_failure",
    "label_id": "Gangguan fungsi hati akut",
    "aliases": [],
    "needs_medical_review": true
  },
  "fluid_overload": {
    "id": "fluid_overload",
    "label_id": "Kelebihan cairan",
    "aliases": [],
    "needs_medical_review": true
  },
  "swelling_of_stomach": {
    "id": "swelling_of_stomach",
    "label_id": "Pembengkakan perut",
    "aliases": [],
    "needs_medical_review": true
  },
  "swelled_lymph_nodes": {
    "id": "swelled_lymph_nodes",
    "label_id": "Pembesaran kelenjar getah bening",
    "aliases": [],
    "needs_medical_review": true
  },
  "malaise": {
    "id": "malaise",
    "label_id": "Rasa tidak enak badan",
    "aliases": [],
    "needs_medical_review": true
  },
  "blurred_and_distorted_vision": {
    "id": "blurred_and_distorted_vision",
    "label_id": "Penglihatan kabur/terdistorsi",
    "aliases": [],
    "needs_medical_review": true
  },
  "phlegm": {
    "id": "phlegm",
    "label_id": "Dahak",
    "aliases": [],
    "needs_medical_review": true
  },
  "throat_irritation": {
    "id": "throat_irritation",
    "label_id": "Iritasi tenggorokan",
    "aliases": [],
    "needs_medical_review": true
  },
  "redness_of_eyes": {
    "id": "redness_of_eyes",
    "label_id": "Mata merah",
    "aliases": [],
    "needs_medical_review": true
  },
  "sinus_pressure": {
    "id": "sinus_pressure",
    "label_id": "Tekanan pada sinus",
    "aliases": [],
    "needs_medical_review": true
  },
  "runny_nose": {
    "id": "runny_nose",
    "label_id": "Hidung berair",
    "aliases": [],
    "needs_medical_review": true
  },
  "congestion": {
    "id": "congestion",
    "label_id": "Hidung tersumbat",
    "aliases": [],
    "needs_medical_review": true
  },
  "chest_pain": {
    "id": "chest_pain",
    "label_id": "Nyeri dada",
    "aliases": [
      "nyeri dada"
    ],
    "needs_medical_review": true
  },
  "weakness_in_limbs": {
    "id": "weakness_in_limbs",
    "label_id": "Kelemahan anggota gerak",
    "aliases": [],
    "needs_medical_review": true
  },
  "fast_heart_rate": {
    "id": "fast_heart_rate",
    "label_id": "Denyut jantung cepat",
    "aliases": [],
    "needs_medical_review": true
  },
  "pain_during_bowel_movements": {
    "id": "pain_during_bowel_movements",
    "label_id": "Nyeri saat buang air besar",
    "aliases": [],
    "needs_medical_review": true
  },
  "pain_in_anal_region": {
    "id": "pain_in_anal_region",
    "label_id": "Nyeri di area anus",
    "aliases": [],
    "needs_medical_review": true
  },
  "bloody_stool": {
    "id": "bloody_stool",
    "label_id": "Tinja berdarah",
    "aliases": [],
    "needs_medical_review": true
  },
  "neck_pain": {
    "id": "neck_pain",
    "label_id": "Nyeri leher",
    "aliases": [],
    "needs_medical_review": true
  },
  "dizziness": {
    "id": "dizziness",
    "label_id": "Pusing",
    "aliases": [],
    "needs_medical_review": true
  },
  "cramps": {
    "id": "cramps",
    "label_id": "Kram",
    "aliases": [],
    "needs_medical_review": true
  },
  "obesity": {
    "id": "obesity",
    "label_id": "Obesitas pada data sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "swollen_legs": {
    "id": "swollen_legs",
    "label_id": "Kaki bengkak",
    "aliases": [],
    "needs_medical_review": true
  },
  "swollen_blood_vessels": {
    "id": "swollen_blood_vessels",
    "label_id": "Pembuluh darah membesar",
    "aliases": [],
    "needs_medical_review": true
  },
  "puffy_face_and_eyes": {
    "id": "puffy_face_and_eyes",
    "label_id": "Wajah dan mata bengkak",
    "aliases": [],
    "needs_medical_review": true
  },
  "enlarged_thyroid": {
    "id": "enlarged_thyroid",
    "label_id": "Pembesaran kelenjar tiroid",
    "aliases": [],
    "needs_medical_review": true
  },
  "brittle_nails": {
    "id": "brittle_nails",
    "label_id": "Kuku rapuh",
    "aliases": [],
    "needs_medical_review": true
  },
  "swollen_extremeties": {
    "id": "swollen_extremeties",
    "label_id": "Anggota tubuh bengkak",
    "aliases": [],
    "needs_medical_review": true
  },
  "excessive_hunger": {
    "id": "excessive_hunger",
    "label_id": "Rasa lapar berlebihan",
    "aliases": [],
    "needs_medical_review": true
  },
  "drying_and_tingling_lips": {
    "id": "drying_and_tingling_lips",
    "label_id": "Bibir kering/kesemutan",
    "aliases": [],
    "needs_medical_review": true
  },
  "slurred_speech": {
    "id": "slurred_speech",
    "label_id": "Bicara pelo",
    "aliases": [
      "bicara pelo"
    ],
    "needs_medical_review": true
  },
  "muscle_weakness": {
    "id": "muscle_weakness",
    "label_id": "Kelemahan otot",
    "aliases": [],
    "needs_medical_review": true
  },
  "stiff_neck": {
    "id": "stiff_neck",
    "label_id": "Leher kaku",
    "aliases": [],
    "needs_medical_review": true
  },
  "swelling_joints": {
    "id": "swelling_joints",
    "label_id": "Sendi bengkak",
    "aliases": [],
    "needs_medical_review": true
  },
  "movement_stiffness": {
    "id": "movement_stiffness",
    "label_id": "Kekakuan saat bergerak",
    "aliases": [],
    "needs_medical_review": true
  },
  "spinning_movements": {
    "id": "spinning_movements",
    "label_id": "Sensasi berputar",
    "aliases": [],
    "needs_medical_review": true
  },
  "loss_of_balance": {
    "id": "loss_of_balance",
    "label_id": "Kehilangan keseimbangan",
    "aliases": [],
    "needs_medical_review": true
  },
  "unsteadiness": {
    "id": "unsteadiness",
    "label_id": "Tubuh tidak stabil",
    "aliases": [],
    "needs_medical_review": true
  },
  "weakness_of_one_body_side": {
    "id": "weakness_of_one_body_side",
    "label_id": "Kelemahan satu sisi tubuh",
    "aliases": [],
    "needs_medical_review": true
  },
  "loss_of_smell": {
    "id": "loss_of_smell",
    "label_id": "Kehilangan kemampuan mencium bau",
    "aliases": [],
    "needs_medical_review": true
  },
  "bladder_discomfort": {
    "id": "bladder_discomfort",
    "label_id": "Rasa tidak nyaman pada kandung kemih",
    "aliases": [],
    "needs_medical_review": true
  },
  "continuous_feel_of_urine": {
    "id": "continuous_feel_of_urine",
    "label_id": "Sering merasa ingin berkemih",
    "aliases": [],
    "needs_medical_review": true
  },
  "internal_itching": {
    "id": "internal_itching",
    "label_id": "Rasa gatal internal pada data sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "depression": {
    "id": "depression",
    "label_id": "Perubahan suasana perasaan pada data sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "irritability": {
    "id": "irritability",
    "label_id": "Mudah tersinggung",
    "aliases": [],
    "needs_medical_review": true
  },
  "muscle_pain": {
    "id": "muscle_pain",
    "label_id": "Nyeri otot",
    "aliases": [],
    "needs_medical_review": true
  },
  "altered_sensorium": {
    "id": "altered_sensorium",
    "label_id": "Perubahan kesadaran/status mental",
    "aliases": [
      "penurunan kesadaran"
    ],
    "needs_medical_review": true
  },
  "coma": {
    "id": "coma",
    "label_id": "Koma/penurunan kesadaran berat",
    "aliases": [
      "penurunan kesadaran"
    ],
    "needs_medical_review": true
  },
  "stomach_bleeding": {
    "id": "stomach_bleeding",
    "label_id": "Perdarahan saluran cerna pada data sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "blood_in_sputum": {
    "id": "blood_in_sputum",
    "label_id": "Darah pada dahak",
    "aliases": [],
    "needs_medical_review": true
  },
  "palpitations": {
    "id": "palpitations",
    "label_id": "Jantung berdebar",
    "aliases": [],
    "needs_medical_review": true
  },
  "painful_walking": {
    "id": "painful_walking",
    "label_id": "Nyeri saat berjalan",
    "aliases": [],
    "needs_medical_review": true
  },
  "blister": {
    "id": "blister",
    "label_id": "Lepuh",
    "aliases": [],
    "needs_medical_review": true
  },
  "skin_peeling": {
    "id": "skin_peeling",
    "label_id": "Kulit mengelupas",
    "aliases": [],
    "needs_medical_review": true
  },
  "irritation_in_anus": {
    "id": "irritation_in_anus",
    "label_id": "Iritasi sekitar anus",
    "aliases": [],
    "needs_medical_review": true
  },
  "bruising": {
    "id": "bruising",
    "label_id": "Memar",
    "aliases": [],
    "needs_medical_review": true
  },
  "extra_marital_contacts": {
    "id": "extra_marital_contacts",
    "label_id": "Riwayat kontak seksual ekstra-marit(al) pada label sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "knee_pain": {
    "id": "knee_pain",
    "label_id": "Nyeri lutut",
    "aliases": [],
    "needs_medical_review": true
  },
  "hip_joint_pain": {
    "id": "hip_joint_pain",
    "label_id": "Nyeri sendi panggul",
    "aliases": [],
    "needs_medical_review": true
  },
  "foul_smell_of_urine": {
    "id": "foul_smell_of_urine",
    "label_id": "Urine berbau tidak biasa",
    "aliases": [],
    "needs_medical_review": true
  },
  "passage_of_gases": {
    "id": "passage_of_gases",
    "label_id": "Sering buang gas",
    "aliases": [],
    "needs_medical_review": true
  },
  "toxic_look_typhos": {
    "id": "toxic_look_typhos",
    "label_id": "Tampak sakit berat pada label sumber (typhos)",
    "aliases": [],
    "needs_medical_review": true
  },
  "red_spots_over_body": {
    "id": "red_spots_over_body",
    "label_id": "Bintik merah pada tubuh",
    "aliases": [],
    "needs_medical_review": true
  },
  "belly_pain": {
    "id": "belly_pain",
    "label_id": "Nyeri perut",
    "aliases": [],
    "needs_medical_review": true
  },
  "abnormal_menstruation": {
    "id": "abnormal_menstruation",
    "label_id": "Menstruasi tidak normal",
    "aliases": [],
    "needs_medical_review": true
  },
  "dischromic_patches": {
    "id": "dischromic_patches",
    "label_id": "Bercak perubahan warna kulit",
    "aliases": [],
    "needs_medical_review": true
  },
  "watering_from_eyes": {
    "id": "watering_from_eyes",
    "label_id": "Mata berair",
    "aliases": [],
    "needs_medical_review": true
  },
  "increased_appetite": {
    "id": "increased_appetite",
    "label_id": "Nafsu makan meningkat",
    "aliases": [],
    "needs_medical_review": true
  },
  "polyuria": {
    "id": "polyuria",
    "label_id": "Sering berkemih",
    "aliases": [],
    "needs_medical_review": true
  },
  "family_history": {
    "id": "family_history",
    "label_id": "Riwayat keluarga",
    "aliases": [],
    "needs_medical_review": true
  },
  "mucoid_sputum": {
    "id": "mucoid_sputum",
    "label_id": "Dahak berlendir",
    "aliases": [],
    "needs_medical_review": true
  },
  "rusty_sputum": {
    "id": "rusty_sputum",
    "label_id": "Dahak berwarna seperti karat pada label sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "lack_of_concentration": {
    "id": "lack_of_concentration",
    "label_id": "Sulit berkonsentrasi",
    "aliases": [],
    "needs_medical_review": true
  },
  "visual_disturbances": {
    "id": "visual_disturbances",
    "label_id": "Gangguan penglihatan",
    "aliases": [],
    "needs_medical_review": true
  },
  "receiving_blood_transfusion": {
    "id": "receiving_blood_transfusion",
    "label_id": "Pernah menerima transfusi darah",
    "aliases": [],
    "needs_medical_review": true
  },
  "receiving_unsterile_injections": {
    "id": "receiving_unsterile_injections",
    "label_id": "Paparan suntikan tidak steril menurut label sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "distention_of_abdomen": {
    "id": "distention_of_abdomen",
    "label_id": "Perut membuncit/distensi",
    "aliases": [],
    "needs_medical_review": true
  },
  "history_of_alcohol_consumption": {
    "id": "history_of_alcohol_consumption",
    "label_id": "Riwayat konsumsi alkohol",
    "aliases": [],
    "needs_medical_review": true
  },
  "prominent_veins_on_calf": {
    "id": "prominent_veins_on_calf",
    "label_id": "Pembuluh darah betis tampak menonjol",
    "aliases": [],
    "needs_medical_review": true
  },
  "pus_filled_pimples": {
    "id": "pus_filled_pimples",
    "label_id": "Jerawat bernanah",
    "aliases": [],
    "needs_medical_review": true
  },
  "blackheads": {
    "id": "blackheads",
    "label_id": "Komedo",
    "aliases": [],
    "needs_medical_review": true
  },
  "scurring": {
    "id": "scurring",
    "label_id": "Bekas/kerak kulit pada label sumber",
    "aliases": [],
    "needs_medical_review": true
  },
  "silver_like_dusting": {
    "id": "silver_like_dusting",
    "label_id": "Sisik keperakan pada kulit",
    "aliases": [],
    "needs_medical_review": true
  },
  "small_dents_in_nails": {
    "id": "small_dents_in_nails",
    "label_id": "Lekukan kecil pada kuku",
    "aliases": [],
    "needs_medical_review": true
  },
  "inflammatory_nails": {
    "id": "inflammatory_nails",
    "label_id": "Peradangan kuku",
    "aliases": [],
    "needs_medical_review": true
  },
  "red_sore_around_nose": {
    "id": "red_sore_around_nose",
    "label_id": "Luka kemerahan sekitar hidung",
    "aliases": [],
    "needs_medical_review": true
  },
  "yellow_crust_ooze": {
    "id": "yellow_crust_ooze",
    "label_id": "Kerak kuning/cairan pada kulit",
    "aliases": [],
    "needs_medical_review": true
  },
  "seizures": {
    "id": "seizures",
    "label_id": "Kejang",
    "aliases": [],
    "needs_medical_review": true
  },
  "seizure": {
    "id": "seizure",
    "label_id": "Kejang",
    "aliases": [],
    "needs_medical_review": true
  },
  "convulsion": {
    "id": "convulsion",
    "label_id": "Kejang",
    "aliases": [],
    "needs_medical_review": true
  },
  "shortness_of_breath": {
    "id": "shortness_of_breath",
    "label_id": "Sesak napas",
    "aliases": [],
    "needs_medical_review": true
  },
  "vomiting_blood": {
    "id": "vomiting_blood",
    "label_id": "Muntah darah",
    "aliases": [],
    "needs_medical_review": true
  },
  "loss_of_consciousness": {
    "id": "loss_of_consciousness",
    "label_id": "Penurunan kesadaran",
    "aliases": [],
    "needs_medical_review": true
  },
  "paralysis": {
    "id": "paralysis",
    "label_id": "Kelumpuhan",
    "aliases": [],
    "needs_medical_review": true
  }
}
```

---

## `config/disease_mapping_id.json`

```json
{
  "Fungal infection": {"label_id": "Infeksi jamur", "needs_medical_review": true},
  "Allergy": {"label_id": "Alergi", "needs_medical_review": true},
  "GERD": {"label_id": "Penyakit refluks gastroesofageal (GERD)", "needs_medical_review": true},
  "Chronic cholestasis": {"label_id": "Kolestasis kronis", "needs_medical_review": true},
  "Drug Reaction": {"label_id": "Reaksi obat", "needs_medical_review": true},
  "Peptic ulcer disease": {"label_id": "Penyakit ulkus peptikum", "needs_medical_review": true},
  "AIDS": {"label_id": "AIDS", "needs_medical_review": true},
  "Diabetes ": {"label_id": "Diabetes (label dataset)", "needs_medical_review": true},
  "Diabetes": {"label_id": "Diabetes (label dataset)", "needs_medical_review": true},
  "Gastroenteritis": {"label_id": "Gastroenteritis", "needs_medical_review": true},
  "Bronchial Asthma": {"label_id": "Asma bronkial", "needs_medical_review": true},
  "Hypertension ": {"label_id": "Hipertensi (label dataset)", "needs_medical_review": true},
  "Hypertension": {"label_id": "Hipertensi (label dataset)", "needs_medical_review": true},
  "Migraine": {"label_id": "Migrain", "needs_medical_review": true},
  "Cervical spondylosis": {"label_id": "Spondilosis servikal", "needs_medical_review": true},
  "Paralysis (brain hemorrhage)": {"label_id": "Kelumpuhan (label dataset: perdarahan otak)", "needs_medical_review": true},
  "Jaundice": {"label_id": "Ikterus/jaundice", "needs_medical_review": true},
  "Malaria": {"label_id": "Malaria", "needs_medical_review": true},
  "Chicken pox": {"label_id": "Cacar air", "needs_medical_review": true},
  "Dengue": {"label_id": "Dengue", "needs_medical_review": true},
  "Typhoid": {"label_id": "Demam tifoid", "needs_medical_review": true},
  "hepatitis A": {"label_id": "Hepatitis A", "needs_medical_review": true},
  "hepatitis B": {"label_id": "Hepatitis B", "needs_medical_review": true},
  "hepatitis C": {"label_id": "Hepatitis C", "needs_medical_review": true},
  "hepatitis D": {"label_id": "Hepatitis D", "needs_medical_review": true},
  "hepatitis E": {"label_id": "Hepatitis E", "needs_medical_review": true},
  "Alcoholic hepatitis": {"label_id": "Hepatitis terkait alkohol (label dataset)", "needs_medical_review": true},
  "Tuberculosis": {"label_id": "Tuberkulosis", "needs_medical_review": true},
  "Common Cold": {"label_id": "Sel esma/common cold", "needs_medical_review": true},
  "Pneumonia": {"label_id": "Pneumonia", "needs_medical_review": true},
  "Dimorphic hemmorhoids(piles)": {"label_id": "Hemoroid (label dataset)", "needs_medical_review": true},
  "Dimorphic hemorrhoids(piles)": {"label_id": "Hemoroid (label dataset)", "needs_medical_review": true},
  "Heart attack": {"label_id": "Serangan jantung (label dataset)", "needs_medical_review": true},
  "Varicose veins": {"label_id": "Varises", "needs_medical_review": true},
  "Hypothyroidism": {"label_id": "Hipotiroidisme", "needs_medical_review": true},
  "Hyperthyroidism": {"label_id": "Hipertiroidisme", "needs_medical_review": true},
  "Hypoglycemia": {"label_id": "Hipoglikemia", "needs_medical_review": true},
  "Osteoarthristis": {"label_id": "Osteoartritis (label dataset)", "needs_medical_review": true},
  "Osteoarthritis": {"label_id": "Osteoartritis", "needs_medical_review": true},
  "Arthritis": {"label_id": "Artritis", "needs_medical_review": true},
  "(vertigo) Paroymsal Positional Vertigo": {"label_id": "Vertigo posisi paroksismal (label dataset)", "needs_medical_review": true},
  "Acne": {"label_id": "Jerawat", "needs_medical_review": true},
  "Urinary tract infection": {"label_id": "Infeksi saluran kemih", "needs_medical_review": true},
  "Psoriasis": {"label_id": "Psoriasis", "needs_medical_review": true},
  "Impetigo": {"label_id": "Impetigo", "needs_medical_review": true}
}
```

---

## `config/disease_info.json`

```json
{
  "review_status": "PERLU DITINJAU TENAGA MEDIS",
  "default": {
    "description": "Deskripsi khusus penyakit belum diisi karena pemetaan nama pada dataset tidak diverifikasi sebagai definisi klinis. Tinjau oleh tenaga medis sebelum digunakan.",
    "general_advice": [
      "Catat kapan gejala mulai, lamanya, tingkat keparahan, dan perubahan yang terjadi untuk disampaikan saat konsultasi.",
      "Konsultasikan keluhan kepada dokter atau fasilitas kesehatan untuk anamnesis, pemeriksaan fisik, dan pemeriksaan lanjutan yang sesuai.",
      "Jika timbul gejala gawat darurat, jangan menunggu hasil aplikasi; segera ke IGD atau hubungi layanan darurat setempat."
    ],
    "sources": [
      {"title":"Kemenkes RI — Kenali stroke iskemik dan bertindak cepat","url":"https://keslan.kemkes.go.id/view_artikel/4465/kenali-stroke-iskemik-dan-bertindak-cepat"},
      {"title":"WHO — Diabetes: pertanyaan dan jawaban","url":"https://www.who.int/news-room/questions-and-answers/item/diabetes"}
    ]
  },
  "conditions": {}
}
```

---

## `tests/conftest.py`

```python
"""Agar modul root proyek dapat diimpor saat pytest dijalankan dari folder mana pun."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

---

## `tests/test_safety.py`

```python
"""Tes unit untuk aturan keselamatan yang tidak bergantung pada model."""
from safety import detect_red_flags, load_safety_config, red_flag_message


def test_red_flag_always_triggers_independently_of_model_output() -> None:
    cfg = load_safety_config()
    flags = detect_red_flags(selected_symptoms=[], explicit_red_flags=["chest_pain"], config=cfg)
    message = red_flag_message(flags, cfg)
    assert flags
    assert any(flag["id"] == "chest_pain" for flag in flags)
    assert "Jangan menunggu hasil model" in message or "jangan menunggu" in message.lower()


def test_red_flag_alias_in_symptom_selection() -> None:
    flags = detect_red_flags(selected_symptoms=["chest_pain"])
    assert any(flag["id"] == "chest_pain" for flag in flags)
```

---

## `tests/test_symptom_logic.py`

```python
"""Tes split, probabilitas, dan penanganan masukan kosong."""
import numpy as np
import pandas as pd

from data import make_demo_symptom_data, clean_symptom_dataframe
from explain import insufficient_information, ordered_topk
from train_symptom import prepare_symptom_split


def test_no_duplicate_rows_cross_train_test() -> None:
    frame, _ = clean_symptom_dataframe(make_demo_symptom_data(n_per_class=18))
    X_train, X_test, y_train, y_test, report = prepare_symptom_split(frame)
    train_rows = set(pd.concat([X_train.reset_index(drop=True), y_train.reset_index(drop=True).rename("prognosis")], axis=1).astype(str).agg("|".join, axis=1))
    test_rows = set(pd.concat([X_test.reset_index(drop=True), y_test.reset_index(drop=True).rename("prognosis")], axis=1).astype(str).agg("|".join, axis=1))
    assert not train_rows.intersection(test_rows)
    assert report["cross_split_exact_row_overlap"] == 0


def test_probabilities_sum_to_one_and_top3_sorted() -> None:
    top = ordered_topk([0.1, 0.7, 0.2], ["A", "B", "C"], k=3)
    assert np.isclose(sum(item["probability"] for item in top), 1.0)
    assert top[0]["label"] == "B"
    assert [item["probability"] for item in top] == sorted([item["probability"] for item in top], reverse=True)


def test_empty_or_too_few_symptoms_is_insufficient() -> None:
    hold, message = insufficient_information([], 0.99, 0.2)
    assert hold and "kurang dari 3" in message
    hold2, _ = insufficient_information(["cough", "fatigue", "headache"], 0.1, 0.2)
    assert hold2
```

---

## `tests/test_screening.py`

```python
"""Tes dasar dataset numerik: nol dimaknai sebagai missing pada fitur tertentu."""
import numpy as np

from data import make_demo_pima_data, prepare_pima_features


def test_pima_zero_values_become_missing_in_features() -> None:
    frame = make_demo_pima_data(n=100)
    frame.loc[0, "Glucose"] = 0
    X, y = prepare_pima_features(frame)
    assert np.isnan(X.loc[0, "Glucose"])
    assert len(X) == len(y)
```

---

## `data/README.md`

```markdown
# Data lokal

Tempatkan dataset yang diunduh secara manual di folder ini:

- Modul A: `Training.csv` dan (opsional) `Testing.csv` dari Kaggle kaushil268.
- Modul B: `diabetes.csv`, `pima.csv`, atau `pima-indians-diabetes.csv` dalam format Pima Indians Diabetes.

File dataset mentah tidak disertakan. Bila data tidak tersedia, skrip akan memakai data sintetis berlabel **DATA DEMO** agar fungsi perangkat lunak dapat diuji. Metrik DATA DEMO tidak merepresentasikan performa klinis.
```

---

## `README.md`

```markdown
# Asisten Diagnosis — Prototipe Riset Python

Satu aplikasi Streamlit dengan dua modul:

- **Modul A — Diagnosis banding dari gejala:** tiga kandidat statistik, probabilitas model, gejala pendukung, gejala yang belum dipilih tetapi sering muncul pada sampel kelas, pertanyaan lanjutan berbasis information gain, EDA, calibration/reliability curve, permutation importance, dan uji ketahanan.
- **Modul B — Skrining indikasi risiko diabetes:** pipeline imputasi median + scaling, perbandingan Logistic Regression / Random Forest / Gradient Boosting, class weighting, threshold dengan perhatian pada recall, confusion matrix, ROC-AUC, ROC curve, serta penjelasan skor individual.

> **Batas keselamatan:** Ini adalah prototipe edukasi/riset, bukan dokter, bukan diagnosis pasti, dan bukan alat kesehatan berizin. Setiap istilah terjemahan/penyakit dan pemetaan red flag ditandai untuk ditinjau tenaga medis. Jangan gunakan hasil untuk mengambil keputusan klinis tanpa dokter.

## 1. Persiapan lingkungan

Disarankan Python 3.10–3.12, lingkungan virtual, dan instalasi dependensi:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Dataset Modul A (Kaggle)

1. Masuk ke halaman Kaggle: https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
2. Unduh dan ekstrak berkas `Training.csv` dan `Testing.csv` (akun Kaggle mungkin diperlukan).
3. Letakkan file sebagai:

```text
data/Training.csv
data/Testing.csv
```

`Training.csv` dipakai untuk EDA, deduplikasi, split 80/20 dan evaluasi utama. `Testing.csv` hanya dipakai untuk sanity check opsional dan **bukan** untuk memilih model atau melaporkan evaluasi utama.

Jika file `Training.csv` tidak ditemukan, aplikasi training membuat data kecil **DATA DEMO SINTETIS** agar dapat menguji jalannya program. Label dan metrik demo tidak mempunyai makna klinis. Jika data lokal tersedia, kode tidak menggunakan data demo.

Kode membersihkan kolom `Unnamed`, nama kolom ganda, kolom kosong, nilai gejala non-biner, serta menghitung dan membuang duplikat **sebelum split**. Kelas dengan kurang dari 3 baris unik tidak dipakai dalam split/CV utama dan dilaporkan karena evaluasi stratified tidak cukup didukung.

Pemetaan nama berada di `config/symptom_mapping_id.json` dan `config/disease_mapping_id.json`. Nama yang tidak memiliki terjemahan menggunakan fallback yang ditandai *perlu ditinjau tenaga medis*. Semua terjemahan saat ini juga masih membutuhkan review klinis.

## 3. Dataset Modul B (Pima)

Urutan pemuatan: CSV lokal (`data/diabetes.csv`, `data/pima.csv`, atau `data/pima-indians-diabetes.csv`) → OpenML data ID 37 → URL publik alternatif → **DATA DEMO SINTETIS** bila semuanya gagal. Bila ingin melarang fallback demo, ubah pemanggilan `load_pima_local_or_remote(allow_demo=False)` di `train_screening.py`.

Nilai nol pada `Glucose`, `BloodPressure`, `SkinThickness`, `Insulin`, dan `BMI` diganti menjadi nilai hilang sebelum pemodelan. Median imputer ditempatkan dalam `Pipeline`, sehingga statistik imputasi dipelajari di train/fold, bukan dari test.

## 4. Training, evaluasi, aplikasi, dan tes

Jalankan dari folder proyek:

```bash
python train_symptom.py
python train_screening.py
python evaluate.py
pytest -q
streamlit run app.py
```

Training bisa memerlukan waktu karena hyperparameter tuning, CV, kalibrasi, dan permutation importance. Setelah selesai, Streamlit akan dibuka pada URL lokal yang dicetak Streamlit. Jangan mengekspos aplikasi ini ke internet atau memasukkan identitas pasien.

## 5. Keluaran training

Folder `outputs/` berisi:

- `symptom_model_comparison.csv`, `symptom_selected_model_test_metrics.csv`, `symptom_confusion_matrix.csv`, `symptom_top_confusions.csv`, `symptom_recall_per_disease.csv`, `symptom_reliability_bins.csv`, `symptom_robustness_tests.csv`, `symptom_permutation_importance.csv`, dan grafik EDA/kalibrasi/importance.
- `screening_model_comparison.csv`, `screening_selected_test_metrics.csv`, `screening_confusion_matrix.csv`, `screening_permutation_importance.csv`, `screening_reliability_bins.csv`, serta grafik ROC/kalibrasi/importance.
- laporan EDA dan metadata sumber data.

Folder `models/` menyimpan joblib dan metadata versi library/waktu training. Model gejala menyimpan statistik training publik untuk menghitung prevalensi dan pertanyaan lanjut; input pasien aplikasi tidak disimpan.

## 6. Desain evaluasi dan interpretasi

- Modul A memilih model berdasar macro-F1 cross-validation; DummyClassifier adalah baseline saja. Top-1/top-3, recall per kelas, confusion matrix, Brier multi-class, reliability bins, dan top confusion pairs dihitung pada test holdout setelah deduplikasi.
- Ambang `Belum cukup informasi` dihitung dari kuantil 10% probabilitas maksimum pada prediksi out-of-fold train. Itu hanya ambang statistik internal, bukan ambang diagnosis tervalidasi. Kurang dari tiga gejala selalu memicu penahanan dugaan.
- Uji robustness menilai penghapusan 20%, 35%, 50% fitur, penambahan gejala acak, dan penyisaan 1–3 gejala positif. Dataset yang bersih dapat memberi hasil sangat tinggi; ini tidak membuktikan kinerja pada pasien nyata.
- Modul B memilih model berdasar recall CV dan ROC-AUC sebagai metrik tambahan. Threshold dipilih dari OOF train dengan sasaran recall 80% bila dapat dicapai, lalu dilaporkan precision/specificity. Penurunan threshold umumnya meningkatkan recall dengan trade-off lebih banyak false positive.
- Kategori Rendah/Sedang/Tinggi didasarkan pada tertil probabilitas OOF train, bukan batas klinis. Output `predict_proba` perlu validasi kalibrasi di data lokal.

## 7. Privasi dan lapisan keselamatan

- Input pasien hanya diproses di memori/session; kode aplikasi tidak menulis masukan pasien ke disk/database dan tidak mengirimkannya ke pihak ketiga. Jangan mengaktifkan logging input atau merekam sesi jika aplikasi dimodifikasi.
- Informasi kesehatan termasuk data pribadi spesifik menurut UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi. Pernyataan ini bukan sertifikasi kepatuhan hukum; pengoperasian nyata perlu kajian hukum, keamanan, dan tata kelola. Sumber resmi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
- Red flag pada `config/red_flags.json` diproses oleh `safety.py` **sebelum** inferensi hasil, sehingga skor ML tidak dapat menimpa peringatan. Pemetaan kolom aktual tergantung versi dataset; kontrol red flag manual tetap disediakan. Semua aturan perlu review klinis.
- Pesan darurat: segera ke IGD atau hubungi 112 / 119. 119 adalah PSC darurat kesehatan Kemenkes. Layanan 112 diselenggarakan pemerintah daerah; cek ketersediaannya di wilayah setempat.
- Peringatan statis untuk bayi/anak kecil, kehamilan, lansia, dan penyakit kronis ditampilkan sepanjang aplikasi.

## 8. Keterbatasan dan validasi sebelum penggunaan nyata

Dataset gejala yang banyak beredar mempunyai 4.920 baris, 132 gejala, 41 kelas, dan sering terlihat tepat 120 sampel per kelas; data ini tampak sangat terstruktur dan tidak memuat usia, jenis kelamin, lama/keparahan gejala, anamnesis, pemeriksaan fisik atau laboratorium. Dataset Pima hanya mencakup perempuan keturunan Pima berusia 21 tahun ke atas. Keduanya belum tentu representatif untuk populasi Indonesia.

Sebelum pemakaian klinis, diperlukan: validasi prospektif/eksternal oleh dokter, evaluasi bias per subkelompok, kalibrasi di data lokal, audit keselamatan dan usability, keamanan/privasi, serta kajian pemenuhan regulasi alat kesehatan dan UU Pelindungan Data Pribadi. Prototipe ini tidak mengeluarkan obat/dosis dan tidak menggantikan diagnosis dokter.

## 9. Sumber

- Kaggle dataset (kaushil268): https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
- OpenML search: https://www.openml.org/search?type=data
- Kemenkes RI — tanda stroke & tindakan cepat: https://keslan.kemkes.go.id/view_artikel/4465/kenali-stroke-iskemik-dan-bertindak-cepat
- Kemenkes RI — PSC 119: https://kemkes.go.id/id/layanan/psc-119
- Komdigi — layanan 112: https://layanan112.komdigi.go.id/tentang
- WHO — diabetes: https://www.who.int/news-room/questions-and-answers/item/diabetes
- BPK RI — UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi: https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
```
