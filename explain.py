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
