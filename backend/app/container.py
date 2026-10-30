"""Kompoziční kořen: jediné místo, kde se skládají vrstvy dohromady.

Prezentační vrstva (app.api) odsud dostává hotové služby a nikdy sama
nevytváří repozitáře ani databázové session.
"""
from collections.abc import Iterator

from app.clock import Clock
from app.db.session import get_sessionmaker
from app.repositories.sql import SqlUnitOfWork
from app.services.booking import BookingService
from app.services.clinic import AbsenceService, CatalogService, PatientService, ReportService, VisitService


def get_uow() -> Iterator[SqlUnitOfWork]:
    session = get_sessionmaker()()
    try:
        yield SqlUnitOfWork(session)
    finally:
        session.close()


def get_clock() -> Clock:
    return Clock()


def booking_service(uow: SqlUnitOfWork, clock: Clock) -> BookingService:
    return BookingService(uow, today=clock.today, now=clock.now)


def patient_service(uow: SqlUnitOfWork, clock: Clock) -> PatientService:
    return PatientService(uow, today=clock.today)


def visit_service(uow: SqlUnitOfWork) -> VisitService:
    return VisitService(uow)


def report_service(uow: SqlUnitOfWork) -> ReportService:
    return ReportService(uow)


def absence_service(uow: SqlUnitOfWork, clock: Clock) -> AbsenceService:
    return AbsenceService(uow, today=clock.today)


def catalog_service(uow: SqlUnitOfWork) -> CatalogService:
    return CatalogService(uow)
