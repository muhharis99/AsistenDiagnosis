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
