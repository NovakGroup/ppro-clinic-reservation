"""REST endpointy (prezentační vrstva).

Každý endpoint jen převezme vstup, zavolá službu a vrátí DTO.
Žádné obchodní rozhodování ani SQL tu není.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from app.api import deps, mappers, schemas
from app.services.booking import BookingRequest, BookingService
from app.services.clinic import (
    AbsenceService,
    CatalogService,
    NewPatient,
    PatientService,
    ReportService,
    VisitItem,
    VisitService,
)

router = APIRouter(prefix="/api")


# ---------- číselníky ----------
@router.get("/doctors", response_model=list[schemas.DoctorOut], tags=["číselníky"])
def list_doctors(svc: CatalogService = Depends(deps.catalog)):
    return [mappers.doctor(d) for d in svc.doctors()]


@router.get("/procedures", response_model=list[schemas.ProcedureOut], tags=["číselníky"])
def list_procedures(svc: CatalogService = Depends(deps.catalog)):
    return [mappers.procedure(p) for p in svc.procedures()]


# ---------- pacienti ----------
@router.get("/patients", response_model=list[schemas.PatientOut], tags=["pacienti"])
def search_patients(q: str | None = None, svc: PatientService = Depends(deps.patients)):
    return [mappers.patient(v) for v in svc.search(q)]


@router.post("/patients", response_model=schemas.PatientOut, status_code=201, tags=["pacienti"])
def create_patient(body: schemas.PatientIn, svc: PatientService = Depends(deps.patients)):
    return mappers.patient(svc.create(NewPatient(**body.model_dump())))


# ---------- rezervace ----------
@router.get("/appointments", response_model=list[schemas.AppointmentOut], tags=["rezervace"])
def list_appointments(
    date_from: date | None = None,
    date_to: date | None = None,
    doctor_id: int | None = None,
    svc: CatalogService = Depends(deps.catalog),
):
    return [mappers.appointment(a) for a in svc.appointments(date_from, date_to, doctor_id)]


@router.post("/appointments", response_model=schemas.AppointmentOut, status_code=201, tags=["rezervace"])
def create_appointment(body: schemas.AppointmentIn, svc: BookingService = Depends(deps.booking)):
    req = BookingRequest(
        doctor_id=body.doctor_id, patient_id=body.patient_id, day=body.date, start_time=body.time,
        duration=body.duration, reason=body.reason, reschedule_from_id=body.reschedule_from_id,
    )
    return mappers.appointment(svc.create(req))


@router.post("/appointments/{appointment_id}/cancel", response_model=schemas.AppointmentOut, tags=["rezervace"])
def cancel_appointment(appointment_id: int, body: schemas.CancelIn | None = None,
                       svc: BookingService = Depends(deps.booking)):
    return mappers.appointment(svc.cancel(appointment_id, body.reason if body else None))


@router.post("/appointments/{appointment_id}/no-show", response_model=schemas.AppointmentOut, tags=["rezervace"])
def no_show(appointment_id: int, svc: BookingService = Depends(deps.booking)):
    return mappers.appointment(svc.mark_no_show(appointment_id))


@router.post("/appointments/{appointment_id}/complete", response_model=schemas.AppointmentOut, tags=["rezervace"])
def complete(appointment_id: int, svc: BookingService = Depends(deps.booking)):
    return mappers.appointment(svc.complete(appointment_id))


@router.post("/appointments/{appointment_id}/called", response_model=schemas.AppointmentOut, tags=["rezervace"])
def mark_called(appointment_id: int, svc: BookingService = Depends(deps.booking)):
    return mappers.appointment(svc.mark_called(appointment_id))


@router.get("/availability", response_model=list[schemas.DayOut], tags=["rezervace"])
def week_availability(doctor_id: int, week_of: date = Query(description="libovolný den v týdnu"),
                      svc: BookingService = Depends(deps.booking)):
    return [mappers.day(d) for d in svc.week_availability(doctor_id, week_of)]


# ---------- návštěvy a výkony ----------
@router.get("/appointments/{appointment_id}/visit", response_model=schemas.VisitOut, tags=["návštěvy"])
def get_visit(appointment_id: int, svc: VisitService = Depends(deps.visits)):
    return mappers.visit(appointment_id, svc.get(appointment_id))


@router.put("/appointments/{appointment_id}/visit", response_model=schemas.VisitOut, tags=["návštěvy"])
def save_visit(appointment_id: int, body: schemas.VisitIn, svc: VisitService = Depends(deps.visits)):
    items = [VisitItem(i.procedure_id, i.count) for i in body.items]
    return mappers.visit(appointment_id, svc.save(appointment_id, body.note, items))


# ---------- výkazy ----------
@router.get("/reports/monthly", response_model=schemas.ReportOut, tags=["výkazy"])
def monthly_report(month: str, doctor_id: int | None = None, svc: ReportService = Depends(deps.reports)):
    return mappers.report(svc.monthly(month, doctor_id))


@router.get("/reports/monthly.csv", tags=["výkazy"])
def monthly_report_csv(month: str, doctor_id: int | None = None, svc: ReportService = Depends(deps.reports)):
    filename = f"vykaz-{month}{f'-lekar{doctor_id}' if doctor_id else ''}.csv"
    return Response(
        content=svc.monthly_csv(month, doctor_id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- nepřítomnost lékaře ----------
@router.get("/absences", response_model=list[schemas.AbsenceOut], tags=["výpadek lékaře"])
def list_absences(svc: AbsenceService = Depends(deps.absences)):
    return [mappers.absence(a) for a in svc.list()]


@router.post("/absences", response_model=schemas.AbsenceOut, status_code=201, tags=["výpadek lékaře"])
def add_absence(body: schemas.AbsenceIn, svc: AbsenceService = Depends(deps.absences)):
    return mappers.absence(svc.add(body.doctor_id, body.date, body.reason))


@router.delete("/absences/{absence_id}", status_code=204, tags=["výpadek lékaře"])
def remove_absence(absence_id: int, svc: AbsenceService = Depends(deps.absences)):
    svc.remove(absence_id)
    return Response(status_code=204)


@router.get("/absences/affected", response_model=list[schemas.AppointmentOut], tags=["výpadek lékaře"])
def affected(svc: AbsenceService = Depends(deps.absences)):
    return [mappers.appointment(a) for a in svc.affected_appointments()]
