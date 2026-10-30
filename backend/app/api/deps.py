"""FastAPI závislosti – endpointy dostávají rovnou službu aplikační vrstvy."""
from fastapi import Depends

from app import container
from app.services.booking import BookingService
from app.services.clinic import AbsenceService, CatalogService, PatientService, ReportService, VisitService


def booking(uow=Depends(container.get_uow), clock=Depends(container.get_clock)) -> BookingService:
    return container.booking_service(uow, clock)


def patients(uow=Depends(container.get_uow), clock=Depends(container.get_clock)) -> PatientService:
    return container.patient_service(uow, clock)


def visits(uow=Depends(container.get_uow)) -> VisitService:
    return container.visit_service(uow)


def reports(uow=Depends(container.get_uow)) -> ReportService:
    return container.report_service(uow)


def absences(uow=Depends(container.get_uow), clock=Depends(container.get_clock)) -> AbsenceService:
    return container.absence_service(uow, clock)


def catalog(uow=Depends(container.get_uow)) -> CatalogService:
    return container.catalog_service(uow)
