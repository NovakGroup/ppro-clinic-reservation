"""ORM modely (datová vrstva). Schéma v databázi vytvářejí migrace Alembic."""
from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppointmentStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelledBy(str, enum.Enum):
    PATIENT = "PATIENT"  # pacient se omluvil – počítá se do statistiky rušení
    CLINIC = "CLINIC"  # přeplánováno ordinací (např. nemoc lékaře) – nepočítá se


class Doctor(Base):
    __tablename__ = "doctor"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(20), default="MUDr.")
    specialization: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    schedules: Mapped[list[DoctorSchedule]] = relationship(back_populates="doctor", order_by="DoctorSchedule.day_of_week")

    @property
    def full_name(self) -> str:
        return f"{self.title} {self.first_name} {self.last_name}"


class DoctorSchedule(Base):
    """Ordinační hodiny: jeden řádek = jedno časové okno v daném dni týdne."""

    __tablename__ = "doctor_schedule"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_schedule_day"),
        CheckConstraint("start_time < end_time", name="ck_schedule_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"))
    day_of_week: Mapped[int] = mapped_column(Integer)  # 0 = pondělí ... 6 = neděle
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    location: Mapped[str] = mapped_column(String(120))

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class Patient(Base):
    __tablename__ = "patient"
    __table_args__ = (CheckConstraint("birth_year BETWEEN 1900 AND 2100", name="ck_patient_birth_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    birth_year: Mapped[int] = mapped_column(Integer)
    insurance_id: Mapped[str] = mapped_column(String(11), unique=True)  # rodné číslo XXXXXX/XXXX
    insurance_code: Mapped[str] = mapped_column(String(3))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Appointment(Base):
    """Rezervace termínu.

    Překryv aktivních rezervací jednoho lékaře zakazuje exclusion constraint
    `ex_appointment_no_overlap` (viz migrace) – pravidlo tedy platí i při ručním zásahu do DB.
    """

    __tablename__ = "appointment"
    __table_args__ = (CheckConstraint("start_at < end_at", name="ck_appointment_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status"), default=AppointmentStatus.PLANNED
    )
    reason: Mapped[str] = mapped_column(String(255))
    cancelled_by: Mapped[CancelledBy | None] = mapped_column(Enum(CancelledBy, name="cancelled_by"))
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    patient_called: Mapped[bool] = mapped_column(Boolean, default=False)
    rescheduled_to_id: Mapped[int | None] = mapped_column(ForeignKey("appointment.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()
    visit: Mapped[Visit | None] = relationship(back_populates="appointment", uselist=False)

    @property
    def duration(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)


class Visit(Base):
    """Záznam o uskutečněné návštěvě (1:1 k rezervaci se stavem COMPLETED)."""

    __tablename__ = "visit"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointment.id"), unique=True)
    visit_date: Mapped[date] = mapped_column(Date)
    clinical_note: Mapped[str] = mapped_column(Text, default="")

    appointment: Mapped[Appointment] = relationship(back_populates="visit")
    procedures: Mapped[list[VisitProcedure]] = relationship(
        back_populates="visit", cascade="all, delete-orphan", order_by="VisitProcedure.id"
    )


class MedicalProcedure(Base):
    """Číselník výkonů (kód, název, bodové ohodnocení)."""

    __tablename__ = "medical_procedure"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    points: Mapped[int] = mapped_column(Integer)


class VisitProcedure(Base):
    """Vazební entita M:N Návštěva ↔ Výkon s atributy počet a body v době výkonu."""

    __tablename__ = "visit_procedure"
    __table_args__ = (
        CheckConstraint("count BETWEEN 1 AND 10", name="ck_visit_procedure_count"),
        CheckConstraint("billed_points >= 0", name="ck_visit_procedure_points"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visit.id"), index=True)
    procedure_id: Mapped[int] = mapped_column(ForeignKey("medical_procedure.id"))
    count: Mapped[int] = mapped_column(Integer, default=1)
    billed_points: Mapped[int] = mapped_column(Integer)

    visit: Mapped[Visit] = relationship(back_populates="procedures")
    procedure: Mapped[MedicalProcedure] = relationship()


class DoctorAbsence(Base):
    """Evidovaná nepřítomnost lékaře (nemoc, výpadek) v konkrétní den."""

    __tablename__ = "doctor_absence"
    __table_args__ = (UniqueConstraint("doctor_id", "date", name="uq_absence_doctor_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.id"))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(255), default="Nemoc")

    doctor: Mapped[Doctor] = relationship()
