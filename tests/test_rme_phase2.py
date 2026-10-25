"""Tes integrasi saran AI ke RME: consent, red flag, RBAC dan tidak ada diagnosis otomatis."""
from __future__ import annotations
from datetime import date
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sklearn.naive_bayes import BernoulliNB

os.environ.setdefault("APP_MODE","demo")
os.environ.setdefault("PII_ENCRYPTION_KEY",Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL","sqlite:///:memory:")

from rme.ai_service import AIConsentRequired, request_symptom_suggestion, review_ai_suggestion
from rme.db import build_engine, initialize_database, session_factory
from rme.models import AISuggestion, AISuggestionReview, AuditLog, Base, Consent, Patient, User, Visit
from rme.schemas import AISuggestionReviewInput, PatientCreate, VisitCreate
from rme.security import SensitiveFieldCipher
from rme.services import create_patient, create_visit, ensure_reference_data, transition_visit
from rme.bootstrap import seed_users


@pytest.fixture()
def context():
    engine=build_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory=session_factory(engine)
    with factory() as session:
        ensure_reference_data(session)
        seed_users(session)
    with factory() as session:
        users={u.username:u for u in session.scalars(select(User).options(joinedload(User.role))).all()}
    cipher=SensitiveFieldCipher(os.environ["PII_ENCRYPTION_KEY"])
    yield factory,cipher,users
    engine.dispose()


def make_patient(context, *, ai_consent: bool=True, birth_date: date=date(1990,1,1)):
    factory,cipher,users=context
    payload=PatientCreate(
        name="Pasien Fiktif Fase Dua",nik="3276010101901234",birth_date=birth_date,
        sex="Perempuan",religion="Belum diisi",occupation="Data demo",education="Data demo",
        marital_status="Belum diisi",allergies="Belum dikaji",is_demo=True,
    )
    with factory() as session:
        return create_patient(
            session,users["pendaftaran_demo"],cipher,payload,
            general_consent=True,data_consent=False,ai_consent=ai_consent,
        )


def make_active_visit(context, patient_id: int) -> int:
    factory,_,users=context
    with factory() as session:
        visit=create_visit(session,users["pendaftaran_demo"],VisitCreate(
            patient_id=patient_id,poli="Poli Umum",dpjp_user_id=users["dokter_demo"].id
        ))
        visit_id=visit.id
    with factory() as session:
        transition_visit(session,users["dokter_demo"],visit_id,"in-progress")
    return visit_id


def model_files(directory: Path) -> tuple[Path,Path]:
    directory.mkdir(parents=True,exist_ok=True)
    features=["itching","cough","fatigue","chest_pain"]
    X=pd.DataFrame([
        [1,0,1,0],[1,1,0,0],[1,0,0,0],[0,1,0,0],
        [0,1,1,0],[0,1,0,0],[0,0,1,0],[0,0,1,0],
        [0,0,0,1],[0,0,0,0],[1,1,1,0],[0,0,0,0],
    ],columns=features)
    y=pd.Series(["A","A","A","B","B","B","C","C","C","C","A","B"],name="prognosis")
    model=BernoulliNB().fit(X,y)
    bundle={"model":model,"feature_names":features,"classes":list(model.classes_),
            "X_train":X,"y_train":y,"confidence_threshold":0.0,"is_demo":True,"model_name":"test-BernoulliNB"}
    model_path=directory/"symptom_model.joblib"
    metadata_path=directory/"symptom_metadata.json"
    joblib.dump(bundle,model_path)
    metadata_path.write_text(json.dumps({
        "model":"test-BernoulliNB","trained_at_utc":"2026-10-25T00:00:00+00:00",
        "is_demo":True,"dataset":{"source":"test sintetis","is_demo":True},
        "selected_test_metrics":{"test_accuracy_top1":0.5}
    }),encoding="utf-8")
    return model_path,metadata_path


def test_red_flag_blocks_before_consent_or_model(context,tmp_path):
    factory,_,users=context
    patient=make_patient(context,ai_consent=False)
    visit_id=make_active_visit(context,patient.id)
    # File sengaja tidak ada: red flag tetap harus diproses sebelum model dimuat.
    with factory() as session:
        result=request_symptom_suggestion(
            session,users["dokter_demo"],visit_id,["chest_pain"],
            explicit_red_flags=["chest_pain"],model_path=tmp_path/"missing.joblib",metadata_path=tmp_path/"missing.json"
        )
    assert result["status"]=="red_flag_blocked"
    with factory() as session:
        assert session.scalar(select(AISuggestion.id).where(AISuggestion.visit_id==visit_id)) is None
        assert session.scalar(select(AuditLog.id).where(AuditLog.action=="ai.red_flag_blocked")) is not None



def test_ai_consent_required_before_model_loading(context,tmp_path):
    factory,_,users=context
    patient=make_patient(context,ai_consent=False)
    visit_id=make_active_visit(context,patient.id)
    with factory() as session, pytest.raises(AIConsentRequired,match="Persetujuan AI-assist"):
        request_symptom_suggestion(
            session,users["dokter_demo"],visit_id,["itching","cough","fatigue"],
            model_path=tmp_path/"missing.joblib",metadata_path=tmp_path/"missing.json"
        )
    with factory() as session:
        assert session.scalar(select(AISuggestion.id).where(AISuggestion.visit_id==visit_id)) is None
        assert session.scalar(select(AuditLog.id).where(AuditLog.action=="ai.consent_denied")) is not None


def test_too_few_symptoms_never_loads_model(context,tmp_path):
    factory,_,users=context
    patient=make_patient(context,ai_consent=True)
    visit_id=make_active_visit(context,patient.id)
    with factory() as session:
        result=request_symptom_suggestion(
            session,users["dokter_demo"],visit_id,["itching","cough"],
            model_path=tmp_path/"missing.joblib",metadata_path=tmp_path/"missing.json"
        )
    assert result["status"]=="insufficient_information"
    with factory() as session:
        assert session.scalar(select(AISuggestion.id).where(AISuggestion.visit_id==visit_id)) is None


def test_elderly_group_is_blocked_before_model(context,tmp_path):
    factory,_,users=context
    patient=make_patient(context,ai_consent=True,birth_date=date(1940,1,1))
    visit_id=make_active_visit(context,patient.id)
    with factory() as session:
        result=request_symptom_suggestion(
            session,users["dokter_demo"],visit_id,["itching","cough","fatigue"],
            model_path=tmp_path/"missing.joblib",metadata_path=tmp_path/"missing.json"
        )
    assert result["status"]=="special_population_blocked"
    assert "Lansia" in result["groups"]


def test_suggestion_is_saved_and_review_does_not_create_formal_diagnosis(context,tmp_path):
    factory,_,users=context
    patient=make_patient(context,ai_consent=True)
    visit_id=make_active_visit(context,patient.id)
    model_path,metadata_path=model_files(tmp_path/"models")
    with factory() as session:
        result=request_symptom_suggestion(
            session,users["dokter_demo"],visit_id,["itching","cough","fatigue"],
            model_path=model_path,metadata_path=metadata_path
        )
    assert result["status"]=="generated"
    assert len(result["candidates"])==3
    assert len(result["training_data_sha256"])==64
    assert len(result["model_artifact_sha256"])==64
    chosen=result["candidates"][0]["label"]
    with factory() as session:
        suggestion=session.get(AISuggestion,result["id"])
        assert suggestion is not None
        assert json.loads(suggestion.input_symptom_ids_json)==["itching","cough","fatigue"]
        review=review_ai_suggestion(
            session,users["dokter_demo"],suggestion.id,
            AISuggestionReviewInput(action="accepted_as_working_hypothesis",selected_candidate=chosen)
        )
        assert review.action=="accepted_as_working_hypothesis"
        visit=session.get(Visit,visit_id)
        assert visit.status=="in-progress"
        assert "diagnoses" not in Base.metadata.tables
        audit=session.scalar(select(AuditLog).where(AuditLog.action=="ai.suggestion_reviewed"))
        assert audit is not None
        assert "formal_diagnosis_created" in audit.details_json
        assert session.scalar(select(AISuggestionReview.id).where(AISuggestionReview.suggestion_id==suggestion.id)) is not None


def test_changed_or_ignored_ai_review_requires_reason():
    with pytest.raises(ValidationError):
        AISuggestionReviewInput(action="modified",modified_candidate="Kandidat dokter")
    with pytest.raises(ValidationError):
        AISuggestionReviewInput(action="ignored")
    changed=AISuggestionReviewInput(action="modified",modified_candidate="Catatan hipotesis dokter",reason="Alasan klinis")
    ignored=AISuggestionReviewInput(action="ignored",reason="Tidak sesuai anamnesis")
    assert changed.action=="modified" and ignored.action=="ignored"
