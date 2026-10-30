"""Aplikační logika kartotéky, návštěv, výkazů a nepřítomnosti lékařů."""
from __future__ import annotations

import csv
import io
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.db.models import AppointmentStatus, DoctorAbsence, Patient, Visit, VisitProcedure
from app.domain import rules
from app.domain.errors import BookingRuleError, ConflictError, NotFoundError, ValidationError

INSURANCE_NAMES = {"111": "VZP", "201": "VoZP", "205": "ČPZP", "207": "OZP", "209": "ZPŠ", "211": "ZPMV", "213": "RBP"}


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if not unicodedata.combining(c)).lower().strip()


def _digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


# ---------------------------------------------------------------- číselníky
class CatalogService:
    """Čtení číselníků: lékaři s ordinačními hodinami a výkony."""

    def __init__(self, uow):
        self.uow = uow

    def doctors(self):
        return self.uow.doctors.list()

    def procedures(self):
        return self.uow.procedures.list()

    def appointments(self, date_from: date | None, date_to: date | None, doctor_id: int | None):
        return self.uow.appointments.list(date_from=date_from, date_to=date_to, doctor_id=doctor_id)


# ---------------------------------------------------------------- pacienti
@dataclass(frozen=True)
class PatientView:
    patient: Patient
    cancellations: int
    no_shows: int

    @property
    def unreliable(self) -> bool:
        return rules.is_unreliable(self.no_shows)


@dataclass(frozen=True)
class NewPatient:
    first_name: str
    last_name: str
    birth_year: int
    insurance_id: str
    insurance_code: str
    phone: str | None


class PatientService:
    def __init__(self, uow, today: Callable[[], date] = date.today):
        self.uow = uow
        self.today = today

    def search(self, query: str | None = None) -> list[PatientView]:
        stats = self.uow.patients.reliability_stats()
        term = _norm(query or "")
        term_digits = _digits(query)
        result = []
        for p in self.uow.patients.list():
            if term:
                names = [_norm(p.last_name), _norm(p.first_name),
                         _norm(f"{p.last_name} {p.first_name}"), _norm(f"{p.first_name} {p.last_name}")]
                by_name = any(term in n for n in names)
                by_number = len(term_digits) >= 3 and (term_digits in _digits(p.phone) or term_digits in _digits(p.insurance_id))
                if not (by_name or by_number):
                    continue
            c, n = stats.get(p.id, (0, 0))
            result.append(PatientView(p, c, n))
        return result

    def create(self, data: NewPatient) -> PatientView:
        first, last = data.first_name.strip(), data.last_name.strip()
        if not first or not last:
            raise ValidationError("Vyplňte jméno i příjmení pacienta.")
        insurance_id = rules.normalize_insurance_id(data.insurance_id)
        if data.insurance_code not in INSURANCE_NAMES:
            raise ValidationError("Neznámý kód pojišťovny.")
        if not 1900 <= data.birth_year <= self.today().year:
            raise ValidationError("Neplatný rok narození.")
        if rules.birth_year_from_insurance_id(insurance_id) != data.birth_year:
            raise ValidationError("Rok narození neodpovídá rodnému číslu.")
        phone = rules.normalize_phone(data.phone)

        existing = self.uow.patients.get_by_insurance_id(insurance_id)
        if existing is not None:
            raise ConflictError(
                f"Pacient s číslem pojištěnce {insurance_id} již v kartotéce existuje "
                f"({existing.last_name} {existing.first_name}). Zamezeno vzniku duplicity."
            )
        patient = self.uow.patients.add(Patient(
            first_name=first, last_name=last, birth_year=data.birth_year,
            insurance_id=insurance_id, insurance_code=data.insurance_code, phone=phone,
        ))
        self.uow.commit()
        return PatientView(patient, 0, 0)


# ---------------------------------------------------------------- návštěvy a výkony
@dataclass(frozen=True)
class VisitItem:
    procedure_id: int
    count: int


class VisitService:
    def __init__(self, uow):
        self.uow = uow

    def get(self, appointment_id: int) -> Visit | None:
        if self.uow.appointments.get(appointment_id) is None:
            raise NotFoundError("Rezervace neexistuje.")
        return self.uow.visits.get_by_appointment(appointment_id)

    def save(self, appointment_id: int, note: str, items: list[VisitItem]) -> Visit:
        app = self.uow.appointments.get(appointment_id)
        if app is None:
            raise NotFoundError("Rezervace neexistuje.")
        if app.status != AppointmentStatus.COMPLETED:
            raise BookingRuleError("Výkon nelze zapsat k návštěvě, která se neuskutečnila.")
        if not items:
            raise ValidationError("Návštěva musí obsahovat alespoň jeden vykázaný výkon.")

        merged: dict[int, int] = {}
        for item in items:
            merged[item.procedure_id] = merged.get(item.procedure_id, 0) + item.count
        for count in merged.values():
            rules.validate_procedure_count(count)

        visit = self.uow.visits.get_by_appointment(appointment_id)
        if visit is None:
            visit = self.uow.visits.add(Visit(appointment_id=appointment_id, visit_date=app.start_at.date(), clinical_note=""))
        # Body se historizují: u výkonu, který už na návštěvě byl, zůstávají body z doby prvního zápisu.
        previous_points = {vp.procedure_id: vp.billed_points for vp in visit.procedures}

        new_rows = []
        for procedure_id, count in merged.items():
            proc = self.uow.procedures.get(procedure_id)
            if proc is None:
                raise ValidationError(f"Výkon {procedure_id} není v číselníku.")
            points = previous_points.get(procedure_id, proc.points)
            new_rows.append(VisitProcedure(procedure_id=procedure_id, count=count, billed_points=points))
        visit.clinical_note = (note or "").strip()
        visit.procedures = new_rows
        self.uow.commit()
        return visit


# ---------------------------------------------------------------- výkazy
@dataclass(frozen=True)
class ReportRow:
    insurance_code: str
    insurance_name: str
    code: str
    name: str
    points: int
    count: int

    @property
    def total(self) -> int:
        return self.points * self.count


@dataclass(frozen=True)
class MonthlyReport:
    month: str
    doctor_id: int | None
    rows: list[ReportRow]
    visits: int
    patients: int
    cancelled_or_no_show: int

    @property
    def total_points(self) -> int:
        return sum(r.total for r in self.rows)


def parse_month(month: str) -> tuple[date, date]:
    try:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Měsíc zadejte ve tvaru RRRR-MM.") from exc
    end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return start, end


class ReportService:
    def __init__(self, uow):
        self.uow = uow

    def monthly(self, month: str, doctor_id: int | None = None) -> MonthlyReport:
        start, end = parse_month(month)
        if doctor_id is not None and self.uow.doctors.get(doctor_id) is None:
            raise NotFoundError("Lékař neexistuje.")
        rows = [
            ReportRow(ins, INSURANCE_NAMES.get(ins, ""), code, name, points, int(count))
            for ins, code, name, points, count in self.uow.reports.monthly_procedures(start, end, doctor_id)
        ]
        visits, patients, storno = self.uow.reports.monthly_counts(start, end, doctor_id)
        return MonthlyReport(month, doctor_id, rows, visits, patients, storno)

    def monthly_csv(self, month: str, doctor_id: int | None = None) -> str:
        report = self.monthly(month, doctor_id)
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(["pojistovna", "kod_vykonu", "nazev", "pocet", "body_ks", "body_celkem"])
        for r in report.rows:
            w.writerow([r.insurance_code, r.code, r.name, r.count, r.points, r.total])
        w.writerow(["CELKEM", "", "", "", "", report.total_points])
        return "﻿" + out.getvalue()


# ---------------------------------------------------------------- nepřítomnost lékaře
class AbsenceService:
    def __init__(self, uow, today: Callable[[], date] = date.today):
        self.uow = uow
        self.today = today

    def list(self) -> list[DoctorAbsence]:
        return self.uow.absences.list()

    def add(self, doctor_id: int, day: date, reason: str | None = None) -> DoctorAbsence:
        if self.uow.doctors.get(doctor_id) is None:
            raise NotFoundError("Lékař neexistuje.")
        if day < self.today():
            raise BookingRuleError("Nepřítomnost nelze evidovat zpětně.")
        if self.uow.absences.exists(doctor_id, day):
            raise ConflictError("Nepřítomnost tohoto lékaře v daný den už je zaevidovaná.")
        absence = self.uow.absences.add(DoctorAbsence(doctor_id=doctor_id, date=day, reason=(reason or "Nemoc")))
        self.uow.commit()
        return absence

    def remove(self, absence_id: int) -> None:
        absence = self.uow.absences.get(absence_id)
        if absence is None:
            raise NotFoundError("Nepřítomnost neexistuje.")
        self.uow.absences.delete(absence)
        self.uow.commit()

    def affected_appointments(self):
        return self.uow.appointments.planned_on_absences()
