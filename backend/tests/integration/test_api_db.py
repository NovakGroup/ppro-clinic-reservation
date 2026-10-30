"""Integrační testy: REST API + aplikační logika + skutečná PostgreSQL."""
import threading
from datetime import date, time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration

MON = "2026-11-02"  # pondělí po pevném "dnes" (pátek 30. 10. 2026)


def book(client, time, duration=15, doctor_id=1, patient_id=1, day=MON):
    return client.post("/api/appointments", json={
        "doctor_id": doctor_id, "patient_id": patient_id, "date": day, "time": time, "duration": duration,
        "reason": "Integrační test",
    })


def test_seed_a_ciselniky(client):
    doctors = client.get("/api/doctors").json()
    assert [d["name"] for d in doctors] == ["MUDr. Jana Hrubá", "MUDr. Petr Svoboda", "MUDr. Eva Černá"]
    assert any(s["external"] for s in doctors[1]["schedules"])
    assert len(client.get("/api/procedures").json()) >= 5


def test_rezervace_a_kolize_pres_api(client):
    assert book(client, "11:00", 30).status_code == 201
    r = book(client, "11:15")
    assert r.status_code == 409 and "KOLIZE" in r.json()["detail"]
    assert book(client, "11:30").status_code == 201  # navazující termín


def test_mimo_ordinacni_hodiny_pres_api(client):
    r = book(client, "09:00", doctor_id=3)
    assert r.status_code == 422 and "neordinuje" in r.json()["detail"]


def test_databaze_sama_odmitne_prekryv(Session):
    """Exclusion constraint chrání data i při zápisu mimo aplikaci."""
    with Session() as s:
        with pytest.raises(IntegrityError, match="ex_appointment_no_overlap"):
            s.execute(text(
                "INSERT INTO appointment (doctor_id, patient_id, start_at, end_at, reason) "
                "SELECT doctor_id, patient_id, start_at + interval '5 minutes', end_at, 'ručně' "
                "FROM appointment WHERE status = 'PLANNED' LIMIT 1"
            ))
            s.flush()


def test_databaze_nedovoli_smazat_historii(Session):
    with Session() as s:
        with pytest.raises(DBAPIError, match="Mazání historie"):
            s.execute(text("DELETE FROM patient WHERE id = 1"))


def test_soubezne_rezervace_stejneho_slotu(Session):
    """Dvě recepce uloží stejný slot ve stejnou chvíli – projde právě jedna rezervace."""
    from app.domain.errors import ConflictError
    from app.repositories.sql import SqlUnitOfWork
    from app.services.booking import BookingRequest, BookingService
    from tests.integration.conftest import FixedClock

    results = []
    barrier = threading.Barrier(2)

    def worker(patient_id):
        clock = FixedClock()
        with Session() as s:
            svc = BookingService(SqlUnitOfWork(s), today=clock.today, now=clock.now)
            barrier.wait()
            try:
                svc.create(BookingRequest(1, patient_id, date(2026, 11, 2), time(12, 0), 15, "souběh"))
                results.append("ok")
            except ConflictError:
                results.append("kolize")

    threads = [threading.Thread(target=worker, args=(pid,)) for pid in (6, 7)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["kolize", "ok"]


def test_navsteva_vykony_a_vykaz(client):
    apps = client.get("/api/appointments", params={"date_from": "2026-10-30", "date_to": "2026-10-31"}).json()
    krátká = next(a for a in apps if a["time"] == "08:15" and a["doctor_id"] == 1)
    assert client.put(f"/api/appointments/{krátká['id']}/visit",
                      json={"note": "", "items": [{"procedure_id": 1, "count": 1}]}).status_code == 422
    assert client.post(f"/api/appointments/{krátká['id']}/complete").status_code == 200
    procs = {p["code"]: p["id"] for p in client.get("/api/procedures").json()}
    r = client.put(f"/api/appointments/{krátká['id']}/visit",
                   json={"note": "TK 130/90", "items": [{"procedure_id": procs["09220"], "count": 1},
                                                        {"procedure_id": procs["09115"], "count": 3}]})
    assert r.status_code == 200 and r.json()["total_points"] == 180 + 3 * 45

    report = client.get("/api/reports/monthly", params={"month": "2026-10", "doctor_id": 1}).json()
    assert report["total_points"] == sum(row["total"] for row in report["rows"])
    vzp_ekg = next(row for row in report["rows"] if row["code"] == "09220" and row["insurance_code"] == "111")
    assert vzp_ekg["count"] >= 1
    csv = client.get("/api/reports/monthly.csv", params={"month": "2026-10"}).text
    assert "CELKEM" in csv


def test_statistika_spolehlivosti_z_historie(client):
    kratka = next(p for p in client.get("/api/patients", params={"q": "kratka"}).json())
    assert (kratka["no_shows"], kratka["cancellations"], kratka["unreliable"]) == (3, 2, True)


def test_nepritomnost_lekare_a_preplanovani(client):
    assert client.post("/api/absences", json={"doctor_id": 1, "date": "2026-11-02"}).status_code == 201
    affected = client.get("/api/absences/affected").json()
    assert affected and all(a["date"] == "2026-11-02" for a in affected)
    assert book(client, "11:00").status_code == 422

    original = affected[0]
    r = client.post("/api/appointments", json={
        "doctor_id": 1, "patient_id": original["patient_id"], "date": "2026-11-03", "time": "10:00",
        "duration": original["duration"], "reason": original["reason"], "reschedule_from_id": original["id"],
    })
    assert r.status_code == 201
    after = {a["id"]: a for a in client.get("/api/absences/affected").json()}
    assert after[original["id"]]["status"] == "CANCELLED"
    assert after[original["id"]]["cancelled_by"] == "CLINIC"


def test_tydenni_prehled(client):
    days = client.get("/api/availability", params={"doctor_id": 1, "week_of": MON}).json()
    assert len(days) == 5 and days[3]["works"] is False  # Hrubá ve čtvrtek neordinuje
    monday = {s["time"]: s["state"] for s in days[0]["slots"]}
    assert monday["09:00"] == "BOOKED" and monday["08:00"] == "FREE"


def test_pacient_duplicita_a_validace(client):
    r = client.post("/api/patients", json={"first_name": "X", "last_name": "Y", "birth_year": 1954,
                                           "insurance_id": "5458120316", "insurance_code": "111"})
    assert r.status_code == 409
    r = client.post("/api/patients", json={"first_name": "Jan", "last_name": "Nový", "birth_year": 1990,
                                           "insurance_id": "900101/0007", "insurance_code": "111",
                                           "phone": "777123456"})
    assert r.status_code == 201 and r.json()["phone"] == "777 123 456"


def test_cas_v_minulosti(client):
    r = book(client, "09:00", day="2026-10-29", doctor_id=2)
    assert r.status_code == 422 and "minulosti" in r.json()["detail"]
