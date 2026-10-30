"""Převod výsledků aplikační vrstvy na DTO (žádná logika, jen tvar dat)."""
from app.api import schemas
from app.domain.rules import MAIN_LOCATION


def doctor(d) -> schemas.DoctorOut:
    return schemas.DoctorOut(
        id=d.id,
        name=d.full_name,
        specialization=d.specialization,
        schedules=[
            schemas.ScheduleOut(
                day_of_week=s.day_of_week,
                start=s.start_time.strftime("%H:%M"),
                end=s.end_time.strftime("%H:%M"),
                location=s.location,
                external=s.location != MAIN_LOCATION,
            )
            for s in d.schedules
        ],
    )


def procedure(p) -> schemas.ProcedureOut:
    return schemas.ProcedureOut(id=p.id, code=p.code, name=p.name, points=p.points)


def patient(view) -> schemas.PatientOut:
    p = view.patient
    return schemas.PatientOut(
        id=p.id, first_name=p.first_name, last_name=p.last_name, birth_year=p.birth_year,
        insurance_id=p.insurance_id, insurance_code=p.insurance_code, phone=p.phone,
        cancellations=view.cancellations, no_shows=view.no_shows, unreliable=view.unreliable,
    )


def appointment(a) -> schemas.AppointmentOut:
    return schemas.AppointmentOut(
        id=a.id, doctor_id=a.doctor_id, patient_id=a.patient_id,
        date=a.start_at.date(), time=a.start_at.strftime("%H:%M"), end_time=a.end_at.strftime("%H:%M"),
        duration=a.duration, status=a.status.value, reason=a.reason,
        cancelled_by=a.cancelled_by.value if a.cancelled_by else None,
        cancellation_reason=a.cancellation_reason, patient_called=bool(a.patient_called),
        rescheduled_to_id=a.rescheduled_to_id, has_visit=a.visit is not None,
    )


def visit(appointment_id: int, v) -> schemas.VisitOut:
    if v is None:
        return schemas.VisitOut(appointment_id=appointment_id, saved=False, note="", items=[], total_points=0)
    items = [
        schemas.VisitItemOut(procedure_id=vp.procedure_id, code=vp.procedure.code, name=vp.procedure.name,
                             count=vp.count, points=vp.billed_points)
        for vp in v.procedures
    ]
    return schemas.VisitOut(appointment_id=appointment_id, saved=True, note=v.clinical_note, items=items,
                            total_points=sum(i.count * i.points for i in items))


def report(r) -> schemas.ReportOut:
    return schemas.ReportOut(
        month=r.month, doctor_id=r.doctor_id,
        rows=[schemas.ReportRowOut(insurance_code=x.insurance_code, insurance_name=x.insurance_name, code=x.code,
                                   name=x.name, points=x.points, count=x.count, total=x.total) for x in r.rows],
        total_points=r.total_points, visits=r.visits, patients=r.patients, cancelled_or_no_show=r.cancelled_or_no_show,
    )


def absence(a) -> schemas.AbsenceOut:
    return schemas.AbsenceOut(id=a.id, doctor_id=a.doctor_id, date=a.date, reason=a.reason)


def day(d) -> schemas.DayOut:
    return schemas.DayOut(
        date=d.day, works=d.works, absent=d.absent,
        slots=[schemas.SlotOut(time=s.time.strftime("%H:%M"), state=s.state, appointment_id=s.appointment_id)
               for s in d.slots],
    )
