"""Repozitáře nad SQLAlchemy (datová vrstva).

Jediné místo v aplikaci, kde vznikají databázové dotazy. Služby (aplikační vrstva)
pracují jen s metodami těchto tříd a o SQL nic nevědí.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Appointment,
    AppointmentStatus,
    CancelledBy,
    Doctor,
    DoctorAbsence,
    DoctorSchedule,
    MedicalProcedure,
    Patient,
    Visit,
    VisitProcedure,
)
from app.domain.errors import ConflictError

ACTIVE = (AppointmentStatus.PLANNED, AppointmentStatus.COMPLETED)


class DoctorRepository:
    def __init__(self, s: Session):
        self.s = s

    def list(self) -> list[Doctor]:
        return list(self.s.scalars(select(Doctor).options(selectinload(Doctor.schedules)).order_by(Doctor.id)))

    def get(self, doctor_id: int) -> Doctor | None:
        return self.s.get(Doctor, doctor_id)

    def schedules_for_day(self, doctor_id: int, day_of_week: int) -> list[DoctorSchedule]:
        q = select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.day_of_week == day_of_week
        )
        return list(self.s.scalars(q.order_by(DoctorSchedule.start_time)))


class PatientRepository:
    def __init__(self, s: Session):
        self.s = s

    def list(self) -> list[Patient]:
        return list(self.s.scalars(select(Patient).order_by(Patient.last_name, Patient.first_name)))

    def get(self, patient_id: int) -> Patient | None:
        return self.s.get(Patient, patient_id)

    def get_by_insurance_id(self, insurance_id: str) -> Patient | None:
        return self.s.scalar(select(Patient).where(Patient.insurance_id == insurance_id))

    def add(self, patient: Patient) -> Patient:
        self.s.add(patient)
        try:
            self.s.flush()
        except IntegrityError as exc:  # pojistka proti souběhu – unikátní index na insurance_id
            self.s.rollback()
            raise ConflictError("Pacient s tímto číslem pojištěnce již v kartotéce existuje.") from exc
        return patient

    def reliability_stats(self) -> dict[int, tuple[int, int]]:
        """Vrátí {patient_id: (omluvená zrušení, neomluvené absence)}."""
        q = select(
            Appointment.patient_id,
            func.count(
                case(
                    (
                        and_(
                            Appointment.status == AppointmentStatus.CANCELLED,
                            Appointment.cancelled_by == CancelledBy.PATIENT,
                        ),
                        1,
                    )
                )
            ),
            func.count(case((Appointment.status == AppointmentStatus.NO_SHOW, 1))),
        ).group_by(Appointment.patient_id)
        return {pid: (c, n) for pid, c, n in self.s.execute(q)}


class AppointmentRepository:
    def __init__(self, s: Session):
        self.s = s

    def get(self, appointment_id: int) -> Appointment | None:
        return self.s.get(Appointment, appointment_id)

    def list(self, *, date_from: date | None = None, date_to: date | None = None,
             doctor_id: int | None = None) -> list[Appointment]:
        q = select(Appointment).options(selectinload(Appointment.visit))
        if date_from:
            q = q.where(Appointment.start_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            q = q.where(Appointment.start_at < datetime.combine(date_to, datetime.min.time()))
        if doctor_id:
            q = q.where(Appointment.doctor_id == doctor_id)
        return list(self.s.scalars(q.order_by(Appointment.start_at)))

    def find_overlapping_active(self, doctor_id: int, start: datetime, end: datetime,
                                exclude_id: int | None = None) -> Appointment | None:
        q = select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(ACTIVE),
            Appointment.start_at < end,
            start < Appointment.end_at,
        )
        if exclude_id is not None:
            q = q.where(Appointment.id != exclude_id)
        return self.s.scalar(q.order_by(Appointment.start_at).limit(1))

    def lock_doctor(self, doctor_id: int) -> None:
        """Zamkne řádek lékaře do konce transakce – serializuje souběžné rezervace u jednoho lékaře."""
        self.s.execute(select(Doctor.id).where(Doctor.id == doctor_id).with_for_update())

    def add(self, appointment: Appointment) -> Appointment:
        self.s.add(appointment)
        try:
            self.s.flush()
        except IntegrityError as exc:
            self.s.rollback()
            if "ex_appointment_no_overlap" in str(exc.orig):
                raise ConflictError("KOLIZE INTERVALU: termín se překrývá s jinou rezervací lékaře.") from exc
            raise
        return appointment

    def planned_on_absences(self) -> list[Appointment]:
        """Rezervace v evidovaných dnech nepřítomnosti lékaře (plánované nebo už přeplánované)."""
        q = (
            select(Appointment)
            .join(
                DoctorAbsence,
                and_(
                    DoctorAbsence.doctor_id == Appointment.doctor_id,
                    DoctorAbsence.date == func.date(Appointment.start_at),
                ),
            )
            .where(or_(Appointment.status == AppointmentStatus.PLANNED, Appointment.rescheduled_to_id.is_not(None)))
            .order_by(Appointment.start_at)
        )
        return list(self.s.scalars(q))


class VisitRepository:
    def __init__(self, s: Session):
        self.s = s

    def get_by_appointment(self, appointment_id: int) -> Visit | None:
        q = select(Visit).options(selectinload(Visit.procedures)).where(Visit.appointment_id == appointment_id)
        return self.s.scalar(q)

    def add(self, visit: Visit) -> Visit:
        self.s.add(visit)
        self.s.flush()
        return visit


class ProcedureRepository:
    def __init__(self, s: Session):
        self.s = s

    def list(self) -> list[MedicalProcedure]:
        return list(self.s.scalars(select(MedicalProcedure).order_by(MedicalProcedure.code)))

    def get(self, procedure_id: int) -> MedicalProcedure | None:
        return self.s.get(MedicalProcedure, procedure_id)


class AbsenceRepository:
    def __init__(self, s: Session):
        self.s = s

    def list(self) -> list[DoctorAbsence]:
        return list(self.s.scalars(select(DoctorAbsence).order_by(DoctorAbsence.date)))

    def get(self, absence_id: int) -> DoctorAbsence | None:
        return self.s.get(DoctorAbsence, absence_id)

    def exists(self, doctor_id: int, day: date) -> bool:
        q = select(DoctorAbsence.id).where(DoctorAbsence.doctor_id == doctor_id, DoctorAbsence.date == day)
        return self.s.scalar(q) is not None

    def dates_for(self, doctor_id: int, date_from: date, date_to: date) -> set[date]:
        q = select(DoctorAbsence.date).where(
            DoctorAbsence.doctor_id == doctor_id, DoctorAbsence.date >= date_from, DoctorAbsence.date < date_to
        )
        return set(self.s.scalars(q))

    def add(self, absence: DoctorAbsence) -> DoctorAbsence:
        self.s.add(absence)
        self.s.flush()
        return absence

    def delete(self, absence: DoctorAbsence) -> None:
        self.s.delete(absence)


class ReportRepository:
    def __init__(self, s: Session):
        self.s = s

    def monthly_procedures(self, month_start: date, month_end: date, doctor_id: int | None):
        """Agregace výkonů: (pojišťovna, kód, název, body/ks, počet) – počítá databáze."""
        q = (
            select(
                Patient.insurance_code,
                MedicalProcedure.code,
                MedicalProcedure.name,
                VisitProcedure.billed_points,
                func.sum(VisitProcedure.count),
            )
            .join(Visit, VisitProcedure.visit_id == Visit.id)
            .join(Appointment, Visit.appointment_id == Appointment.id)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(MedicalProcedure, VisitProcedure.procedure_id == MedicalProcedure.id)
            .where(Visit.visit_date >= month_start, Visit.visit_date < month_end,
                   Appointment.status == AppointmentStatus.COMPLETED)
            .group_by(Patient.insurance_code, MedicalProcedure.code, MedicalProcedure.name, VisitProcedure.billed_points)
            .order_by(Patient.insurance_code, MedicalProcedure.code)
        )
        if doctor_id:
            q = q.where(Appointment.doctor_id == doctor_id)
        return list(self.s.execute(q))

    def monthly_counts(self, month_start: date, month_end: date, doctor_id: int | None) -> tuple[int, int, int]:
        """(uložené návštěvy, různí pacienti, zrušeno pacientem + nedošli)."""
        visits_q = (
            select(func.count(Visit.id), func.count(func.distinct(Appointment.patient_id)))
            .join(Appointment, Visit.appointment_id == Appointment.id)
            .where(Visit.visit_date >= month_start, Visit.visit_date < month_end)
        )
        storno_q = select(func.count(Appointment.id)).where(
            Appointment.start_at >= datetime.combine(month_start, datetime.min.time()),
            Appointment.start_at < datetime.combine(month_end, datetime.min.time()),
            or_(
                Appointment.status == AppointmentStatus.NO_SHOW,
                and_(Appointment.status == AppointmentStatus.CANCELLED, Appointment.cancelled_by == CancelledBy.PATIENT),
            ),
        )
        if doctor_id:
            visits_q = visits_q.where(Appointment.doctor_id == doctor_id)
            storno_q = storno_q.where(Appointment.doctor_id == doctor_id)
        visits, patients = self.s.execute(visits_q).one()
        return visits, patients, self.s.scalar(storno_q)


class SqlUnitOfWork:
    """Drží jednu databázovou transakci a zpřístupňuje repozitáře."""

    def __init__(self, session: Session):
        self.session = session
        self.doctors = DoctorRepository(session)
        self.patients = PatientRepository(session)
        self.appointments = AppointmentRepository(session)
        self.visits = VisitRepository(session)
        self.procedures = ProcedureRepository(session)
        self.absences = AbsenceRepository(session)
        self.reports = ReportRepository(session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
