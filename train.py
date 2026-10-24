"""Pelatihan, tuning, pemilihan threshold, dan penyimpanan model.

Pemilihan model menggunakan recall cross-validation sebagai prioritas utama.
Threshold skrining dipilih dari prediksi out-of-fold data train agar target
sensitivitas minimum 80% dapat diusahakan tanpa memakai data test.
"""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from data import FEATURES, OUTPUT_DIR, PROJECT_DIR, generate_eda_artifacts, load_dataset, make_model_features

RANDOM_STATE = 42
TEST_SIZE = 0.20
CV_SPLITS = 5
TARGET_RECALL = 0.80
MODELS_DIR = PROJECT_DIR / "models"


def _package_version(package: str) -> str:
    """Ambil versi library tanpa menghentikan proses jika metadata tidak ada."""
    try:
        return version(package)
    except PackageNotFoundError:
        return "tidak diketahui"


def _make_pipeline(model: Any) -> Pipeline:
    """Bangun pipeline agar imputasi dan scaling dipelajari hanya dari fold train."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("model", model),
    ])


def _model_search_spaces() -> dict[str, tuple[Pipeline, dict[str, list[Any]]]]:
    """Definisikan minimal tiga model dengan balancing dan grid tuning."""
    logistic = _make_pipeline(LogisticRegression(
        class_weight="balanced", solver="liblinear", max_iter=2000, random_state=RANDOM_STATE
    ))
    random_forest = _make_pipeline(RandomForestClassifier(
        class_weight="balanced", random_state=RANDOM_STATE, n_jobs=1
    ))
    gradient_boosting = _make_pipeline(GradientBoostingClassifier(random_state=RANDOM_STATE))

    return {
        "Logistic Regression": (logistic, {
            # Regularisasi L2 default dipakai agar kompatibel pada scikit-learn 1.4+.
            "model__C": [0.1, 1.0, 10.0],
        }),
        "Random Forest": (random_forest, {
            "model__n_estimators": [200],
            "model__max_depth": [None, 8, 14],
            "model__min_samples_leaf": [1, 3, 5],
            "model__max_features": ["sqrt"],
        }),
        "Gradient Boosting": (gradient_boosting, {
            "model__n_estimators": [100, 200],
            "model__learning_rate": [0.03, 0.1],
            "model__max_depth": [1, 2],
            "model__min_samples_leaf": [3],
        }),
    }


def _oof_probabilities(
    estimator: Pipeline,
    model_name: str,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    cv: StratifiedKFold,
) -> np.ndarray:
    """Hitung probabilitas out-of-fold dan bobot kelas per fold bila diperlukan."""
    probabilities = np.full(len(y_train), np.nan, dtype=float)
    for train_indices, valid_indices in cv.split(x_train, y_train):
        fold_model = clone(estimator)
        x_fold = x_train.iloc[train_indices]
        y_fold = y_train.iloc[train_indices]
        fit_params: dict[str, Any] = {}
        if model_name == "Gradient Boosting":
            # GradientBoostingClassifier belum memiliki parameter class_weight.
            # Sample weight seimbang memberi penalti lebih besar kepada kelas minoritas.
            fit_params["model__sample_weight"] = compute_sample_weight("balanced", y_fold)
        fold_model.fit(x_fold, y_fold, **fit_params)
        probabilities[valid_indices] = fold_model.predict_proba(x_train.iloc[valid_indices])[:, 1]
    if np.isnan(probabilities).any():
        raise RuntimeError("Ada probabilitas OOF yang tidak terisi.")
    return probabilities


def choose_screening_threshold(
    y_true: pd.Series | np.ndarray,
    probabilities: np.ndarray,
    target_recall: float = TARGET_RECALL,
) -> dict[str, float]:
    """Pilih threshold dengan presisi terbesar dengan syarat recall >= target.

    Bila tidak ada threshold yang memenuhi target (kondisi sangat jarang),
    fungsi memilih threshold dengan recall tertinggi. Threshold ini adalah
    keputusan internal model, bukan ambang diagnosis klinis.
    """
    y_array = np.asarray(y_true, dtype=int)
    candidates = np.unique(np.concatenate(([0.0], probabilities, [1.0])))
    feasible: list[tuple[float, float, float]] = []
    all_results: list[tuple[float, float, float]] = []
    for threshold in candidates:
        prediction = (probabilities >= float(threshold)).astype(int)
        recall = float(recall_score(y_array, prediction, zero_division=0))
        precision = float(precision_score(y_array, prediction, zero_division=0))
        item = (precision, recall, float(threshold))
        all_results.append(item)
        if recall >= target_recall:
            feasible.append(item)
    chosen = max(feasible, key=lambda row: (row[0], row[1], row[2])) if feasible else max(
        all_results, key=lambda row: (row[1], row[0], row[2])
    )
    return {
        "threshold": float(chosen[2]),
        "oof_precision": float(chosen[0]),
        "oof_recall": float(chosen[1]),
        "target_recall": float(target_recall),
    }


def _risk_category_cutoffs(probabilities: np.ndarray) -> dict[str, float]:
    """Buat batas kategori skor relatif dari tertil probabilitas OOF data train."""
    lower, upper = np.quantile(probabilities, [1.0 / 3.0, 2.0 / 3.0])
    lower, upper = float(lower), float(upper)
    if upper <= lower:
        upper = min(1.0, lower + 1e-6)
    return {"low_upper": lower, "medium_upper": upper,
            "method": "tertil probabilitas out-of-fold data train; bukan ambang klinis"}


def _json_dump(path: Path, value: dict[str, Any]) -> None:
    """Simpan JSON dengan tipe NumPy dikonversi dengan aman."""
    def _convert(obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Tipe tidak dapat diserialisasi ke JSON: {type(obj)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, ensure_ascii=False, default=_convert)


def train() -> dict[str, Any]:
    """Jalankan seluruh eksperimen dan simpan artefak model."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frame = load_dataset()
    eda_summary = generate_eda_artifacts(frame, OUTPUT_DIR)
    x, y = make_model_features(frame)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    cv = StratifiedKFold(n_splits=CV_SPLITS, shuffle=True, random_state=RANDOM_STATE)

    searches: dict[str, GridSearchCV] = {}
    bundles: dict[str, dict[str, Any]] = {}
    comparison_rows: list[dict[str, Any]] = []

    for model_name, (pipeline, parameter_grid) in _model_search_spaces().items():
        print(f"\n=== Tuning {model_name} ===")
        search = GridSearchCV(
            estimator=pipeline,
            param_grid=parameter_grid,
            scoring={
                "recall": "recall",
                "precision": "precision",
                "roc_auc": "roc_auc",
                "f1": "f1",
            },
            refit="recall",
            cv=cv,
            n_jobs=-1,
            return_train_score=False,
            error_score="raise",
        )
        fit_kwargs: dict[str, Any] = {}
        if model_name == "Gradient Boosting":
            fit_kwargs["model__sample_weight"] = compute_sample_weight("balanced", y_train)
        search.fit(x_train, y_train, **fit_kwargs)
        searches[model_name] = search

        oof_probabilities = _oof_probabilities(search.best_estimator_, model_name, x_train, y_train, cv)
        threshold_info = choose_screening_threshold(y_train, oof_probabilities)
        category_cutoffs = _risk_category_cutoffs(oof_probabilities)
        cv_results = search.cv_results_
        best_index = int(search.best_index_)
        comparison_rows.append({
            "model": model_name,
            "cv_recall_mean": float(cv_results["mean_test_recall"][best_index]),
            "cv_recall_std": float(cv_results["std_test_recall"][best_index]),
            "cv_precision_mean_at_0_5": float(cv_results["mean_test_precision"][best_index]),
            "cv_f1_mean_at_0_5": float(cv_results["mean_test_f1"][best_index]),
            "cv_roc_auc_mean": float(cv_results["mean_test_roc_auc"][best_index]),
            "threshold_oof": threshold_info["threshold"],
            "oof_recall_at_threshold": threshold_info["oof_recall"],
            "oof_precision_at_threshold": threshold_info["oof_precision"],
            "best_params": json.dumps(search.best_params_, ensure_ascii=False),
        })
        bundles[model_name] = {
            "model_name": model_name,
            "pipeline": search.best_estimator_,
            "threshold": threshold_info["threshold"],
            "threshold_selection": threshold_info,
            "category_cutoffs": category_cutoffs,
            "reference_values": x_train.median(numeric_only=True).to_dict(),
            "feature_names": FEATURES,
            "best_params": search.best_params_,
            "cv_metrics": {
                "recall_mean": float(cv_results["mean_test_recall"][best_index]),
                "precision_mean_at_0_5": float(cv_results["mean_test_precision"][best_index]),
                "f1_mean_at_0_5": float(cv_results["mean_test_f1"][best_index]),
                "roc_auc_mean": float(cv_results["mean_test_roc_auc"][best_index]),
            },
        }
        print(
            f"Recall CV={comparison_rows[-1]['cv_recall_mean']:.3f}; "
            f"ROC-AUC CV={comparison_rows[-1]['cv_roc_auc_mean']:.3f}; "
            f"threshold OOF={threshold_info['threshold']:.3f}"
        )

    comparison = pd.DataFrame(comparison_rows).sort_values(
        ["cv_recall_mean", "cv_roc_auc_mean"], ascending=False
    ).reset_index(drop=True)
    comparison.to_csv(OUTPUT_DIR / "model_comparison_cv.csv", index=False)
    best_name = str(comparison.iloc[0]["model"])
    best_bundle = bundles[best_name]

    # Latih ulang model terpilih pada seluruh data train (bukan data test).
    # GridSearchCV sudah fit pada train; model ini tidak pernah melihat test.
    joblib.dump(bundles, MODELS_DIR / "trained_models.joblib")
    joblib.dump(best_bundle, MODELS_DIR / "best_model.joblib")

    metadata = {
        "project": "Pima Diabetes Early Screening",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": frame.attrs.get("data_source", "tidak diketahui"),
        "dataset_rows": int(len(frame)),
        "target_distribution": {str(int(k)): int(v) for k, v in y.value_counts().sort_index().items()},
        "features": FEATURES,
        "target": "Outcome",
        "split": {"test_size": TEST_SIZE, "random_state": RANDOM_STATE, "stratified": True},
        "cross_validation": {"type": "StratifiedKFold", "n_splits": CV_SPLITS, "shuffle": True, "random_state": RANDOM_STATE},
        "selection_rule": "Prioritas recall CV; ROC-AUC sebagai pemecah seri",
        "selected_model": best_name,
        "selected_model_params": best_bundle["best_params"],
        "selected_model_cv_metrics": best_bundle["cv_metrics"],
        "all_models_cv_metrics": {name: bundle["cv_metrics"] for name, bundle in bundles.items()},
        "cv_comparison_rows": comparison_rows,
        "selected_threshold": best_bundle["threshold"],
        "threshold_strategy": f"Presisi terbaik dengan recall OOF minimal {TARGET_RECALL:.0%}; hanya untuk prioritas skrining",
        "category_cutoffs": best_bundle["category_cutoffs"],
        "versions": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "pandas": _package_version("pandas"),
            "numpy": _package_version("numpy"),
            "joblib": _package_version("joblib"),
        },
        "clinical_notice": "Eksperimen riset pada dataset Pima; bukan alat diagnosis dan belum divalidasi untuk populasi Indonesia.",
    }
    _json_dump(MODELS_DIR / "metadata.json", metadata)
    _json_dump(OUTPUT_DIR / "training_summary.json", {**metadata, "eda": eda_summary})

    print("\n=== Ringkasan CV (urut recall lalu ROC-AUC) ===")
    print(comparison[["model", "cv_recall_mean", "cv_precision_mean_at_0_5", "cv_roc_auc_mean", "threshold_oof"]].to_string(index=False))
    print(f"\nModel terpilih: {best_name}")
    print(f"Artefak disimpan di: {MODELS_DIR}")
    print(f"Jumlah data test disiapkan: {len(x_test)}; label test belum dipakai saat tuning.")
    return metadata


if __name__ == "__main__":
    train()
