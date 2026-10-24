"""Skema Pydantic v2 untuk memvalidasi masukan RME."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class PatientCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=150)
    nik: str = Field(pattern=r"^\d{16}$")
    birth_date: date
    sex: str = Field(pattern=r"^(Laki-laki|Perempuan|Tidak diketahui)$")
    religion: str = Field(default="Belum diisi", max_length=60)
    occupation: str = Field(default="Belum diisi", max_length=100)
    education: str = Field(default="Belum diisi", max_length=100)
    marital_status: str = Field(default="Belum diisi", max_length=40)
    allergies: str = Field(default="Belum dikaji", max_length=2000)
    is_demo: bool = True
    @field_validator("birth_date")
    @classmethod
    def not_future(cls, value):
        if value > date.today(): raise ValueError("Tanggal lahir tidak boleh di masa depan.")
        return value
    @field_validator("is_demo")
    @classmethod
    def demo_only(cls, value):
        if value is not True: raise ValueError("Fase 1 hanya menerima is_demo=true.")
        return value

class VisitCreate(BaseModel):
    patient_id: int = Field(gt=0)
    poli: str = Field(min_length=2, max_length=100)
    dpjp_user_id: int | None = Field(default=None, gt=0)

class AnamnesisInput(BaseModel):
    chief_complaint: str = Field(min_length=2, max_length=4000)
    associated_symptoms: str = Field(default="", max_length=8000)
    personal_history: str = Field(default="", max_length=8000)
    family_history: str = Field(default="", max_length=8000)
    allergy_history: str = Field(default="Belum dikaji", max_length=4000)
    current_medications: str = Field(default="Belum dikaji", max_length=4000)

class VitalSignsInput(BaseModel):
    systolic_mmhg: int | None = Field(default=None, ge=40, le=300)
    diastolic_mmhg: int | None = Field(default=None, ge=20, le=200)
    pulse_per_min: int | None = Field(default=None, ge=20, le=250)
    respiration_per_min: int | None = Field(default=None, ge=4, le=80)
    temperature_c: float | None = Field(default=None, ge=25, le=45)
    spo2_percent: float | None = Field(default=None, ge=50, le=100)
    weight_kg: float | None = Field(default=None, ge=0.2, le=500)
    height_cm: float | None = Field(default=None, ge=20, le=250)
    @model_validator(mode="after")
    def check_bp(self):
        if self.systolic_mmhg is not None and self.diastolic_mmhg is not None and self.diastolic_mmhg >= self.systolic_mmhg:
            raise ValueError("Tekanan diastolik harus lebih rendah daripada sistolik.")
        return self

class ResumeInput(BaseModel):
    subjective: str = Field(default="", max_length=8000)
    objective: str = Field(default="", max_length=8000)
    assessment: str = Field(default="Belum ditetapkan dokter", max_length=8000)
    plan: str = Field(default="Perlu ditinjau dokter", max_length=8000)
    follow_up: str = Field(default="", max_length=8000)

class AddendumInput(BaseModel):
    content: str = Field(min_length=3, max_length=10000)
    reason: str = Field(min_length=5, max_length=2000)
