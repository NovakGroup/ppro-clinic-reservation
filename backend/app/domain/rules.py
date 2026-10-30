"""Doménová pravidla ordinace.

Čisté funkce bez závislosti na databázi nebo webovém frameworku,
proto se dají snadno testovat jednotkovými testy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.domain.errors import BookingRuleError, ValidationError

SLOT_MINUTES = 15
ALLOWED_DURATIONS = (15, 30, 45, 60)
MAIN_LOCATION = "Na Vyhlídce"
UNRELIABLE_NO_SHOW_LIMIT = 3
MAX_PROCEDURE_COUNT = 10

CZ_DAYS = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]


@dataclass(frozen=True)
class TimeWindow:
    """Jedno okno ordinačních hodin lékaře v daném dni."""

    start: time
    end: time
    location: str

    @property
    def is_external(self) -> bool:
        return self.location != MAIN_LOCATION


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


def overlaps(a: Interval, b: Interval) -> bool:
    """Překryv polootevřených intervalů [start, end).

    Termín 08:15–08:30 a termín 08:30–08:45 se NEpřekrývají.
    """
    return a.start < b.end and b.start < a.end


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def validate_booking_time(
    *,
    start: datetime,
    duration: int,
    today: date,
    windows: list[TimeWindow],
    doctor_absent: bool,
    doctor_name: str,
) -> None:
    """Ověří, že termín leží v ordinačních hodinách lékaře.

    Vyhodí BookingRuleError s textem srozumitelným pro recepci.
    """
    if duration not in ALLOWED_DURATIONS:
        raise ValidationError("Neplatná délka termínu (povoleno 15, 30, 45 nebo 60 minut).")
    if start.date() < today:
        raise BookingRuleError("Termín nelze založit do minulosti.")
    if start.weekday() >= 5:
        raise BookingRuleError("Ordinace je o víkendu uzavřena.")
    if start.second or start.microsecond or start.minute % SLOT_MINUTES:
        raise BookingRuleError(
            f"Čas začátku musí odpovídat {SLOT_MINUTES}minutové mřížce (např. 09:00, 09:15, 09:30, 09:45)."
        )
    if doctor_absent:
        raise BookingRuleError(f"{doctor_name} je v tento den nepřítomen/nepřítomna (evidovaný výpadek).")

    day_name = CZ_DAYS[start.weekday()]
    on_site = [w for w in windows if not w.is_external]
    if not on_site:
        raise BookingRuleError(f"{doctor_name} v tento den ({day_name}) na pracovišti {MAIN_LOCATION} neordinuje.")

    start_min = start.hour * 60 + start.minute
    end_min = start_min + duration
    if any(_minutes(w.start) <= start_min and end_min <= _minutes(w.end) for w in on_site):
        return

    for w in windows:
        if w.is_external and start_min < _minutes(w.end) and _minutes(w.start) < end_min:
            raise BookingRuleError(
                f"{doctor_name} v čase {w.start:%H:%M}–{w.end:%H:%M} ordinuje na jiné adrese ({w.location}). "
                "Termín zde nelze rezervovat."
            )
    hours = ", ".join(f"{w.start:%H:%M}–{w.end:%H:%M}" for w in on_site)
    end_txt = (datetime.combine(start.date(), time()) + timedelta(minutes=end_min)).strftime("%H:%M")
    raise BookingRuleError(
        f"Termín {start:%H:%M}–{end_txt} je mimo ordinační hodiny ({day_name}: {hours}). "
        "Celý termín musí skončit nejpozději v čase konce ordinace."
    )


def generate_slots(windows: list[TimeWindow]) -> list[tuple[time, bool]]:
    """Vrátí sloty po 15 minutách jako dvojice (čas, je_externí)."""
    slots: list[tuple[time, bool]] = []
    for w in sorted(windows, key=lambda x: x.start):
        m = _minutes(w.start)
        while m < _minutes(w.end):
            slots.append((time(m // 60, m % 60), w.is_external))
            m += SLOT_MINUTES
    return slots


def normalize_insurance_id(raw: str) -> str:
    """Ověří rodné číslo (číslo pojištěnce) a vrátí ho ve tvaru XXXXXX/XXXX.

    Kontroluje 9 nebo 10 číslic, platný měsíc (vč. +20/+50/+70) a den,
    u desetimístného čísla dělitelnost 11 (s výjimkou zbytku 10 → kontrolní číslice 0).
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) not in (9, 10):
        raise ValidationError(f"„{raw}“ není platné rodné číslo (musí mít 9 nebo 10 číslic).")
    month = int(digits[2:4])
    day = int(digits[4:6])
    valid_month = 1 <= month <= 12 or 21 <= month <= 32 or 51 <= month <= 62 or 71 <= month <= 82
    if not valid_month or not 1 <= day <= 31:
        raise ValidationError(f"„{raw}“ není platné rodné číslo (neplatný měsíc nebo den).")
    if len(digits) == 10:
        mod = int(digits[:9]) % 11
        expected = 0 if mod == 10 else mod
        if int(digits[9]) != expected:
            raise ValidationError(f"„{raw}“ není platné rodné číslo (nesedí kontrolní číslice).")
    return f"{digits[:6]}/{digits[6:]}"


def birth_year_from_insurance_id(normalized: str) -> int:
    """Odvodí rok narození z rodného čísla (pro kontrolu konzistence)."""
    digits = normalized.replace("/", "")
    yy = int(digits[:2])
    if len(digits) == 9:
        return 1900 + yy
    return 1900 + yy if yy >= 54 else 2000 + yy


def normalize_phone(raw: str | None) -> str | None:
    """Vrátí telefon ve tvaru „777 123 456“, None pro prázdný vstup."""
    if raw is None or not raw.strip():
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("420"):
        digits = digits[3:]
    if len(digits) != 9:
        raise ValidationError("Telefon zadejte jako 9 číslic, případně s předvolbou +420.")
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def validate_procedure_count(count: int) -> None:
    if not 1 <= count <= MAX_PROCEDURE_COUNT:
        raise ValidationError(f"Počet provedení výkonu musí být 1 až {MAX_PROCEDURE_COUNT}.")


def is_unreliable(no_shows: int) -> bool:
    return no_shows >= UNRELIABLE_NO_SHOW_LIMIT


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())
