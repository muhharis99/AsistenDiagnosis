"""Use-case RME; otorisasi dan aturan bisnis ada di luar antarmuka."""
from __future__ import annotations
import hashlib, json
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from rme.models import (Anamnesis, AuditLog, Consent, Facility, Patient, ResumeAddendum, ResumeMedical,
                        ResumeRevision, Role, User, Visit, VitalSigns, utc_now)
from rme.schemas import PatientCreate, VisitCreate, AnamnesisInput, VitalSignsInput, ResumeInput, AddendumInput
from rme.security import SensitiveFieldCipher, append_audit, require_permission

class BusinessRuleError(ValueError): pass
class CorrectionWindowExpired(BusinessRuleError): pass

def ensure_reference_data(session: Session) -> None:
    roles = {"admin_pendaftaran":"Admin Pendaftaran","perawat":"Perawat","dokter":"Dokter (DPJP)","perekam_medis":"Perekam Medis","pimpinan":"Pimpinan","admin_sistem":"Admin Sistem"}
    for code,name in roles.items():
        if session.scalar(select(Role).where(Role.code==code)) is None: session.add(Role(code=code,name=name))
    if session.scalar(select(Facility).where(Facility.code=="KLINIK-DEMO-001")) is None:
        session.add(Facility(code="KLINIK-DEMO-001",name="Klinik Demo Sehat (FIKTIF)",is_demo=True))
    session.commit()

def _age(birth: date, today: date | None = None) -> int:
    now = today or date.today()
    return now.year - birth.year - ((now.month,now.day) < (birth.month,birth.day))

def create_patient(session: Session, user: User, cipher: SensitiveFieldCipher, data: PatientCreate, *, general_consent: bool, data_consent: bool=False, ai_consent: bool=False, family_consent: bool=False) -> Patient:
    require_permission(user,"patient:create"); require_permission(user,"consent:create")
    if not data.is_demo: raise BusinessRuleError("Fase 1 hanya menerima pasien fiktif.")
    if not general_consent: raise BusinessRuleError("Persetujuan umum wajib dicatat.")
    age = _age(data.birth_date)
    if age < 18 and not family_consent: raise BusinessRuleError("Persetujuan keluarga/wali diperlukan untuk pasien di bawah 18 tahun.")
    digest = cipher.lookup_digest(data.nik)
    if session.scalar(select(Patient.id).where(Patient.nik_lookup_hash==digest)) is not None: raise BusinessRuleError("NIK fiktif sudah terdaftar.")
    num = int(session.scalar(select(func.max(Patient.id))) or 0) + 1
    patient = Patient(medical_record_no=f"RM-D{num:06d}", name_ciphertext=cipher.encrypt(data.name),
        nik_ciphertext=cipher.encrypt(data.nik), nik_lookup_hash=digest, birth_date=data.birth_date, sex=data.sex,
        religion=data.religion, occupation=data.occupation, education=data.education, marital_status=data.marital_status,
        allergies=data.allergies, created_by=user.id, is_demo=True)
    session.add(patient); session.flush()
    consents = [("general",True,"Simulasi pasien fiktif"),("data_sharing",data_consent,"Simulasi pasien fiktif"),("ai_assist",ai_consent,"Simulasi pasien fiktif")]
    if age < 18: consents.append(("family_guardian",True,"Simulasi keluarga/wali"))
    for kind, granted, who in consents:
        session.add(Consent(patient_id=patient.id,consent_type=kind,granted=granted,granted_by=who,recorded_by=user.id,is_demo=True))
    append_audit(session,user,"patient.created","Patient",patient.id,{"no_rm":patient.medical_record_no,"is_demo":True,"consents":[x[0] for x in consents]})
    session.commit(); session.refresh(patient); return patient

def patient_view(patient: Patient, cipher: SensitiveFieldCipher, reveal_nik: bool=False, user: User | None=None) -> dict:
    """Representasi pasien dengan NIK dimasking kecuali aktor berizin."""
    if reveal_nik:
        if user is None:
            raise BusinessRuleError("NIK penuh hanya boleh ditampilkan melalui service dengan pemeriksaan RBAC.")
        require_permission(user, "patient:nik:reveal")
    nik = cipher.decrypt(patient.nik_ciphertext)
    return {"id":patient.id,"no_rm":patient.medical_record_no,"nama":cipher.decrypt(patient.name_ciphertext),
            "nik":nik if reveal_nik else nik[:4]+"********"+nik[-4:],"tanggal_lahir":patient.birth_date,
            "jenis_kelamin":patient.sex,"alergi":patient.allergies,"is_demo":patient.is_demo}

def get_patient(session: Session,user: User,patient_id:int,cipher:SensitiveFieldCipher,reveal_nik:bool=False)->dict:
    require_permission(user,"patient:read")
    if reveal_nik: require_permission(user,"patient:nik:reveal")
    p=session.get(Patient,patient_id)
    if not p: raise BusinessRuleError("Pasien tidak ditemukan.")
    append_audit(session,user,"patient.read","Patient",p.id,{"nik_revealed":reveal_nik})
    session.commit(); return patient_view(p,cipher,reveal_nik,user=user)

def search_patients(session:Session,user:User,query:str,cipher:SensitiveFieldCipher)->list[dict]:
    require_permission(user,"patient:read"); q=query.strip()
    if q.upper().startswith("RM-D"): rows=session.scalars(select(Patient).where(Patient.medical_record_no==q)).all()
    elif q.isdigit() and len(q)==16: rows=session.scalars(select(Patient).where(Patient.nik_lookup_hash==cipher.lookup_digest(q))).all()
    else: return []
    out=[]
    for p in rows:
        append_audit(session,user,"patient.read","Patient",p.id,{"lookup":"exact"})
        out.append(patient_view(p,cipher))
    session.commit(); return out

def create_visit(session:Session,user:User,data:VisitCreate)->Visit:
    require_permission(user,"visit:create")
    p=session.get(Patient,data.patient_id); f=session.scalar(select(Facility).where(Facility.code=="KLINIK-DEMO-001"))
    if not p or not f: raise BusinessRuleError("Pasien atau fasyankes demo tidak ditemukan.")
    if data.dpjp_user_id:
        d=session.get(User,data.dpjp_user_id)
        if not d or not d.active or d.role.code!="dokter": raise BusinessRuleError("DPJP harus akun dokter demo yang aktif.")
    n=int(session.scalar(select(func.max(Visit.id))) or 0)+1
    v=Visit(visit_number=f"KJ-D{datetime.now(timezone.utc):%Y%m%d}-{n:05d}",patient_id=p.id,facility_id=f.id,poli=data.poli,dpjp_user_id=data.dpjp_user_id,created_by=user.id,is_demo=True)
    session.add(v); session.flush(); append_audit(session,user,"visit.created","Visit",v.id,{"status":"arrived","poli":data.poli})
    session.commit(); session.refresh(v); return v

def list_visits(session:Session,user:User,status:str|None=None)->list[Visit]:
    require_permission(user,"visit:read"); q=select(Visit).order_by(Visit.arrived_at.desc())
    if status in ("arrived","in-progress","finished"): q=q.where(Visit.status==status)
    rows=session.scalars(q.limit(250)).all()
    append_audit(session,user,"visit.queue_read","VisitQueue","queue",{"filter":status or "all","count":len(rows)})
    session.commit(); return rows

def transition_visit(session:Session,user:User,visit_id:int,new_status:str)->Visit:
    v=session.get(Visit,visit_id)
    if not v: raise BusinessRuleError("Kunjungan tidak ditemukan.")
    transitions={"arrived":{"in-progress"},"in-progress":{"finished"},"finished":set()}
    if new_status not in transitions[v.status]: raise BusinessRuleError(f"Transisi status tidak valid: {v.status} -> {new_status}.")
    if new_status=="in-progress": require_permission(user,"visit:start"); v.started_at=utc_now()
    if new_status=="finished":
        require_permission(user,"visit:finish")
        resume=session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id==v.id))
        if not resume or resume.status!="final": raise BusinessRuleError("Resume harus difinalisasi dokter sebelum kunjungan selesai.")
        v.finished_at=utc_now()
    old=v.status; v.status=new_status; v.updated_at=utc_now()
    append_audit(session,user,"visit.status_changed","Visit",v.id,{"old":old,"new":new_status})
    session.commit(); session.refresh(v); return v

def save_anamnesis(session:Session,user:User,visit_id:int,data:AnamnesisInput)->Anamnesis:
    require_permission(user,"anamnesis:write")
    v=session.get(Visit,visit_id)
    if not v or v.status!="in-progress": raise BusinessRuleError("Anamnesis hanya dapat disimpan saat kunjungan in-progress.")
    row=session.scalar(select(Anamnesis).where(Anamnesis.visit_id==visit_id)); existing=row is not None
    vals=data.model_dump()
    if row is None: row=Anamnesis(visit_id=visit_id,created_by=user.id,is_demo=True,**vals); session.add(row)
    else:
        for k,val in vals.items(): setattr(row,k,val)
        row.updated_at=utc_now()
    session.flush(); append_audit(session,user,"anamnesis.saved","Anamnesis",row.id,{"fields":sorted(vals),"updated_existing":existing})
    session.commit(); session.refresh(row); return row

def save_vitals(session:Session,user:User,visit_id:int,data:VitalSignsInput)->VitalSigns:
    require_permission(user,"vitals:write")
    v=session.get(Visit,visit_id)
    if not v or v.status!="in-progress": raise BusinessRuleError("Tanda vital hanya dapat disimpan saat kunjungan in-progress.")
    vals=data.model_dump()
    vals["bmi"]=round(vals["weight_kg"]/((vals["height_cm"]/100)**2),2) if vals["weight_kg"] and vals["height_cm"] else None
    row=session.scalar(select(VitalSigns).where(VitalSigns.visit_id==visit_id))
    if row is None: row=VitalSigns(visit_id=visit_id,recorded_by=user.id,is_demo=True,**vals); session.add(row)
    else:
        for k,val in vals.items(): setattr(row,k,val)
        row.recorded_by=user.id; row.recorded_at=utc_now()
    session.flush(); append_audit(session,user,"vitals.saved","VitalSigns",row.id,{"fields":sorted(vals),"terminology":"TODO-VERIFIKASI"})
    session.commit(); session.refresh(row); return row

def save_resume_draft(session:Session,user:User,visit_id:int,data:ResumeInput)->ResumeMedical:
    require_permission(user,"resume:write")
    v=session.get(Visit,visit_id)
    if not v or v.status!="in-progress": raise BusinessRuleError("Draf resume hanya untuk kunjungan in-progress.")
    row=session.scalar(select(ResumeMedical).where(ResumeMedical.visit_id==visit_id))
    if row and row.status=="final": raise BusinessRuleError("Resume final tidak boleh ditimpa; gunakan koreksi/addendum.")
    vals=data.model_dump()
    if row is None: row=ResumeMedical(visit_id=visit_id,created_by=user.id,updated_by=user.id,is_demo=True,**vals); session.add(row)
    else:
        for k,val in vals.items(): setattr(row,k,val)
        row.version+=1; row.updated_by=user.id; row.updated_at=utc_now()
    session.flush(); append_audit(session,user,"resume.draft_saved","ResumeMedical",row.id,{"status":row.status,"version":row.version})
    session.commit(); session.refresh(row); return row

def finalize_resume(session:Session,user:User,resume_id:int)->ResumeMedical:
    require_permission(user,"resume:finalize")
    row=session.get(ResumeMedical,resume_id)
    if not row or row.status!="draft": raise BusinessRuleError("Resume draf tidak ditemukan atau sudah final.")
    v=session.get(Visit,row.visit_id)
    if not v or v.status!="in-progress": raise BusinessRuleError("Resume difinalisasi pada kunjungan in-progress.")
    if not all([row.subjective.strip(),row.objective.strip(),row.assessment.strip(),row.plan.strip()]): raise BusinessRuleError("Bagian S/O/A/P wajib diisi.")
    now=utc_now(); row.status="final"; row.finalized_at=now; row.signed_by=user.id; row.updated_by=user.id; row.updated_at=now
    row.signature_method="SIMULASI_BUKAN_TTE_TERSERTIFIKASI"
    raw=f"SIMULATED|{row.id}|{row.version}|{user.username}|{now.isoformat()}|{row.subjective}|{row.objective}|{row.assessment}|{row.plan}"
    row.signature_digest=hashlib.sha256(raw.encode()).hexdigest()
    append_audit(session,user,"resume.finalized","ResumeMedical",row.id,{"method":row.signature_method,"version":row.version})
    session.commit(); session.refresh(row); return row

def correct_final_resume(session:Session,user:User,resume_id:int,data:ResumeInput,reason:str,now:datetime|None=None)->ResumeMedical:
    require_permission(user,"resume:write")
    row=session.get(ResumeMedical,resume_id)
    if not row or row.status!="final" or not row.finalized_at: raise BusinessRuleError("Resume final tidak ditemukan.")
    if row.created_by!=user.id: raise BusinessRuleError("Koreksi dalam 2x24 jam hanya oleh pembuat data.")
    current=now or utc_now(); final=row.finalized_at
    if final.tzinfo is None: final=final.replace(tzinfo=timezone.utc)
    if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
    if current.astimezone(timezone.utc)-final.astimezone(timezone.utc)>timedelta(hours=48):
        raise CorrectionWindowExpired("Batas 2x24 jam lewat; buat addendum tanpa menimpa isi lama.")
    if len(reason.strip())<5: raise BusinessRuleError("Alasan koreksi wajib diisi.")
    vals=data.model_dump(); old={k:getattr(row,k) for k in vals}; version=row.version+1
    rev=ResumeRevision(resume_id=row.id,version=version,reason=reason.strip(),old_content_json=json.dumps(old,ensure_ascii=False,sort_keys=True),
        new_content_json=json.dumps(vals,ensure_ascii=False,sort_keys=True),changed_by=user.id,is_demo=True)
    session.add(rev)
    for k,val in vals.items(): setattr(row,k,val)
    row.version=version; row.updated_by=user.id; row.updated_at=current
    row.signature_method="SIMULASI_KOREKSI_BUKAN_TTE_TERSERTIFIKASI"
    row.signature_digest=hashlib.sha256(f"CORRECTION|{row.id}|{version}|{reason}|{current.isoformat()}".encode()).hexdigest()
    session.flush(); append_audit(session,user,"resume.corrected","ResumeMedical",row.id,{"version":version,"reason":reason})
    session.commit(); session.refresh(row); return row

def create_addendum(session:Session,user:User,resume_id:int,data:AddendumInput)->ResumeAddendum:
    require_permission(user,"resume:addendum")
    row=session.get(ResumeMedical,resume_id)
    if not row or row.status!="final": raise BusinessRuleError("Addendum hanya dapat ditambahkan ke resume final.")
    now=utc_now(); digest=hashlib.sha256(f"ADDENDUM|{row.id}|{user.username}|{now.isoformat()}|{data.content}|{data.reason}".encode()).hexdigest()
    add=ResumeAddendum(resume_id=row.id,content=data.content,reason=data.reason,created_by=user.id,created_at=now,signature_digest=digest,is_demo=True)
    session.add(add); session.flush(); append_audit(session,user,"resume.addendum_created","ResumeAddendum",add.id,{"resume_id":row.id,"reason":data.reason})
    session.commit(); session.refresh(add); return add
