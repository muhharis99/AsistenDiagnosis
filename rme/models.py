"""Model database SQLAlchemy untuk RME fase 1."""
from __future__ import annotations
from datetime import date, datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    users: Mapped[list["User"]] = relationship(back_populates="role")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    role: Mapped[Role] = relationship(back_populates="users")

class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("medical_record_no", name="uq_patient_rm"),
        UniqueConstraint("nik_lookup_hash", name="uq_patient_nik_hash"),
        CheckConstraint("is_demo = true", name="ck_patient_demo_only"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    medical_record_no: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nik_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nik_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(String(24), nullable=False)
    religion: Mapped[str] = mapped_column(String(60), nullable=False, default="Belum diisi")
    occupation: Mapped[str] = mapped_column(String(100), nullable=False, default="Belum diisi")
    education: Mapped[str] = mapped_column(String(100), nullable=False, default="Belum diisi")
    marital_status: Mapped[str] = mapped_column(String(40), nullable=False, default="Belum diisi")
    allergies: Mapped[str] = mapped_column(Text, nullable=False, default="Belum dikaji")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (CheckConstraint("is_demo = true", name="ck_consent_demo_only"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    text_version: Mapped[str] = mapped_column(String(40), nullable=False, default="demo-v1")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("visit_number", name="uq_visit_number"),
        CheckConstraint("status IN ('arrived','in-progress','finished')", name="ck_visit_status"),
        CheckConstraint("is_demo = true", name="ck_visit_demo_only"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False)
    poli: Mapped[str] = mapped_column(String(100), nullable=False)
    dpjp_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="arrived", index=True)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class Anamnesis(Base):
    __tablename__ = "anamneses"
    __table_args__ = (CheckConstraint("is_demo = true", name="ck_anamnesis_demo_only"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), unique=True, nullable=False)
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    associated_symptoms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personal_history: Mapped[str] = mapped_column(Text, nullable=False, default="")
    family_history: Mapped[str] = mapped_column(Text, nullable=False, default="")
    allergy_history: Mapped[str] = mapped_column(Text, nullable=False, default="Belum dikaji")
    current_medications: Mapped[str] = mapped_column(Text, nullable=False, default="Belum dikaji")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class VitalSigns(Base):
    __tablename__ = "vital_signs"
    __table_args__ = (CheckConstraint("is_demo = true", name="ck_vitals_demo_only"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), unique=True, nullable=False)
    systolic_mmhg: Mapped[int | None] = mapped_column(Integer)
    diastolic_mmhg: Mapped[int | None] = mapped_column(Integer)
    pulse_per_min: Mapped[int | None] = mapped_column(Integer)
    respiration_per_min: Mapped[int | None] = mapped_column(Integer)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    spo2_percent: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    bmi: Mapped[float | None] = mapped_column(Float)
    terminology_status: Mapped[str] = mapped_column(String(60), nullable=False, default="TODO-VERIFIKASI")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class ResumeMedical(Base):
    __tablename__ = "medical_resumes"
    __table_args__ = (
        CheckConstraint("status IN ('draft','final')", name="ck_resume_status"),
        CheckConstraint("is_demo = true", name="ck_resume_demo_only"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), unique=True, nullable=False)
    subjective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assessment: Mapped[str] = mapped_column(Text, nullable=False, default="Belum ditetapkan dokter")
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="Perlu ditinjau dokter")
    follow_up: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    signature_method: Mapped[str | None] = mapped_column(String(70))
    signature_digest: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class ResumeRevision(Base):
    __tablename__ = "resume_revisions"
    __table_args__ = (CheckConstraint("is_demo = true", name="ck_resume_revision_demo_only"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("medical_resumes.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    old_content_json: Mapped[str] = mapped_column(Text, nullable=False)
    new_content_json: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class ResumeAddendum(Base):
    __tablename__ = "resume_addenda"
    __table_args__ = (CheckConstraint("is_demo = true", name="ck_resume_addendum_demo_only"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("medical_resumes.id", ondelete="RESTRICT"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    signature_method: Mapped[str] = mapped_column(String(70), nullable=False, default="SIMULASI_BUKAN_TTE_TERSERTIFIKASI")
    signature_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_username: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

class ModelRegistry(Base):
    __tablename__ = "model_registry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="TODO-VERIFIKASI")
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DEMO_UNVALIDATED")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

Index("ix_visit_status_arrived", Visit.status, Visit.arrived_at)
Index("ix_audit_entity", AuditLog.entity_type, AuditLog.entity_id)


class AISuggestion(Base):
    """Saran model yang terpisah dari diagnosis resmi; semua contoh wajib fiktif."""
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint("is_demo = true", name="ck_ai_suggestion_demo_only"),
        CheckConstraint("status IN ('generated','insufficient_information')", name="ck_ai_suggestion_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False, index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(160), nullable=False)
    model_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    training_data_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_symptom_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_candidates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    explanations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    followup_questions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="generated")
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    max_probability: Mapped[float] = mapped_column(Float, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class AISuggestionReview(Base):
    """Keputusan dokter atas saran AI; bukan diagnosis final atau kode ICD."""
    __tablename__ = "ai_suggestion_reviews"
    __table_args__ = (
        CheckConstraint("is_demo = true", name="ck_ai_suggestion_review_demo_only"),
        CheckConstraint("action IN ('accepted_as_working_hypothesis','modified','ignored')", name="ck_ai_suggestion_review_action"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("ai_suggestions.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_candidate: Mapped[str | None] = mapped_column(String(180))
    modified_candidate: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

Index("ix_ai_suggestion_visit_created", AISuggestion.visit_id, AISuggestion.created_at)
Index("ix_ai_suggestion_review_suggestion_created", AISuggestionReview.suggestion_id, AISuggestionReview.created_at)


class Diagnosis(Base):
    """Diagnosis yang dimasukkan secara manual oleh dokter, terpisah dari saran AI."""
    __tablename__ = "diagnoses"
    __table_args__ = (
        UniqueConstraint("visit_id", "icd10_code", name="uq_diagnosis_visit_icd10"),
        CheckConstraint("status IN ('provisional','confirmed')", name="ck_diagnosis_status"),
        CheckConstraint("is_demo = true", name="ck_diagnosis_demo_only"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False, index=True)
    clinical_label: Mapped[str] = mapped_column(Text, nullable=False)
    icd10_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    icd10_display: Mapped[str] = mapped_column(String(255), nullable=False)
    icd10_edition: Mapped[str] = mapped_column(String(12), nullable=False, default="2010")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="provisional")
    diagnosis_set_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    code_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    code_verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    code_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    code_verification_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OutboxSync(Base):
    """Resource FHIR demo yang menunggu/sudah disimulasikan; tidak melakukan transmisi jaringan."""
    __tablename__ = "outbox_sync"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        CheckConstraint("status IN ('queued','mock_accepted','failed','blocked')", name="ck_outbox_status"),
        CheckConstraint("is_demo = true", name="ck_outbox_demo_only"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_summary: Mapped[str | None] = mapped_column(String(500))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    last_attempt_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


Index("ix_diagnosis_visit_status", Diagnosis.visit_id, Diagnosis.status)
Index("ix_outbox_status_created", OutboxSync.status, OutboxSync.created_at)
