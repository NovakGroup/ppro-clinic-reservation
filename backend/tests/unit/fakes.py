"""In-memory náhrada datové vrstvy pro jednotkové testy služeb (bez databáze)."""
from __future__ import annotations

from datetime import date, time
from itertools import count
from types import SimpleNamespace

from app.db.models import AppointmentStatus

ACTIVE = (AppointmentStatus.PLANNED, AppointmentStatus.COMPLETED)


def schedule(doctor_id: int, dow: int, start: str, end: str, location: str = "Na Vyhlídce"):
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return SimpleNamespace(doctor_id=doctor_id, day_of_week=dow, start_time=time(h1, m1), end_time=time(h2, m2),
                           location=location)


class FakeDoctors:
    def __init__(self, doctors, schedules):
        self.doctors = {d.id: d for d in doctors}
        self.schedules = schedules

    def get(self, doctor_id):
        return self.doctors.get(doctor_id)

    def list(self):
        return list(self.doctors.values())

    def schedules_for_day(self, doctor_id, dow):
        return [s for s in self.schedules if s.doctor_id == doctor_id and s.day_of_week == dow]


class FakePatients:
    def __init__(self, patients):
        self.items = {p.id: p for p in patients}
        self._ids = count(1000)

    def get(self, pid):
        return self.items.get(pid)

    def list(self):
        return list(self.items.values())

    def get_by_insurance_id(self, iid):
        return next((p for p in self.items.values() if p.insurance_id == iid), None)

    def add(self, p):
        p.id = next(self._ids)
        self.items[p.id] = p
        return p

    def reliability_stats(self):
        return {}


class FakeAppointments:
    def __init__(self):
        self.items: dict[int, object] = {}
        self._ids = count(1)
        self.locked: list[int] = []

    def get(self, aid):
        return self.items.get(aid)

    def add(self, a):
        a.id = next(self._ids)
        a.visit = None
        self.items[a.id] = a
        return a

    def lock_doctor(self, doctor_id):
        self.locked.append(doctor_id)

    def find_overlapping_active(self, doctor_id, start, end, exclude_id=None):
        for a in self.items.values():
            if a.id != exclude_id and a.doctor_id == doctor_id and a.status in ACTIVE and a.start_at < end and start < a.end_at:
                return a
        return None

    def list(self, *, date_from=None, date_to=None, doctor_id=None):
        return [a for a in self.items.values()
                if (doctor_id is None or a.doctor_id == doctor_id)
                and (date_from is None or a.start_at.date() >= date_from)
                and (date_to is None or a.start_at.date() < date_to)]


class FakeAbsences:
    def __init__(self, days: set[tuple[int, date]] | None = None):
        self.days = days or set()

    def exists(self, doctor_id, day):
        return (doctor_id, day) in self.days

    def dates_for(self, doctor_id, date_from, date_to):
        return {d for (doc, d) in self.days if doc == doctor_id and date_from <= d < date_to}


class FakeVisits:
    def __init__(self):
        self.items = {}

    def get_by_appointment(self, aid):
        return self.items.get(aid)

    def add(self, v):
        v.procedures = []
        self.items[v.appointment_id] = v
        return v


class FakeProcedures:
    def __init__(self, procedures):
        self.items = {p.id: p for p in procedures}

    def get(self, pid):
        return self.items.get(pid)


class FakeUnitOfWork:
    def __init__(self):
        self.doctors = FakeDoctors(
            [SimpleNamespace(id=1, full_name="MUDr. Jana Hrubá"), SimpleNamespace(id=2, full_name="MUDr. Petr Svoboda")],
            [schedule(1, 0, "08:00", "12:30"), schedule(1, 1, "08:00", "12:00"),
             schedule(2, 1, "08:30", "12:00"), schedule(2, 1, "12:00", "14:00", "Externí pracoviště")],
        )
        self.patients = FakePatients([SimpleNamespace(id=1, first_name="Marie", last_name="Krátká",
                                                      insurance_id="545812/0316")])
        self.appointments = FakeAppointments()
        self.absences = FakeAbsences()
        self.visits = FakeVisits()
        self.procedures = FakeProcedures([SimpleNamespace(id=1, code="09511", name="Cílené vyšetření", points=150),
                                          SimpleNamespace(id=2, code="09220", name="EKG", points=180)])
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass
