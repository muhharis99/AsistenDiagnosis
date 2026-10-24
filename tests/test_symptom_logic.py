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
