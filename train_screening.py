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
