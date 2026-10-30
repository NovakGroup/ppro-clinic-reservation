"""Počáteční schéma ordinace.

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

appointment_status = sa.Enum("PLANNED", "COMPLETED", "CANCELLED", "NO_SHOW", name="appointment_status")
cancelled_by = sa.Enum("PATIENT", "CLINIC", name="cancelled_by")


def upgrade() -> None:
    # btree_gist umožní v jednom exclusion constraintu kombinovat "=" (lékař) a "&&" (překryv času)
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "doctor",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("title", sa.String(20), nullable=False, server_default="MUDr."),
        sa.Column("specialization", sa.String(80), nullable=False),
        sa.Column("email", sa.String(120)),
        sa.Column("phone", sa.String(20)),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "doctor_schedule",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("doctor.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("location", sa.String(120), nullable=False),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_schedule_day"),
        sa.CheckConstraint("start_time < end_time", name="ck_schedule_range"),
    )

    op.create_table(
        "patient",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
        sa.Column("birth_year", sa.Integer, nullable=False),
        sa.Column("insurance_id", sa.String(11), nullable=False, unique=True),
        sa.Column("insurance_code", sa.String(3), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("birth_year BETWEEN 1900 AND 2100", name="ck_patient_birth_year"),
    )
    op.create_index("ix_patient_last_name", "patient", ["last_name"])
    op.create_index("ix_patient_phone", "patient", ["phone"])

    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("doctor.id"), nullable=False),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patient.id"), nullable=False),
        sa.Column("start_at", sa.DateTime, nullable=False),
        sa.Column("end_at", sa.DateTime, nullable=False),
        sa.Column("status", appointment_status, nullable=False, server_default="PLANNED"),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("cancelled_by", cancelled_by),
        sa.Column("cancellation_reason", sa.String(255)),
        sa.Column("cancelled_at", sa.DateTime),
        sa.Column("patient_called", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("rescheduled_to_id", sa.Integer, sa.ForeignKey("appointment.id")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("start_at < end_at", name="ck_appointment_range"),
    )
    op.create_index("ix_appointment_doctor_id", "appointment", ["doctor_id"])
    op.create_index("ix_appointment_patient_id", "appointment", ["patient_id"])
    # Klíčové pravidlo klienta vynucené databází: aktivní rezervace jednoho lékaře se nesmí překrývat.
    # tsrange(start, end) je polootevřený interval [start, end), navazující termíny jsou tedy povolené.
    op.execute(
        """
        ALTER TABLE appointment ADD CONSTRAINT ex_appointment_no_overlap
        EXCLUDE USING gist (doctor_id WITH =, tsrange(start_at, end_at) WITH &&)
        WHERE (status IN ('PLANNED', 'COMPLETED'))
        """
    )

    op.create_table(
        "visit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointment.id"), nullable=False, unique=True),
        sa.Column("visit_date", sa.Date, nullable=False),
        sa.Column("clinical_note", sa.Text, nullable=False, server_default=""),
    )

    op.create_table(
        "medical_procedure",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("points", sa.Integer, nullable=False),
    )

    # Vazba M:N Návštěva ↔ Výkon s atributy počet a body platné v době výkonu
    op.create_table(
        "visit_procedure",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("visit_id", sa.Integer, sa.ForeignKey("visit.id"), nullable=False),
        sa.Column("procedure_id", sa.Integer, sa.ForeignKey("medical_procedure.id"), nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("billed_points", sa.Integer, nullable=False),
        sa.CheckConstraint("count BETWEEN 1 AND 10", name="ck_visit_procedure_count"),
        sa.CheckConstraint("billed_points >= 0", name="ck_visit_procedure_points"),
    )
    op.create_index("ix_visit_procedure_visit_id", "visit_procedure", ["visit_id"])

    op.create_table(
        "doctor_absence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("doctor.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("reason", sa.String(255), nullable=False, server_default="Nemoc"),
        sa.UniqueConstraint("doctor_id", "date", name="uq_absence_doctor_date"),
    )

    # "Historie pacienta se nemaže": databáze odmítne DELETE pacienta, rezervace i návštěvy.
    op.execute(
        """
        CREATE FUNCTION forbid_history_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Mazání historie (%) není povoleno', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("patient", "appointment", "visit"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_delete()"
        )


def downgrade() -> None:
    for table in ("patient", "appointment", "visit"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS forbid_history_delete()")
    for table in ("doctor_absence", "visit_procedure", "medical_procedure", "visit", "appointment",
                  "patient", "doctor_schedule", "doctor"):
        op.drop_table(table)
    cancelled_by.drop(op.get_bind(), checkfirst=True)
    appointment_status.drop(op.get_bind(), checkfirst=True)
