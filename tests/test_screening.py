"""Tes dasar dataset numerik: nol dimaknai sebagai missing pada fitur tertentu."""
import numpy as np

from data import make_demo_pima_data, prepare_pima_features


def test_pima_zero_values_become_missing_in_features() -> None:
    frame = make_demo_pima_data(n=100)
    frame.loc[0, "Glucose"] = 0
    X, y = prepare_pima_features(frame)
    assert np.isnan(X.loc[0, "Glucose"])
    assert len(X) == len(y)
