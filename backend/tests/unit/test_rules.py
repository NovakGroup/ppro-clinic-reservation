"""Jednotkové testy čistých doménových pravidel."""
from datetime import date, datetime, time

import pytest

from app.domain import rules
from app.domain.errors import BookingRuleError, ValidationError

MON = date(2026, 11, 2)  # pondělí
TODAY = date(2026, 10, 30)
HRUBA_MON = [rules.TimeWindow(time(8, 0), time(12, 30), rules.MAIN_LOCATION)]
SVOBODA_TUE = [rules.TimeWindow(time(8, 30), time(12, 0), rules.MAIN_LOCATION),
               rules.TimeWindow(time(12, 0), time(14, 0), "Externí pracoviště")]


def at(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m))


def validate(start, duration=15, windows=HRUBA_MON, absent=False):
    rules.validate_booking_time(start=start, duration=duration, today=TODAY, windows=windows,
                                doctor_absent=absent, doctor_name="MUDr. Test")


class TestOverlap:
    def test_navazujici_terminy_se_neprekryvaji(self):
        a = rules.Interval(at(MON, "08:15"), at(MON, "08:30"))
        b = rules.Interval(at(MON, "08:30"), at(MON, "08:45"))
        assert not rules.overlaps(a, b)

    def test_castecny_prekryv(self):
        a = rules.Interval(at(MON, "08:45"), at(MON, "09:15"))
        b = rules.Interval(at(MON, "09:00"), at(MON, "09:15"))
        assert rules.overlaps(a, b)

    def test_vnoreny_interval(self):
        a = rules.Interval(at(MON, "08:00"), at(MON, "09:00"))
        b = rules.Interval(at(MON, "08:15"), at(MON, "08:30"))
        assert rules.overlaps(a, b) and rules.overlaps(b, a)


class TestBookingTime:
    def test_platny_termin(self):
        validate(at(MON, "09:00"))

    def test_termin_konci_presne_v_konci_ordinace(self):
        validate(at(MON, "12:15"), duration=15)

    @pytest.mark.parametrize("hhmm,duration", [("07:45", 15), ("12:30", 15), ("12:15", 45), ("23:00", 15)])
    def test_mimo_ordinacni_hodiny(self, hhmm, duration):
        with pytest.raises(BookingRuleError, match="mimo ordinační hodiny"):
            validate(at(MON, hhmm), duration=duration)

    def test_mimo_mrizku(self):
        with pytest.raises(BookingRuleError, match="mřížce"):
            validate(at(MON, "09:37"))

    def test_vikend(self):
        with pytest.raises(BookingRuleError, match="víkendu"):
            validate(at(date(2026, 11, 7), "09:00"))

    def test_minulost(self):
        with pytest.raises(BookingRuleError, match="minulosti"):
            validate(at(date(2026, 10, 26), "09:00"))

    def test_lekar_nepritomen(self):
        with pytest.raises(BookingRuleError, match="nepřítom"):
            validate(at(MON, "09:00"), absent=True)

    def test_lekar_ten_den_neordinuje(self):
        with pytest.raises(BookingRuleError, match="neordinuje"):
            validate(at(MON, "09:00"), windows=[])

    def test_externi_pracoviste(self):
        tue = date(2026, 11, 3)
        with pytest.raises(BookingRuleError, match="jiné adrese"):
            validate(at(tue, "12:00"), windows=SVOBODA_TUE)

    def test_termin_zasahujici_do_externiho_bloku(self):
        tue = date(2026, 11, 3)
        with pytest.raises(BookingRuleError, match="jiné adrese"):
            validate(at(tue, "11:45"), duration=30, windows=SVOBODA_TUE)

    def test_neplatna_delka(self):
        with pytest.raises(ValidationError):
            validate(at(MON, "09:00"), duration=20)


class TestSlots:
    def test_generuje_sloty_po_15_minutach(self):
        slots = rules.generate_slots(HRUBA_MON)
        assert len(slots) == 18
        assert slots[0] == (time(8, 0), False) and slots[-1] == (time(12, 15), False)

    def test_externi_sloty_jsou_oznacene(self):
        slots = rules.generate_slots(SVOBODA_TUE)
        assert sum(1 for _, ext in slots if ext) == 8


class TestInsuranceId:
    @pytest.mark.parametrize("raw", ["545812/0316", "5458120316", " 545812 0316 "])
    def test_normalizace(self, raw):
        assert rules.normalize_insurance_id(raw) == "545812/0316"

    @pytest.mark.parametrize("raw", ["abc", "5458120312", "541312/0316", "12345"])
    def test_neplatne(self, raw):
        with pytest.raises(ValidationError):
            rules.normalize_insurance_id(raw)

    def test_rok_narozeni(self):
        assert rules.birth_year_from_insurance_id("545812/0316") == 1954
        assert rules.birth_year_from_insurance_id("016215/1110") == 2001


class TestPhoneAndCounts:
    def test_telefon(self):
        assert rules.normalize_phone("+420 777123456") == "777 123 456"
        assert rules.normalize_phone("") is None
        with pytest.raises(ValidationError):
            rules.normalize_phone("123")

    @pytest.mark.parametrize("count", [0, 11])
    def test_pocet_vykonu(self, count):
        with pytest.raises(ValidationError):
            rules.validate_procedure_count(count)

    def test_rizikovy_pacient(self):
        assert rules.is_unreliable(3) and not rules.is_unreliable(2)
