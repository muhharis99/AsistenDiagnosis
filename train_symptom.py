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
