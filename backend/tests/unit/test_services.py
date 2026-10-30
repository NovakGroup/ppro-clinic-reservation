"""Jednotkové testy aplikační vrstvy nad in-memory repozitáři (bez databáze)."""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

from app.db.models import AppointmentStatus, CancelledBy
from app.domain.errors import BookingRuleError, ConflictError, ValidationError
from app.services.booking import BookingRequest, BookingService
from app.services.clinic import NewPatient, PatientService, VisitItem, VisitService
from tests.unit.fakes import FakeUnitOfWork

TODAY = date(2026, 10, 30)
MON = date(2026, 11, 2)
TUE = date(2026, 11, 3)


@pytest.fixture
def uow():
    return FakeUnitOfWork()


@pytest.fixture
def booking(uow):
    return BookingService(uow, today=lambda: TODAY, now=lambda: datetime(2026, 10, 30, 12, 0))


def req(hhmm="09:00", duration=15, doctor=1, day=MON, **kw):
    h, m = map(int, hhmm.split(":"))
    return BookingRequest(doctor_id=doctor, patient_id=1, day=day, start_time=time(h, m), duration=duration,
                          reason=kw.pop("reason", "Kontrola"), **kw)


class TestBooking:
    def test_zalozi_rezervaci_a_zamkne_lekare(self, booking, uow):
        a = booking.create(req("09:00", 30))
        assert a.status == AppointmentStatus.PLANNED
        assert a.end_at == datetime(2026, 11, 2, 9, 30)
        assert uow.appointments.locked == [1] and uow.commits == 1

    def test_kolize_je_odmitnuta(self, booking):
        booking.create(req("09:00", 30))
        with pytest.raises(ConflictError, match="KOLIZE"):
            booking.create(req("09:15"))

    def test_navazujici_termin_je_povolen(self, booking):
        booking.create(req("08:15"))
        assert booking.create(req("08:30")).start_at.time() == time(8, 30)

    def test_jiny_lekar_ve_stejny_cas_je_povolen(self, booking):
        booking.create(req("09:00", day=TUE))
        booking.create(req("09:00", day=TUE, doctor=2))

    def test_zruseny_termin_slot_uvolni(self, booking):
        a = booking.create(req("09:00"))
        booking.cancel(a.id)
        assert booking.create(req("09:00")).id != a.id

    def test_prazdny_duvod_dostane_vychozi_text(self, booking):
        assert booking.create(req(reason="  ")).reason == "Běžná kontrola"

    def test_externi_pracoviste(self, booking):
        with pytest.raises(BookingRuleError, match="jiné adrese"):
            booking.create(req("12:00", doctor=2, day=TUE))

    def test_den_nepritomnosti(self, booking, uow):
        uow.absences.days.add((1, MON))
        with pytest.raises(BookingRuleError, match="nepřítom"):
            booking.create(req("09:00"))


class TestStatusChanges:
    def test_zruseni_pacientem(self, booking):
        a = booking.cancel(booking.create(req()).id)
        assert a.status == AppointmentStatus.CANCELLED and a.cancelled_by == CancelledBy.PATIENT

    def test_odbavenou_navstevu_nelze_zrusit(self, booking, uow):
        a = booking.create(req())
        a.status = AppointmentStatus.COMPLETED
        with pytest.raises(BookingRuleError):
            booking.cancel(a.id)

    def test_absenci_ani_prichod_nelze_zapsat_dopredu(self, booking):
        a = booking.create(req())
        with pytest.raises(BookingRuleError, match="teprve"):
            booking.mark_no_show(a.id)
        with pytest.raises(BookingRuleError):
            booking.complete(a.id)

    def test_preplanovani_zrusi_puvodni_bez_penalizace_pacienta(self, booking):
        original = booking.create(req("09:00"))
        new = booking.create(req("09:00", day=TUE, reschedule_from_id=original.id))
        assert original.status == AppointmentStatus.CANCELLED
        assert original.cancelled_by == CancelledBy.CLINIC
        assert original.rescheduled_to_id == new.id

    def test_preplanovani_na_prekryvajici_cas_tehoz_lekare(self, booking):
        original = booking.create(req("09:00", 30))
        new = booking.create(req("09:15", 30, reschedule_from_id=original.id))
        assert new.start_at.time() == time(9, 15)


class TestWeekAvailability:
    def test_tyden_obsahuje_obsazene_a_volne_sloty(self, booking):
        booking.create(req("09:00", 30))
        days = booking.week_availability(1, MON)
        assert [d.day.weekday() for d in days] == [0, 1, 2, 3, 4]
        monday = {s.time: s.state for s in days[0].slots}
        assert monday[time(9, 0)] == "BOOKED" and monday[time(9, 15)] == "BOOKED"
        assert monday[time(9, 30)] == "FREE"
        assert not days[2].works  # Hrubá ve středu v testovacích datech neordinuje


class TestPatients:
    def test_duplicitni_rodne_cislo(self, uow):
        svc = PatientService(uow, today=lambda: TODAY)
        with pytest.raises(ConflictError, match="již v kartotéce"):
            svc.create(NewPatient("Marie", "Krátká", 1954, "5458120316", "111", None))

    def test_rok_narozeni_musi_odpovidat_rc(self, uow):
        svc = PatientService(uow, today=lambda: TODAY)
        with pytest.raises(ValidationError, match="neodpovídá"):
            svc.create(NewPatient("Jan", "Nový", 1985, "9001010007", "111", None))

    def test_ulozi_normalizovane_udaje(self, uow):
        svc = PatientService(uow, today=lambda: TODAY)
        p = svc.create(NewPatient(" Jan ", "Nový", 1990, "9001010007", "111", "+420777123456")).patient
        assert (p.first_name, p.insurance_id, p.phone) == ("Jan", "900101/0007", "777 123 456")


class TestVisits:
    def _completed(self, booking):
        a = booking.create(req())
        a.status = AppointmentStatus.COMPLETED
        return a

    def test_vykon_k_neuskutecnene_navsteve(self, booking, uow):
        a = booking.create(req())
        with pytest.raises(BookingRuleError, match="neuskutečnila"):
            VisitService(uow).save(a.id, "", [VisitItem(1, 1)])

    def test_stejne_vykony_se_sectou(self, booking, uow):
        a = self._completed(booking)
        v = VisitService(uow).save(a.id, "ok", [VisitItem(1, 2), VisitItem(1, 1), VisitItem(2, 1)])
        assert sorted((p.procedure_id, p.count) for p in v.procedures) == [(1, 3), (2, 1)]

    def test_soucet_nad_limit(self, booking, uow):
        a = self._completed(booking)
        with pytest.raises(ValidationError):
            VisitService(uow).save(a.id, "", [VisitItem(1, 6), VisitItem(1, 5)])

    def test_body_se_historizuji(self, booking, uow):
        a = self._completed(booking)
        svc = VisitService(uow)
        svc.save(a.id, "", [VisitItem(1, 1)])
        uow.procedures.items[1] = SimpleNamespace(id=1, code="09511", name="Cílené vyšetření", points=999)
        v = svc.save(a.id, "", [VisitItem(1, 2), VisitItem(2, 1)])
        points = {p.procedure_id: p.billed_points for p in v.procedures}
        assert points == {1: 150, 2: 180}

    def test_navsteva_bez_vykonu(self, booking, uow):
        a = self._completed(booking)
        with pytest.raises(ValidationError, match="alespoň jeden"):
            VisitService(uow).save(a.id, "", [])
