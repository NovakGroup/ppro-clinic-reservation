"""Doménové výjimky. Prezentační vrstva je převádí na HTTP odpovědi."""


class DomainError(Exception):
    """Základ všech chyb, které má uživatel vidět jako srozumitelnou hlášku."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(DomainError):
    status_code = 422


class BookingRuleError(DomainError):
    """Porušení obchodního pravidla (ordinační hodiny, víkend, minulost...)."""

    status_code = 422


class ConflictError(DomainError):
    """Kolize s existujícími daty (překryv termínů, duplicitní pacient)."""

    status_code = 409


class NotFoundError(DomainError):
    status_code = 404
