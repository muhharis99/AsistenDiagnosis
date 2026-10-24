"""Konfigurasi runtime; mode selain demo ditolak."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

@dataclass(frozen=True)
class Settings:
    app_mode: str
    database_url: str
    pii_encryption_key: str
    idle_timeout_minutes: int = 20
    facility_name: str = "Klinik Demo Sehat (FIKTIF)"

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("APP_MODE", "demo").strip().lower()
        if mode != "demo":
            raise RuntimeError("Fase 1 hanya mengizinkan APP_MODE=demo; mode produksi ditolak.")
        key = os.getenv("PII_ENCRYPTION_KEY", "").strip()
        if not key:
            raise RuntimeError("PII_ENCRYPTION_KEY belum tersedia. Jalankan python scripts/init_demo.py.")
        timeout = int(os.getenv("IDLE_TIMEOUT_MINUTES", "20"))
        if timeout < 1 or timeout > 240:
            raise ValueError("IDLE_TIMEOUT_MINUTES harus berada pada rentang 1–240.")
        default_db = f"sqlite:///{(ROOT / 'instance' / 'rme_demo.db').as_posix()}"
        return cls(
            app_mode=mode,
            database_url=os.getenv("DATABASE_URL", default_db),
            pii_encryption_key=key,
            idle_timeout_minutes=timeout,
            facility_name=os.getenv("FACILITY_NAME", "Klinik Demo Sehat (FIKTIF)"),
        )
