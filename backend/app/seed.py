"""Syntetická testovací data. Spouští se při startu kontejneru, data vloží jen do prázdné databáze.

Všechna jména, rodná čísla i telefony jsou smyšlené. Termíny jsou vztažené k aktuálnímu
týdnu, aby diář po spuštění nikdy nebyl prázdný.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Appointment,
    AppointmentStatus,
    CancelledBy,
    Doctor,
    DoctorSchedule,
    MedicalProcedure,
    Patient,
    Visit,
    VisitProcedure,
)
from app.db.session import get_sessionmaker
from app.domain.rules import MAIN_LOCATION, week_start

EXTERNAL = "Externí pracoviště"


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def seed(session: Session, today: date | None = None) -> bool:
    if session.scalar(select(Doctor.id).limit(1)) is not None:
        return False
    today = today or date.today()
    monday = week_start(today) if today.weekday() < 5 else week_start(today) + timedelta(days=7)

    hruba = Doctor(first_name="Jana", last_name="Hrubá", specialization="Praktický lékař", email="hruba@example.test")
    svoboda = Doctor(first_name="Petr", last_name="Svoboda", specialization="Interna", email="svoboda@example.test")
    cerna = Doctor(first_name="Eva", last_name="Černá", specialization="Kardiologie", email="cerna@example.test")
    session.add_all([hruba, svoboda, cerna])
    session.flush()

    schedule = [
        (hruba, 0, "08:00", "12:30", MAIN_LOCATION), (hruba, 1, "08:00", "12:00", MAIN_LOCATION),
        (hruba, 2, "08:00", "12:30", MAIN_LOCATION), (hruba, 4, "08:00", "12:30", MAIN_LOCATION),
        (svoboda, 0, "08:30", "14:00", MAIN_LOCATION), (svoboda, 1, "08:30", "12:00", MAIN_LOCATION),
        (svoboda, 1, "12:00", "14:00", EXTERNAL), (svoboda, 3, "08:30", "14:00", MAIN_LOCATION),
        (cerna, 2, "09:00", "15:00", MAIN_LOCATION), (cerna, 3, "09:00", "15:00", MAIN_LOCATION),
        (cerna, 4, "09:00", "15:00", MAIN_LOCATION),
    ]
    session.add_all(
        DoctorSchedule(doctor_id=d.id, day_of_week=dow, start_time=_t(s), end_time=_t(e), location=loc)
        for d, dow, s, e, loc in schedule
    )

    procedures = {
        "09511": MedicalProcedure(code="09511", name="Cílené vyšetření praktickým lékařem", points=150),
        "09513": MedicalProcedure(code="09513", name="Kontrolní vyšetření", points=95),
        "09115": MedicalProcedure(code="09115", name="Aplikace injekce (i.m., s.c.)", points=45),
        "09123": MedicalProcedure(code="09123", name="Odběr krve ze žíly", points=35),
        "09220": MedicalProcedure(code="09220", name="Elektrokardiografické vyšetření (EKG)", points=180),
        "09543": MedicalProcedure(code="09543", name="Preventivní prohlídka", points=420),
    }
    session.add_all(procedures.values())

    people = [
        ("Marie", "Krátká", 1954, "545812/0316", "111", "721 849 102"),
        ("Jana", "Nováková", 1981, "815201/4497", "205", "604 112 334"),
        ("Karel", "Vomáčka", 1976, "760418/1827", "111", "777 982 301"),
        ("Alena", "Dvořáková", 1992, "926105/9820", "211", "608 554 219"),
        ("Tomáš", "Beneš", 1988, "881022/3312", "111", "732 441 905"),
        ("Lenka", "Malá", 1995, "955307/1231", "201", "731 220 418"),
        ("Jiří", "Procházka", 1969, "690911/4421", "111", "603 778 120"),
        ("Pavla", "Horáková", 2001, "016215/1110", "207", "720 915 336"),
    ]
    patients = [Patient(first_name=f, last_name=l, birth_year=y, insurance_id=rc, insurance_code=ins, phone=ph)
                for f, l, y, rc, ins, ph in people]
    session.add_all(patients)
    session.flush()
    p = {x.last_name: x for x in patients}

    def app(doc, pat, day_offset, hhmm, minutes, reason, status=AppointmentStatus.PLANNED, cancelled=None):
        start = datetime.combine(monday + timedelta(days=day_offset), _t(hhmm))
        a = Appointment(doctor_id=doc.id, patient_id=pat.id, start_at=start, end_at=start + timedelta(minutes=minutes),
                        reason=reason, status=status, patient_called=False)
        if cancelled:
            a.cancelled_by = cancelled
            a.cancelled_at = start - timedelta(days=1)
            a.cancellation_reason = "Pacient se omluvil" if cancelled == CancelledBy.PATIENT else "Přeplánováno"
        session.add(a)
        return a

    C, N, D = AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED
    # Historie spolehlivosti (minulé týdny): paní Krátká 2× zrušila a 3× nepřišla.
    for i, st in enumerate([C, N, C, N, N]):
        app(hruba, p["Krátká"], -7 * (i + 2), "09:00", 15, "Kontrola tlaku", st,
            CancelledBy.PATIENT if st == C else None)
    app(hruba, p["Beneš"], -14, "10:00", 15, "Kontrola", C, CancelledBy.PATIENT)
    app(hruba, p["Beneš"], -21, "10:00", 15, "Kontrola", N)
    app(svoboda, p["Nováková"], -14, "09:00", 15, "Kontrola", C, CancelledBy.PATIENT)

    # Uskutečněné návštěvy s výkony (pro měsíční výkaz)
    done = [
        (hruba, "Vomáčka", -7, "08:30", 15, "Kontrola po antibiotikách", [("09513", 1)]),
        (cerna, "Beneš", -5, "09:00", 30, "EKG kontrola", [("09220", 1), ("09513", 1)]),
        (svoboda, "Dvořáková", -4, "10:00", 30, "Interní vyšetření", [("09511", 1), ("09123", 2)]),
        (hruba, "Procházka", -3, "11:00", 45, "Preventivní prohlídka", [("09543", 1), ("09123", 1)]),
        (hruba, "Nováková", 0, "10:00", 15, "Předpis chronických léků na tlak", [("09513", 1), ("09115", 1)]),
    ]
    for doc, last, off, hhmm, mins, reason, items in done:
        a = app(doc, p[last], off, hhmm, mins, reason, D)
        session.flush()
        v = Visit(appointment_id=a.id, visit_date=a.start_at.date(), clinical_note="Bez komplikací.")
        v.procedures = [VisitProcedure(procedure_id=procedures[c].id, count=n, billed_points=procedures[c].points)
                        for c, n in items]
        session.add(v)

    # Aktuální týden – plánované termíny
    planned = [
        (hruba, "Krátká", 0, "08:15", 15, "Bolest v krku a teplota"),
        (hruba, "Vomáčka", 0, "08:45", 30, "Preventivní prohlídka po 2 letech"),
        (hruba, "Dvořáková", 0, "10:30", 15, "Aplikace očkovací látky"),
        (svoboda, "Beneš", 0, "09:00", 30, "Vstupní interní vyšetření"),
        (hruba, "Nováková", 1, "08:30", 15, "Kontrola krevního tlaku"),
        (hruba, "Beneš", 1, "09:15", 15, "Výpis ze zdravotní dokumentace"),
        (svoboda, "Krátká", 1, "09:00", 30, "Kontrola laboratorních výsledků"),
        (hruba, "Dvořáková", 2, "08:45", 15, "Odběry krve nalačno"),
        (cerna, "Vomáčka", 2, "09:30", 30, "Pravidelné EKG vyšetření"),
        (svoboda, "Nováková", 3, "08:45", 15, "Doporučení na rehabilitační péči"),
        (cerna, "Beneš", 3, "10:15", 45, "Komplexní kardiologická konzultace"),
        (hruba, "Krátká", 4, "08:15", 15, "Předoperační vyšetření a razítko"),
        (hruba, "Vomáčka", 4, "11:00", 15, "Ukončení pracovní neschopnosti"),
        (hruba, "Malá", 7, "09:00", 30, "Vstupní prohlídka"),
        (cerna, "Horáková", 9, "10:00", 30, "Bušení srdce"),
        (svoboda, "Procházka", 10, "11:00", 15, "Kontrola cukrovky"),
    ]
    for doc, last, off, hhmm, mins, reason in planned:
        app(doc, p[last], off, hhmm, mins, reason)

    session.commit()
    return True


def main() -> None:
    with get_sessionmaker()() as session:
        print("Testovací data vložena." if seed(session) else "Databáze už obsahuje data, seed přeskočen.")


if __name__ == "__main__":
    main()
