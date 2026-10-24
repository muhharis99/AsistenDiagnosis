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
