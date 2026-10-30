"""Aplikační logika rezervací (aplikační vrstva).

Nezná HTTP ani SQL: dostává unit of work s repozitáři a vrací doménové objekty.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.db.models import Appointment, AppointmentStatus, CancelledBy
from app.domain import rules
from app.domain.errors import BookingRuleError, ConflictError, NotFoundError, ValidationError


@dataclass(frozen=True)
class BookingRequest:
    doctor_id: int
    patient_id: int
    day: date
    start_time: time
    duration: int
    reason: str
    reschedule_from_id: int | None = None


@dataclass(frozen=True)
class Slot:
    time: time
    state: str  # FREE | BOOKED | EXTERNAL | ABSENT | PAST
    appointment_id: int | None = None


@dataclass(frozen=True)
class DayAvailability:
    day: date
    works: bool
    absent: bool
    slots: list[Slot]


class BookingService:
    def __init__(self, uow, today: Callable[[], date] = date.today, now: Callable[[], datetime] = datetime.now):
        self.uow = uow
        self.today = today
        self.now = now

    # ---------- pomocné ----------
    def _windows(self, doctor_id: int, day: date) -> list[rules.TimeWindow]:
        return [
            rules.TimeWindow(s.start_time, s.end_time, s.location)
            for s in self.uow.doctors.schedules_for_day(doctor_id, day.weekday())
        ]

    def _get(self, appointment_id: int) -> Appointment:
        app = self.uow.appointments.get(appointment_id)
        if app is None:
            raise NotFoundError("Rezervace neexistuje.")
        return app

    # ---------- založení ----------
    def create(self, req: BookingRequest) -> Appointment:
        doctor = self.uow.doctors.get(req.doctor_id)
        if doctor is None:
            raise NotFoundError("Lékař neexistuje.")
        if self.uow.patients.get(req.patient_id) is None:
            raise NotFoundError("Pacient neexistuje.")
        reason = (req.reason or "").strip() or "Běžná kontrola"
        if len(reason) > 255:
            raise ValidationError("Důvod návštěvy je příliš dlouhý (max. 255 znaků).")

        original = None
        if req.reschedule_from_id is not None:
            original = self._get(req.reschedule_from_id)
            if original.status != AppointmentStatus.PLANNED:
                raise BookingRuleError("Přeplánovat lze jen plánovaný termín.")

        start = datetime.combine(req.day, req.start_time)
        end = start + timedelta(minutes=req.duration)
        rules.validate_booking_time(
            start=start,
            duration=req.duration,
            today=self.today(),
            windows=self._windows(req.doctor_id, req.day),
            doctor_absent=self.uow.absences.exists(req.doctor_id, req.day),
            doctor_name=doctor.full_name,
        )

        # Zámek lékaře: dvě recepce nemohou současně projít kontrolou kolize.
        self.uow.appointments.lock_doctor(req.doctor_id)
        ignore = original.id if original and original.doctor_id == req.doctor_id else None
        clash = self.uow.appointments.find_overlapping_active(req.doctor_id, start, end, exclude_id=ignore)
        if clash is not None:
            raise ConflictError(
                f"KOLIZE INTERVALU: Termín ({start:%H:%M} – {end:%H:%M}) se překrývá s existující rezervací "
                f"({clash.start_at:%H:%M} – {clash.end_at:%H:%M}). Systém nedovolí překrytí."
            )

        if original is not None:
            # Původní termín uvolníme dřív, než vložíme nový (kvůli DB constraintu při překryvu se sebou samým).
            original.status = AppointmentStatus.CANCELLED
            original.cancelled_by = CancelledBy.CLINIC
            original.cancelled_at = self.now()
            original.cancellation_reason = (
                "Přeplánováno ordinací (nepřítomnost lékaře)"
                if self.uow.absences.exists(original.doctor_id, original.start_at.date())
                else "Přeplánováno na jiný termín"
            )

        new = self.uow.appointments.add(
            Appointment(
                doctor_id=req.doctor_id,
                patient_id=req.patient_id,
                start_at=start,
                end_at=end,
                status=AppointmentStatus.PLANNED,
                reason=reason,
                patient_called=False,
            )
        )
        if original is not None:
            original.rescheduled_to_id = new.id
        self.uow.commit()
        return new

    # ---------- změny stavu ----------
    def cancel(self, appointment_id: int, reason: str | None = None) -> Appointment:
        """Pacient se omluvil → CANCELLED, slot se uvolní, záznam zůstává pro statistiku."""
        app = self._get(appointment_id)
        if app.status != AppointmentStatus.PLANNED:
            raise BookingRuleError("Zrušit lze jen plánovaný termín (odbavenou návštěvu nelze zrušit).")
        app.status = AppointmentStatus.CANCELLED
        app.cancelled_by = CancelledBy.PATIENT
        app.cancelled_at = self.now()
        app.cancellation_reason = (reason or "").strip() or "Pacient se omluvil"
        self.uow.commit()
        return app

    def mark_no_show(self, appointment_id: int) -> Appointment:
        app = self._get(appointment_id)
        if app.status != AppointmentStatus.PLANNED:
            raise BookingRuleError("Absenci lze zaznamenat jen u plánovaného termínu.")
        if app.start_at.date() > self.today():
            raise BookingRuleError("Absenci nelze zaznamenat u termínu, který teprve proběhne.")
        app.status = AppointmentStatus.NO_SHOW
        self.uow.commit()
        return app

    def complete(self, appointment_id: int) -> Appointment:
        """Pacient dorazil → návštěva se uskutečnila a lze k ní vykazovat výkony."""
        app = self._get(appointment_id)
        if app.status != AppointmentStatus.PLANNED:
            raise BookingRuleError("Odbavit lze jen plánovaný termín.")
        if app.start_at.date() > self.today():
            raise BookingRuleError("Návštěvu nelze odbavit dřív, než nastane den termínu.")
        app.status = AppointmentStatus.COMPLETED
        self.uow.commit()
        return app

    def mark_called(self, appointment_id: int) -> Appointment:
        app = self._get(appointment_id)
        app.patient_called = True
        self.uow.commit()
        return app

    # ---------- přehled volných termínů ----------
    def week_availability(self, doctor_id: int, any_day_in_week: date) -> list[DayAvailability]:
        if self.uow.doctors.get(doctor_id) is None:
            raise NotFoundError("Lékař neexistuje.")
        monday = rules.week_start(any_day_in_week)
        saturday = monday + timedelta(days=5)
        apps = self.uow.appointments.list(date_from=monday, date_to=saturday, doctor_id=doctor_id)
        active = [a for a in apps if a.status in (AppointmentStatus.PLANNED, AppointmentStatus.COMPLETED)]
        absent_days = self.uow.absences.dates_for(doctor_id, monday, saturday)
        now = self.now()

        days: list[DayAvailability] = []
        for offset in range(5):
            day = monday + timedelta(days=offset)
            windows = self._windows(doctor_id, day)
            absent = day in absent_days
            slots: list[Slot] = []
            for t, external in rules.generate_slots(windows):
                start = datetime.combine(day, t)
                slot = rules.Interval(start, start + timedelta(minutes=rules.SLOT_MINUTES))
                hit = next((a for a in active if rules.overlaps(slot, rules.Interval(a.start_at, a.end_at))), None)
                if external:
                    state = "EXTERNAL"
                elif hit is not None:
                    state = "BOOKED"
                elif absent:
                    state = "ABSENT"
                elif start < now:
                    state = "PAST"
                else:
                    state = "FREE"
                slots.append(Slot(t, state, hit.id if hit is not None else None))
            days.append(DayAvailability(day, works=bool(windows), absent=absent, slots=slots))
        return days
