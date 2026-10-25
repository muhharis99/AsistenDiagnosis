"""Registry pembacaan ICD-10 edisi 2010 dengan status sumber eksplisit."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TERMINOLOGY_PATH = ROOT / "data" / "icd10_seed_2010.csv"
SUPPORTED_EDITION = "2010"


@dataclass(frozen=True)
class ICD10Term:
    code: str
    display: str
    edition: str
    status: str
    source_url: str
    source_note: str

    @property
    def verified_source(self) -> bool:
        return self.status == "source_verified" and self.edition == SUPPORTED_EDITION


def load_icd10_terms(path: Path | None = None) -> list[ICD10Term]:
    """Load term rows; never infer a term from a disease label or an AI candidate."""
    source = path or DEFAULT_TERMINOLOGY_PATH
    terms: list[ICD10Term] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"code", "display", "edition", "status", "source_url", "source_note"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("Kolom registry ICD-10 tidak lengkap.")
        for row in reader:
            code = (row.get("code") or "").strip().upper()
            display = (row.get("display") or "").strip()
            edition = (row.get("edition") or "").strip()
            status = (row.get("status") or "").strip().lower()
            source_url = (row.get("source_url") or "").strip()
            source_note = (row.get("source_note") or "").strip()
            if not code or not display:
                continue
            if len(code) > 12 or not all(ch.isalnum() or ch == "." for ch in code):
                raise ValueError(f"Format kode ICD-10 tidak valid dalam registry: {code!r}")
            terms.append(ICD10Term(code, display, edition, status, source_url, source_note))
    codes = [term.code for term in terms]
    if len(codes) != len(set(codes)):
        raise ValueError("Registry ICD-10 memiliki kode duplikat; perbaiki sebelum digunakan.")
    return terms


def verified_icd10_terms(path: Path | None = None) -> list[ICD10Term]:
    """Only source-reviewed terms are selectable; this starter file is not a complete catalogue."""
    return sorted((t for t in load_icd10_terms(path) if t.verified_source), key=lambda t: t.code)


def get_verified_icd10_term(code: str, path: Path | None = None) -> ICD10Term | None:
    wanted = (code or "").strip().upper()
    return next((term for term in verified_icd10_terms(path) if term.code == wanted), None)


def search_icd10(query: str, path: Path | None = None, *, include_unverified: bool = False) -> list[ICD10Term]:
    needle = (query or "").strip().casefold()
    if not needle:
        return []
    terms = load_icd10_terms(path)
    if not include_unverified:
        terms = [term for term in terms if term.verified_source]
    return [term for term in terms if needle in term.code.casefold() or needle in term.display.casefold()]
