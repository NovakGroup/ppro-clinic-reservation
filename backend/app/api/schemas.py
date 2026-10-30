"""DTO prezentační vrstvy: validace formátu vstupu a tvar JSON odpovědí."""
from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field


class ScheduleOut(BaseModel):
    day_of_week: int = Field(description="0 = pondělí ... 6 = neděle")
    start: str
    end: str
    location: str
    external: bool


class DoctorOut(BaseModel):
    id: int
    name: str
    specialization: str
    schedules: list[ScheduleOut]


class ProcedureOut(BaseModel):
    id: int
    code: str
    name: str
    points: int


class PatientIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    birth_year: int
    insurance_id: str = Field(min_length=1, max_length=20)
    insurance_code: str = Field(min_length=3, max_length=3)
    phone: str | None = Field(default=None, max_length=30)


class PatientOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    birth_year: int
    insurance_id: str
    insurance_code: str
    phone: str | None
    cancellations: int
    no_shows: int
    unreliable: bool


class AppointmentIn(BaseModel):
    doctor_id: int
    patient_id: int
    date: date
    time: time
    duration: int = 15
    reason: str = Field(default="", max_length=255)
    reschedule_from_id: int | None = None


class AppointmentOut(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    date: date
    time: str
    end_time: str
    duration: int
    status: str
    reason: str
    cancelled_by: str | None
    cancellation_reason: str | None
    patient_called: bool
    rescheduled_to_id: int | None
    has_visit: bool


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class VisitItemIn(BaseModel):
    procedure_id: int
    count: int = Field(ge=1, le=10)


class VisitIn(BaseModel):
    note: str = Field(default="", max_length=5000)
    items: list[VisitItemIn]


class VisitItemOut(BaseModel):
    procedure_id: int
    code: str
    name: str
    count: int
    points: int


class VisitOut(BaseModel):
    appointment_id: int
    saved: bool
    note: str
    items: list[VisitItemOut]
    total_points: int


class SlotOut(BaseModel):
    time: str
    state: str
    appointment_id: int | None


class DayOut(BaseModel):
    date: date
    works: bool
    absent: bool
    slots: list[SlotOut]


class ReportRowOut(BaseModel):
    insurance_code: str
    insurance_name: str
    code: str
    name: str
    points: int
    count: int
    total: int


class ReportOut(BaseModel):
    month: str
    doctor_id: int | None
    rows: list[ReportRowOut]
    total_points: int
    visits: int
    patients: int
    cancelled_or_no_show: int


class AbsenceIn(BaseModel):
    doctor_id: int
    date: date
    reason: str | None = Field(default=None, max_length=255)


class AbsenceOut(BaseModel):
    id: int
    doctor_id: int
    date: date
    reason: str
