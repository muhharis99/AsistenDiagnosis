"""Siapkan secret lokal, database, akun, dan pasien fiktif untuk demonstrasi."""
from __future__ import annotations
import os, sys
from pathlib import Path
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
ENV=ROOT/".env"

def main()->int:
    if not ENV.exists():
        key=Fernet.generate_key().decode()
        ENV.write_text("APP_MODE=demo\nDATABASE_URL=sqlite:///./instance/rme_demo.db\nPII_ENCRYPTION_KEY="+key+"\nIDLE_TIMEOUT_MINUTES=20\nFACILITY_NAME=Klinik Demo Sehat (FIKTIF)\nSATUSEHAT_MODE=mock\n",encoding="utf-8")
        try: ENV.chmod(0o600)
        except OSError: pass
        print("File .env dan encryption key lokal dibuat. Simpan backup key secara aman.")
    from dotenv import load_dotenv
    load_dotenv(ENV,override=True)
    from rme.settings import Settings
    from rme.db import build_engine,initialize_database,session_factory
    from rme.security import SensitiveFieldCipher
    from rme.services import ensure_reference_data
    from rme.bootstrap import seed_users,seed_demo_patients,DEMO_ACCOUNTS
    settings=Settings.from_env()
    (ROOT/"instance").mkdir(exist_ok=True)
    engine=build_engine(settings.database_url); initialize_database(engine)
    factory=session_factory(engine)
    with factory() as session:
        ensure_reference_data(session); seed_users(session); seed_demo_patients(session,SensitiveFieldCipher(settings.pii_encryption_key))
    print("\nRME demo siap: seluruh data pasien fiktif; hanya untuk localhost.")
    for username,password,name,role in DEMO_ACCOUNTS: print(f"{role:18} {username:20} {password}")
    print("Jalankan: streamlit run rme_app.py")
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"Inisialisasi gagal: {exc}",file=sys.stderr); raise
