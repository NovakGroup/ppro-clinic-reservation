"""Zdroj aktuálního data a času. V testech se nahrazuje pevným datem."""
from datetime import date, datetime


class Clock:
    def today(self) -> date:
        return date.today()

    def now(self) -> datetime:
        return datetime.now()
