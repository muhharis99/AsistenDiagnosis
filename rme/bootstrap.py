"""Seeder akun dan data sintetis."""
from __future__ import annotations
from datetime import date
from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from rme.models import Role, User, Patient
from rme.schemas import PatientCreate, VisitCreate
from rme.security import SensitiveFieldCipher, hash_password
from rme.services import ensure_reference_data, create_patient, create_visit

DEMO_ACCOUNTS = (
 ("pendaftaran_demo","DemoDaftar!2026","Petugas Pendaftaran Demo","admin_pendaftaran"),
 ("perawat_demo","DemoPerawat!2026","Perawat Demo","perawat"),
 ("dokter_demo","DemoDokter!2026","Dokter DPJP Demo","dokter"),
 ("rekam_medis_demo","DemoRekam!2026","Perekam Medis Demo","perekam_medis"),
 ("pimpinan_demo","DemoPimpinan!2026","Pimpinan Demo","pimpinan"),
 ("admin_sistem_demo","DemoSistem!2026","Admin Sistem Demo","admin_sistem"),
)

def seed_users(session: Session) -> None:
    roles={r.code:r for r in session.scalars(select(Role)).all()}
    for username,password,name,role in DEMO_ACCOUNTS:
        if session.scalar(select(User.id).where(User.username==username)) is None:
            session.add(User(username=username,password_hash=hash_password(password),display_name=name,role_id=roles[role].id,active=True,is_demo=True))
    session.commit()

def seed_demo_patients(session: Session,cipher:SensitiveFieldCipher,count:int=3) -> None:
    if session.scalar(select(Patient.id).limit(1)) is not None: return
    fake=Faker("id_ID"); fake.seed_instance(20261025)
    registration=session.scalar(select(User).options(joinedload(User.role)).where(User.username=="pendaftaran_demo"))
    doctor=session.scalar(select(User).options(joinedload(User.role)).where(User.username=="dokter_demo"))
    for patient_index in range(count):
        nik=str(fake.unique.random_int(min=1_000_000_000_000_000,max=9_999_999_999_999_999))
        born=fake.date_of_birth(minimum_age=18,maximum_age=80)
        p=create_patient(session,registration,cipher,PatientCreate(name=fake.name(),nik=nik,birth_date=born,
            sex=fake.random_element(elements=("Laki-laki","Perempuan")),occupation="Data demo",education="Data demo",
            religion="Belum diisi",marital_status="Belum diisi",allergies="Belum dikaji",is_demo=True),
            general_consent=True,data_consent=False,ai_consent=(patient_index == 0))
        create_visit(session,registration,VisitCreate(patient_id=p.id,poli=fake.random_element(elements=("Poli Umum","Poli Penyakit Dalam")),dpjp_user_id=doctor.id))
