"""Tes fondasi RME: RBAC, privasi, consent, state machine, resume, audit."""
from datetime import date, timedelta, timezone
import os
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("APP_MODE","demo")
os.environ.setdefault("PII_ENCRYPTION_KEY",Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL","sqlite:///:memory:")

from rme.db import build_engine,initialize_database,session_factory
from rme.models import User,Patient,Consent,AuditLog,ResumeMedical
from rme.schemas import PatientCreate,VisitCreate,AnamnesisInput,VitalSignsInput,ResumeInput
from rme.security import SensitiveFieldCipher,append_audit,verify_audit_chain,AuthorizationError
from rme.services import (ensure_reference_data,create_patient,create_visit,transition_visit,save_anamnesis,save_vitals,
                          save_resume_draft,finalize_resume,correct_final_resume,CorrectionWindowExpired,BusinessRuleError)
from rme.bootstrap import seed_users
from sqlalchemy.orm import joinedload

@pytest.fixture()
def ctx():
    eng=build_engine("sqlite:///:memory:"); initialize_database(eng); fac=session_factory(eng)
    with fac() as s: ensure_reference_data(s); seed_users(s)
    with fac() as s:
        users={u.username:u for u in s.scalars(select(User).options(joinedload(User.role))).all()}
    cipher=SensitiveFieldCipher(os.environ["PII_ENCRYPTION_KEY"])
    yield fac,cipher,users
    eng.dispose()

def patient_payload(nik="3276010101901234",born=date(1990,1,1)):
    return PatientCreate(name="Nama Pasien Fiktif",nik=nik,birth_date=born,sex="Perempuan",is_demo=True)

def create_p(ctx):
    fac,cipher,u=ctx
    with fac() as s: return create_patient(s,u["pendaftaran_demo"],cipher,patient_payload(),general_consent=True)

def in_progress(ctx,pid):
    fac,_,u=ctx
    with fac() as s: v=create_visit(s,u["pendaftaran_demo"],VisitCreate(patient_id=pid,poli="Poli Umum",dpjp_user_id=u["dokter_demo"].id)); vid=v.id
    with fac() as s: transition_visit(s,u["dokter_demo"],vid,"in-progress")
    return vid

def test_sensitive_fields_encrypted_and_nik_masked(ctx):
    fac,cipher,u=ctx; p=create_p(ctx)
    with fac() as s:
        row=s.get(Patient,p.id)
        assert "Nama Pasien Fiktif" not in row.name_ciphertext and "3276010101901234" not in row.nik_ciphertext
        assert cipher.decrypt(row.nik_ciphertext)=="3276010101901234"
        assert row.is_demo

def test_registration_requires_general_and_family_consent(ctx):
    fac,cipher,u=ctx
    with fac() as s, pytest.raises(BusinessRuleError,match="Persetujuan umum"):
        create_patient(s,u["pendaftaran_demo"],cipher,patient_payload(),general_consent=False)
    minor=patient_payload("3276010101141234",date.today().replace(year=date.today().year-12))
    with fac() as s, pytest.raises(BusinessRuleError,match="keluarga/wali"):
        create_patient(s,u["pendaftaran_demo"],cipher,minor,general_consent=True)
    with fac() as s:
        p=create_patient(s,u["pendaftaran_demo"],cipher,minor,general_consent=True,family_consent=True)
        kinds={c.consent_type:c.granted for c in s.scalars(select(Consent).where(Consent.patient_id==p.id)).all()}
        assert kinds=={"general":True,"data_sharing":False,"ai_assist":False,"family_guardian":True}

def test_rbac_denies_nurse_patient_registration_and_nik_reveal(ctx):
    fac,cipher,u=ctx
    with fac() as s, pytest.raises(AuthorizationError):
        create_patient(s,u["perawat_demo"],cipher,patient_payload("3276010101901235"),general_consent=True)
    p=create_p(ctx)
    from rme.services import get_patient
    with fac() as s, pytest.raises(AuthorizationError):
        get_patient(s,u["perawat_demo"],p.id,cipher,reveal_nik=True)

def test_vitals_validation_and_visit_state_machine(ctx):
    fac,cipher,u=ctx; p=create_p(ctx); vid=in_progress(ctx,p.id)
    with pytest.raises(ValueError,match="diastolik"):
        VitalSignsInput(systolic_mmhg=110,diastolic_mmhg=120)
    with fac() as s:
        save_anamnesis(s,u["dokter_demo"],vid,AnamnesisInput(chief_complaint="Batuk sejak kemarin"))
        v=save_vitals(s,u["perawat_demo"],vid,VitalSignsInput(systolic_mmhg=120,diastolic_mmhg=80,pulse_per_min=80,respiration_per_min=18,temperature_c=36.7,spo2_percent=98,weight_kg=60,height_cm=160))
        assert round(v.bmi,2)==23.44
    with fac() as s, pytest.raises(BusinessRuleError,match="Resume harus difinalisasi"):
        transition_visit(s,u["dokter_demo"],vid,"finished")

def test_final_resume_correction_window_and_finalization(ctx):
    fac,cipher,u=ctx; p=create_p(ctx); vid=in_progress(ctx,p.id)
    data=ResumeInput(subjective="Keluhan fiktif",objective="Pemeriksaan fiktif",assessment="Asesmen dokter",plan="Rencana untuk ditinjau dokter")
    with fac() as s: r=save_resume_draft(s,u["dokter_demo"],vid,data); rid=r.id
    with fac() as s: final=finalize_resume(s,u["dokter_demo"],rid); finalized=final.finalized_at
    assert final.signature_method=="SIMULASI_BUKAN_TTE_TERSERTIFIKASI"
    with fac() as s:
        rev=correct_final_resume(s,u["dokter_demo"],rid,data,"Koreksi salah catat",now=finalized+timedelta(hours=24))
        assert rev.version==2
    with fac() as s, pytest.raises(CorrectionWindowExpired,match="addendum"):
        correct_final_resume(s,u["dokter_demo"],rid,data,"Terlambat koreksi",now=finalized+timedelta(hours=49))

def test_audit_chain_valid_and_database_append_only(ctx):
    fac,cipher,u=ctx
    with fac() as s:
        append_audit(s,u["pendaftaran_demo"],"test.action","Test","1",{"no_pii":True}); s.commit()
        assert verify_audit_chain(s)==(True,None)
        with pytest.raises(IntegrityError): s.execute(update(AuditLog).values(action="tampered"))
        s.rollback()
    with fac() as s:
        with pytest.raises(IntegrityError): s.execute(delete(AuditLog))
        s.rollback()
    with fac() as s: assert verify_audit_chain(s)==(True,None)

def test_only_demo_rows_and_status_transitions(ctx):
    fac,cipher,u=ctx
    from pydantic import ValidationError
    with pytest.raises(ValidationError,match="is_demo=true"):
        PatientCreate(name="Bukan demo",nik="3276010101901235",birth_date=date(1990,1,1),sex="Laki-laki",is_demo=False)
    p=create_p(ctx)
    with fac() as s: v=create_visit(s,u["pendaftaran_demo"],VisitCreate(patient_id=p.id,poli="Poli Umum")); vid=v.id
    with fac() as s, pytest.raises(BusinessRuleError,match="Transisi status tidak valid"):
        transition_visit(s,u["dokter_demo"],vid,"finished")
