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
