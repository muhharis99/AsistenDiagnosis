"""UI RME rawat jalan fase 1. Seluruh data pasien wajib fiktif."""
from __future__ import annotations
import time
import html
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from rme.settings import Settings
from rme.db import build_engine,initialize_database,session_factory
from rme.models import User,Role,Patient,Visit,Anamnesis,VitalSigns,ResumeMedical,ResumeAddendum,AuditLog,ModelRegistry
from rme.schemas import PatientCreate,VisitCreate,AnamnesisInput,VitalSignsInput,ResumeInput,AddendumInput
from rme.security import LoginRateLimiter,AuthenticationError,SensitiveFieldCipher,append_audit,authenticate,require_permission,verify_audit_chain
from rme.ui_ai import render_ai_panel, render_ai_evaluation
from rme.ui_phase3 import render_diagnosis_panel, render_satusehat_panel
from rme.services import BusinessRuleError,create_patient,create_visit,list_visits,transition_visit,save_anamnesis,save_vitals,save_resume_draft,finalize_resume,correct_final_resume,create_addendum,patient_view,search_patients,get_patient,CorrectionWindowExpired

st.set_page_config(page_title="RME Rawat Jalan — Prototipe",page_icon="🩺",layout="wide")
DISCLAIMER="PROTOTIPE — DATA FIKTIF. Bukan untuk pelayanan klinis nyata. AI hanya memberi saran dan tidak menetapkan diagnosis resmi. Tanda tangan di sini simulasi, bukan TTE tersertifikasi."

@st.cache_resource
def runtime():
    cfg=Settings.from_env(); engine=build_engine(cfg.database_url); initialize_database(engine)
    return session_factory(engine),SensitiveFieldCipher(cfg.pii_encryption_key),cfg

def wib(value):
    if value is None: return "—"
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M WIB")

def audit(session,user,action,kind,eid,details=None):
    append_audit(session,user,action,kind,eid,details or {}); session.commit()

def show_banner(cfg,user):
    st.markdown("<div style='background:#8b1e1e;color:white;padding:10px;border-radius:6px;font-weight:800;text-align:center'>PROTOTIPE — DATA FIKTIF — BUKAN UNTUK PELAYANAN KLINIS NYATA</div>",unsafe_allow_html=True)
    a,b,c=st.columns([2,2,1]); a.write("**"+cfg.facility_name+"**"); b.write(f"{user.display_name} · {user.role.name}"); c.write("DEMO / MOCK\n"+datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M WIB"))
    st.caption(DISCLAIMER)

def login(factory):
    if "limiter" not in st.session_state: st.session_state.limiter=LoginRateLimiter()
    st.title("Masuk ke RME Demo")
    with st.form("login"):
        username=st.text_input("Nama pengguna"); password=st.text_input("Kata sandi",type="password")
        go=st.form_submit_button("Masuk",type="primary")
    if go:
        with factory() as session:
            try:
                user=authenticate(session,username,password,st.session_state.limiter,time.time())
                audit(session,user,"auth.login","User",user.id,{"role":user.role.code})
                st.session_state.user_id=user.id; st.session_state.last_activity=time.time(); st.rerun()
            except AuthenticationError as e: st.error(str(e))
    with st.expander("Akun demonstrasi lokal"):
        st.code("pendaftaran_demo / DemoDaftar!2026\nperawat_demo / DemoPerawat!2026\ndokter_demo / DemoDokter!2026\nrekam_medis_demo / DemoRekam!2026\npimpinan_demo / DemoPimpinan!2026\nadmin_sistem_demo / DemoSistem!2026")
        st.caption("Akun ini hanya untuk localhost; jangan gunakan pada server terbuka.")

def current_user(factory,cfg):
    uid=st.session_state.get("user_id")
    if not uid: return None
    if time.time()-st.session_state.get("last_activity",time.time())>cfg.idle_timeout_minutes*60:
        st.session_state.clear(); st.warning("Sesi berakhir karena tidak aktif."); st.rerun()
    st.session_state.last_activity=time.time()
    with factory() as session:
        user=session.scalar(select(User).options(joinedload(User.role)).where(User.id==uid,User.active.is_(True)))
        if user: audit(session,user,"auth.session_access","User",user.id,{"screen":"rme_app"}); return user
    st.session_state.clear(); return None

def dashboard(factory,user):
    st.header("Dasbor")
    require_permission(user,"dashboard:read")
    with factory() as s:
        all_v=s.query(Visit).count(); arrived=s.query(Visit).filter(Visit.status=="arrived").count()
        active=s.query(Visit).filter(Visit.status=="in-progress").count(); finished=s.query(Visit).filter(Visit.status=="finished").count()
        audit(s,user,"dashboard.read","Dashboard","summary",{"counts_only":True})
    a,b,c,d=st.columns(4); a.metric("Antrean",arrived); b.metric("Pemeriksaan",active); c.metric("Selesai",finished); d.metric("Kunjungan demo",all_v)
    st.info("SATUSEHAT masih placeholder. Fase 1 tidak mengirim data ke pihak ketiga.")

def registration(factory,user,cipher):
    st.header("Pendaftaran")
    try:
        require_permission(user,"patient:create"); require_permission(user,"visit:create"); require_permission(user,"consent:create")
    except PermissionError as e: st.error(str(e)); return
    with factory() as s: doctors=s.scalars(select(User).join(Role).where(Role.code=="dokter",User.active.is_(True))).all()
    doctor_options={f"{d.display_name} ({d.username})":d.id for d in doctors}
    with st.form("reg_form"):
        name=st.text_input("Nama fiktif"); nik=st.text_input("NIK fiktif 16 digit",max_chars=16)
        a,b=st.columns(2); dob=a.date_input("Tanggal lahir",value=date(1990,1,1),min_value=date(1900,1,1),max_value=date.today(),format="DD/MM/YYYY"); sex=b.selectbox("Jenis kelamin",["Tidak diketahui","Laki-laki","Perempuan"])
        a,b=st.columns(2); religion=a.selectbox("Agama",["Belum diisi","Islam","Kristen","Katolik","Hindu","Buddha","Konghucu","Lainnya"]); job=b.text_input("Pekerjaan",value="Data demo")
        a,b=st.columns(2); edu=a.selectbox("Pendidikan",["Belum diisi","SD","SMP","SMA/SMK","Diploma","Sarjana","Lainnya"]); marital=b.selectbox("Status perkawinan",["Belum diisi","Belum kawin","Kawin","Cerai hidup","Cerai mati"])
        allergy=st.text_input("Alergi",value="Belum dikaji")
        st.markdown("**Persetujuan simulasi**")
        general=st.checkbox("Persetujuan umum (wajib)"); share=st.checkbox("Persetujuan pembukaan/pemanfaatan data (dicatat terpisah)"); ai=st.checkbox("Persetujuan AI-assist (belum mengaktifkan AI pada Fase 1)"); guardian=st.checkbox("Persetujuan keluarga/wali bila usia di bawah 18 tahun")
        poli=st.selectbox("Poli",["Poli Umum","Poli Penyakit Dalam","Poli Anak","Poli Kebidanan","Poli Gigi","Lainnya"])
        dpjp_label=st.selectbox("DPJP",list(doctor_options)) if doctor_options else None
        submit=st.form_submit_button("Daftarkan dan buat antrean",type="primary")
    if submit:
        try:
            data=PatientCreate(name=name,nik=nik,birth_date=dob,sex=sex,religion=religion,occupation=job or "Belum diisi",education=edu,marital_status=marital,allergies=allergy or "Belum dikaji",is_demo=True)
            with factory() as s:
                p=create_patient(s,user,cipher,data,general_consent=general,data_consent=share,ai_consent=ai,family_consent=guardian)
                v=create_visit(s,user,VisitCreate(patient_id=p.id,poli=poli,dpjp_user_id=doctor_options.get(dpjp_label) if dpjp_label else None))
            st.success(f"Pasien {p.medical_record_no} dan antrean {v.visit_number} berhasil dibuat.")
        except Exception as e: st.error(f"Pendaftaran tidak disimpan: {e}")
    st.subheader("Pencarian pasien")
    with st.form("search_patient"):
        q=st.text_input("Cari No. RM atau NIK fiktif exact"); go=st.form_submit_button("Cari")
    if go:
        try:
            with factory() as s: hits=search_patients(s,user,q,cipher)
            if hits: st.dataframe(pd.DataFrame(hits),use_container_width=True,hide_index=True)
            else: st.info("Tidak ditemukan. Untuk privasi, pencarian nama bebas belum disediakan.")
        except Exception as e: st.error(str(e))

def queue_page(factory,user):
    st.header("Antrean Kunjungan"); flt=st.selectbox("Status",["Semua","arrived","in-progress","finished"])
    try:
        with factory() as s: rows=list_visits(s,user,None if flt=="Semua" else flt); vals=[]
        with factory() as s:
            for v in rows:
                p=s.get(Patient,v.patient_id); vals.append({"ID":v.id,"No. Kunjungan":v.visit_number,"No. RM":p.medical_record_no if p else "—","Poli":v.poli,"Status":v.status,"Tiba (WIB)":wib(v.arrived_at)})
        if vals: st.dataframe(pd.DataFrame(vals),use_container_width=True,hide_index=True)
        else: st.info("Belum ada kunjungan.")
        for v in rows:
            with st.expander(f"{v.visit_number} · {v.poli} · {v.status}"):
                if v.status=="arrived":
                    if st.button("Mulai pemeriksaan",key=f"start_{v.id}"):
                        with factory() as s: transition_visit(s,user,v.id,"in-progress")
                        st.success("Kunjungan menjadi in-progress."); st.rerun()
    except Exception as e: st.error(str(e))

def examination(factory,user,cipher):
    st.header("Pemeriksaan / SOAP")
    try:
        with factory() as s: rows=list_visits(s,user,"in-progress")
    except Exception as e: st.error(str(e)); return
    if not rows: st.info("Tidak ada kunjungan in-progress. Mulai dari antrean."); return
    options={}
    with factory() as s:
        for v in rows:
            p=s.get(Patient,v.patient_id)
            options[f"{cipher.decrypt(p.name_ciphertext)} · {p.medical_record_no} · {v.visit_number}"]=v.id
    chosen=st.selectbox("Pasien aktif",list(options)); vid=options[chosen]
    with factory() as s:
        v=s.get(Visit,vid); p=s.get(Patient,v.patient_id); a=s.scalar(select(Anamnesis).where(Anamnesis.visit_id==vid)); t=s.scalar(select(VitalSigns).where(VitalSigns.visit_id==vid)); r=s.scalar(select(ResumeMedical).where(ResumeMedical.visit_id==vid))
        dp=s.get(User,v.dpjp_user_id) if v.dpjp_user_id else None
        audit(s,user,"visit.clinical_read","Visit",vid,{"has_anamnesis":bool(a),"has_vitals":bool(t),"has_resume":bool(r)})
        s.commit()
    age=date.today().year-p.birth_date.year-((date.today().month,date.today().day)<(p.birth_date.month,p.birth_date.day))
    # Semua nilai dinamis di-escape sebelum dirender dengan HTML kustom untuk mencegah injeksi markup.
    safe_name=html.escape(cipher.decrypt(p.name_ciphertext))
    raw_nik=cipher.decrypt(p.nik_ciphertext)
    safe_nik=html.escape(raw_nik[:4]+"********"+raw_nik[-4:])
    safe_sex=html.escape(p.sex)
    safe_rm=html.escape(p.medical_record_no)
    safe_allergies=html.escape(p.allergies)
    safe_status=html.escape(v.status)
    safe_dpjp=html.escape(dp.display_name if dp else "Belum ditetapkan")
    safe_poli=html.escape(v.poli)
    st.markdown(f"""<div style="border:1px solid #ccd7e2;border-left:6px solid #315b7d;background:white;padding:14px;border-radius:8px"><b>{safe_name}</b> · {age} tahun · {safe_sex}<br>No. RM: {safe_rm} · NIK: {safe_nik}<br><span style="color:#a32626"><b>Alergi:</b> {safe_allergies}</span><br>Status: {safe_status} · DPJP: {safe_dpjp} · Poli: {safe_poli}</div>""",unsafe_allow_html=True)
    tabs=st.tabs(["Anamnesis","Fisik & Tanda Vital","Penunjang","Asesmen & Diagnosis","Rencana","Resume"])
    with tabs[0]:
        try:
            require_permission(user,"anamnesis:write")
            with st.form(f"anamnesis_{vid}"):
                cc=st.text_area("Keluhan utama *",a.chief_complaint if a else "")
                sx=st.text_area("Gejala penyerta",a.associated_symptoms if a else "")
                ph=st.text_area("Riwayat penyakit pribadi",a.personal_history if a else "")
                fh=st.text_area("Riwayat penyakit keluarga",a.family_history if a else "")
                al=st.text_area("Riwayat alergi",a.allergy_history if a else p.allergies)
                meds=st.text_area("Obat yang digunakan (catatan)",a.current_medications if a else "Belum dikaji")
                save=st.form_submit_button("Simpan anamnesis")
            if save:
                with factory() as s: save_anamnesis(s,user,vid,AnamnesisInput(chief_complaint=cc,associated_symptoms=sx,personal_history=ph,family_history=fh,allergy_history=al,current_medications=meds))
                st.success("Anamnesis tersimpan."); st.rerun()
        except PermissionError as e: st.warning(str(e))
    with tabs[1]:
        try:
            require_permission(user,"vitals:write")
            with st.form(f"vitals_{vid}"):
                a1,a2,a3=st.columns(3); sys=a1.number_input("Sistolik mmHg",40,300,int(t.systolic_mmhg or 120)); dia=a2.number_input("Diastolik mmHg",20,200,int(t.diastolic_mmhg or 80)); pulse=a3.number_input("Nadi/menit",20,250,int(t.pulse_per_min or 80))
                a1,a2,a3=st.columns(3); resp=a1.number_input("Napas/menit",4,80,int(t.respiration_per_min or 18)); temp=a2.number_input("Suhu °C",25.0,45.0,float(t.temperature_c or 36.7),step=0.1); spo=a3.number_input("SpO₂ %",50.0,100.0,float(t.spo2_percent if t and t.spo2_percent else 98.0),step=0.5)
                a1,a2=st.columns(2); weight=a1.number_input("Berat kg",0.2,500.0,float(t.weight_kg if t and t.weight_kg else 60.0)); height=a2.number_input("Tinggi cm",20.0,250.0,float(t.height_cm if t and t.height_cm else 160.0))
                save=st.form_submit_button("Simpan tanda vital")
            if save:
                data=VitalSignsInput(systolic_mmhg=sys,diastolic_mmhg=dia,pulse_per_min=pulse,respiration_per_min=resp,temperature_c=temp,spo2_percent=spo,weight_kg=weight,height_cm=height)
                with factory() as s: saved=save_vitals(s,user,vid,data)
                st.success(f"Tanda vital tersimpan. IMT demo: {saved.bmi} kg/m²; LOINC/UCUM masih TODO-VERIFIKASI."); st.rerun()
        except Exception as e: st.error(str(e))
    with tabs[2]: st.info("Placeholder. Pemeriksaan laboratorium/radiologi di luar lingkup Fase 1.")
    with tabs[3]:
        render_ai_panel(factory,user,v,p,age)
        render_diagnosis_panel(factory,user,vid)
    with tabs[4]: st.info("Rencana dicatat pada resume. Tidak ada peresepan/dosis otomatis.")
    with tabs[5]:
        st.caption("Tanda tangan pada fase ini hanya simulasi hash; bukan TTE tersertifikasi.")
        if r and r.status=="final":
            st.success(f"Resume FINAL versi {r.version} · {wib(r.finalized_at)}")
            st.write("**S**",r.subjective); st.write("**O**",r.objective); st.write("**A**",r.assessment); st.write("**P**",r.plan); st.write("**Tindak lanjut**",r.follow_up)
            st.code(f"{r.signature_method}\n{r.signature_digest}")
            try:
                require_permission(user,"resume:addendum")
                with st.form(f"addendum_{r.id}"):
                    content=st.text_area("Isi addendum"); reason=st.text_input("Alasan addendum"); add=st.form_submit_button("Tambah addendum")
                if add:
                    with factory() as s: create_addendum(s,user,r.id,AddendumInput(content=content,reason=reason))
                    st.success("Addendum ditambahkan tanpa menimpa resume lama."); st.rerun()
            except PermissionError: pass
        else:
            try:
                require_permission(user,"resume:write")
                with st.form(f"resume_{vid}"):
                    subj=st.text_area("S — Subjective *",r.subjective if r else (a.chief_complaint if a else ""))
                    obj=st.text_area("O — Objective *",r.objective if r else "")
                    assess=st.text_area("A — Assessment (catatan dokter, belum ICD-10) *",r.assessment if r else "Belum ditetapkan dokter")
                    plan=st.text_area("P — Plan *",r.plan if r else "Perlu ditinjau dokter")
                    fu=st.text_area("Tindak lanjut",r.follow_up if r else "")
                    save=st.form_submit_button("Simpan draf")
                if save:
                    with factory() as s: save_resume_draft(s,user,vid,ResumeInput(subjective=subj,objective=obj,assessment=assess,plan=plan,follow_up=fu))
                    st.success("Draf disimpan."); st.rerun()
                if r:
                    with st.form(f"final_{r.id}"):
                        confirm=st.checkbox("Saya dokter DPJP dan telah meninjau isi resume.")
                        final=st.form_submit_button("Finalisasi dan tanda tangan simulasi",type="primary")
                    if final:
                        if not confirm: st.error("Konfirmasi dokter wajib.")
                        else:
                            with factory() as s:
                                fin=finalize_resume(s,user,r.id); transition_visit(s,user,vid,"finished")
                            st.success("Resume difinalisasi dan kunjungan selesai. Simulasi bukan TTE tersertifikasi."); st.rerun()
            except PermissionError as e: st.warning(str(e))

def resumes(factory,user,cipher):
    """Daftar resume, koreksi berbatas waktu, dan addendum tanpa overwrite."""
    st.header("Resume Medis")
    try:
        require_permission(user,"resume:read")
        with factory() as s:
            rows=s.scalars(select(ResumeMedical).order_by(ResumeMedical.updated_at.desc()).limit(200)).all()
            data=[]
            for item in rows:
                v=s.get(Visit,item.visit_id); p=s.get(Patient,v.patient_id) if v else None
                if p:
                    data.append({"ID":item.id,"Status":item.status,"Versi":item.version,"No. RM":p.medical_record_no,
                                 "Nama":cipher.decrypt(p.name_ciphertext),"Kunjungan":v.visit_number,"Poli":v.poli,
                                 "Waktu WIB":wib(item.updated_at)})
                    append_audit(s,user,"resume.list_read","ResumeMedical",item.id,{"status":item.status})
            s.commit()
        if not data:
            st.info("Belum ada resume.")
            return
        st.dataframe(pd.DataFrame(data),use_container_width=True,hide_index=True)
        selected=st.selectbox("Pilih resume",data,format_func=lambda x:f"#{x['ID']} · {x['Nama']} · {x['Status']}")
        with factory() as s:
            r=s.get(ResumeMedical,selected["ID"])
            addenda=s.scalars(select(ResumeAddendum).where(ResumeAddendum.resume_id==selected["ID"]).order_by(ResumeAddendum.id)).all()
            append_audit(s,user,"resume.read","ResumeMedical",r.id,{"status":r.status,"version":r.version})
            s.commit()
        st.write("**S — Subjective**",r.subjective)
        st.write("**O — Objective**",r.objective)
        st.write("**A — Assessment**",r.assessment)
        st.write("**P — Plan**",r.plan)
        st.write("**Tindak lanjut**",r.follow_up)
        if r.status=="final":
            st.warning("Resume FINAL. Tanda tangan adalah simulasi hash, bukan TTE tersertifikasi.")
            st.code(f"{r.signature_method}\\n{r.signature_digest}")
            # Koreksi hanya ditawarkan kepada pembuat; service tetap memvalidasi izin dan jendela 48 jam.
            if r.created_by==user.id:
                try:
                    require_permission(user,"resume:write")
                    with st.form(f"resume_correction_{r.id}"):
                        st.markdown("**Koreksi dalam 2x24 jam**")
                        subj=st.text_area("S koreksi",r.subjective)
                        obj=st.text_area("O koreksi",r.objective)
                        assess=st.text_area("A koreksi",r.assessment)
                        plan=st.text_area("P koreksi",r.plan)
                        follow=st.text_area("Tindak lanjut koreksi",r.follow_up)
                        reason=st.text_input("Alasan koreksi wajib")
                        submit=st.form_submit_button("Simpan koreksi")
                    if submit:
                        with factory() as s:
                            revised=correct_final_resume(s,user,r.id,ResumeInput(subjective=subj,objective=obj,assessment=assess,plan=plan,follow_up=follow),reason)
                        st.success(f"Koreksi disimpan; versi sekarang {revised.version}, revisi lama dipertahankan."); st.rerun()
                except PermissionError:
                    pass
                except Exception as exc:
                    st.error(str(exc))
            try:
                require_permission(user,"resume:addendum")
                with st.form(f"resume_addendum_{r.id}"):
                    st.markdown("**Addendum (tanpa menimpa isi final)**")
                    content=st.text_area("Isi addendum")
                    reason=st.text_input("Alasan addendum")
                    submit_add=st.form_submit_button("Tambahkan addendum")
                if submit_add:
                    with factory() as s: create_addendum(s,user,r.id,AddendumInput(content=content,reason=reason))
                    st.success("Addendum ditambahkan dan audit dicatat."); st.rerun()
            except PermissionError:
                pass
            if addenda:
                st.markdown("### Riwayat addendum")
                for item in addenda:
                    st.markdown(f"**{wib(item.created_at)}** — {item.content}  \\nAlasan: {item.reason}")
        else:
            st.info("Resume masih draf. Buka menu Pemeriksaan untuk melanjutkan.")
    except Exception as e:
        st.error(str(e))

def administration(factory,user):
    st.header("Administrasi & audit")
    with factory() as s:
        try:
            require_permission(user,"user:read")
            users=s.scalars(select(User).options(joinedload(User.role)).order_by(User.id)).all()
            st.dataframe(pd.DataFrame([{"username":u.username,"nama":u.display_name,"peran":u.role.code,"aktif":u.active,"is_demo":u.is_demo} for u in users]),use_container_width=True)
        except PermissionError: st.info("Peran tidak dapat melihat pengguna.")
        try:
            require_permission(user,"audit:read")
            logs=s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100)).all()
            st.dataframe(pd.DataFrame([{"id":x.id,"waktu UTC":x.occurred_at.isoformat(),"aktor":x.actor_username,"aksi":x.action,"entitas":x.entity_type,"id entitas":x.entity_id,"hash":x.entry_hash[:16]+"…"} for x in logs]),use_container_width=True)
            good,bad=verify_audit_chain(s)
            st.success("Audit hash-chain valid.") if good else st.error(f"Audit tidak valid mulai event {bad}.")
        except PermissionError: st.info("Peran tidak dapat melihat audit trail.")

def main():
    st.markdown("<style>.stApp{background:#f6f8fb} [data-testid='stSidebar']{background:#eef2f7} button{min-height:40px}</style>",unsafe_allow_html=True)
    try: factory,cipher,cfg=runtime()
    except Exception as e: st.error(f"Runtime belum siap: {e}"); st.code("python scripts/init_demo.py\nstreamlit run rme_app.py"); st.stop()
    st.title("RME Rawat Jalan — Prototipe Fase 5")
    if not st.session_state.get("user_id"): login(factory); return
    user=current_user(factory,cfg)
    if not user: login(factory); return
    show_banner(cfg,user)
    menu=["Dasbor","Pendaftaran","Antrean Kunjungan","Pemeriksaan","Resume Medis","Integrasi SATUSEHAT","Evaluasi Model","Administrasi","Tentang"]
    pick=st.sidebar.radio("Menu RME",menu); st.sidebar.caption(f"{user.username} · {user.role.name}")
    if st.sidebar.button("Keluar"):
        with factory() as s: audit(s,user,"auth.logout","User",user.id,{})
        st.session_state.clear(); st.rerun()
    if pick=="Dasbor": dashboard(factory,user)
    elif pick=="Pendaftaran": registration(factory,user,cipher)
    elif pick=="Antrean Kunjungan": queue_page(factory,user)
    elif pick=="Pemeriksaan": examination(factory,user,cipher)
    elif pick=="Resume Medis": resumes(factory,user,cipher)
    elif pick=="Administrasi": administration(factory,user)
    elif pick=="Integrasi SATUSEHAT": render_satusehat_panel(factory,user,cipher)
    elif pick=="Evaluasi Model": render_ai_evaluation()
    else:
        st.header("Tentang & Keterbatasan")
        st.write("Tujuan: demonstrasi pendaftaran, antrean, pemeriksaan SOAP, audit trail, dan panel saran AI pada data fiktif.")
        st.write("Bukan untuk penggunaan klinis. Enkripsi field-level diterapkan pada nama dan NIK; akses ke berkas database harus dibatasi terpisah.")
        st.markdown("[Permenkes 24/2022 tentang Rekam Medis](https://jdih.kemkes.go.id/documents/peraturan-menteri-kesehatan-nomor-24-tahun-2022) · [UU 27/2022 PDP](https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022) · [Playbook Resume Medis Rawat Jalan SATUSEHAT](https://satusehat.kemkes.go.id/platform/docs/id/interoperability/rme-rawat-jalan/)")
        st.caption("Belum ada klaim kepatuhan regulasi, validasi klinis AI, integrasi SATUSEHAT, atau TTE tersertifikasi. Semua saran AI tetap harus ditinjau dokter.")

if __name__=="__main__": main()
