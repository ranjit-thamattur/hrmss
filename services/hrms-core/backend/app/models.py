"""Database model. One deployment = one client, with ONE DATABASE per client (decision 0006), so isolation
between clients is by separate database and user pool. Inside the client, data is scoped by
entity and location.

Dated data (salary structures, entity allocations, assignments, policies, statutory rules) has
effective_from / effective_to so payroll always uses what was in force on the day.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


Money = Numeric(14, 2)


# ---------------------------------------------------------------- organisation
class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    pan: Mapped[str | None] = mapped_column(String(20))
    tan: Mapped[str | None] = mapped_column(String(20))
    pf_code: Mapped[str | None] = mapped_column(String(40))
    esi_code: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(40), default="Tamil Nadu")
    tally_company: Mapped[str | None] = mapped_column(String(200))
    statutory: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"PF": true, "ESI": true, ...} applicability (SCRUM-119)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    state: Mapped[str] = mapped_column(String(40), default="Tamil Nadu")
    weekly_off: Mapped[int] = mapped_column(Integer, default=6)  # 0=Mon … 6=Sun
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Designation(Base):
    __tablename__ = "designations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    min_gross: Mapped[Decimal] = mapped_column(Money, default=0)
    max_gross: Mapped[Decimal] = mapped_column(Money, default=0)
    notice_days: Mapped[int] = mapped_column(Integer, default=30)


class Shift(Base):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5))
    break_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_off: Mapped[bool] = mapped_column(Boolean, default=False)
    is_night: Mapped[bool] = mapped_column(Boolean, default=False)


class Holiday(Base):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(120))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))  # null = all locations


class PolicyVersion(Base):
    """Dated settings: leave quotas, OT, notice, cut-off, missed-punch rule, approval chains…"""
    __tablename__ = "policy_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[Any] = mapped_column(JSON)
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StatutoryRuleVersion(Base):
    """The full payroll rule set (see domain.payroll_engine.DEFAULT_RULES), versioned by date."""
    __tablename__ = "statutory_rule_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))  # null = all entities
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- employees
class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), default="")
    gender: Mapped[str | None] = mapped_column(String(10))
    dob: Mapped[date | None] = mapped_column(Date)
    doj: Mapped[date] = mapped_column(Date)
    dol: Mapped[date | None] = mapped_column(Date)  # last working day
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | notice | exited
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(5), default="ta")  # ta | en | hi
    address: Mapped[str | None] = mapped_column(Text)
    pan_enc: Mapped[str | None] = mapped_column(Text)
    aadhaar_last4: Mapped[str | None] = mapped_column(String(4))  # full Aadhaar is never stored
    bank_account_enc: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(String(120))
    ifsc: Mapped[str | None] = mapped_column(String(11))
    uan: Mapped[str | None] = mapped_column(String(20))
    esic_no: Mapped[str | None] = mapped_column(String(20))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    designation_id: Mapped[int | None] = mapped_column(ForeignKey("designations.id"))
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))  # HOD / reporting manager
    shift_code: Mapped[str] = mapped_column(String(10), default="G")
    pf_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    esi_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    pt_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    lwf_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    biometric_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Assignment(Base):
    """History of location/department/designation/grade/status with effective dates."""
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    designation_id: Mapped[int | None] = mapped_column(ForeignKey("designations.id"))
    grade_id: Mapped[int | None] = mapped_column(ForeignKey("grades.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")


class SalaryStructure(Base):
    __tablename__ = "salary_structures"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    components: Mapped[dict[str, str]] = mapped_column(JSON)  # {"BASIC": "10000", "HRA": "4000", …}
    monthly_gross: Mapped[Decimal] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual | import | increment


class EntityAllocation(Base):
    """Who pays the employee: one or more entities, by percent or fixed amount (split salaries)."""
    __tablename__ = "entity_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(10), default="percent")  # percent | fixed
    value: Mapped[Decimal] = mapped_column(Money, default=100)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class EmployeeDocument(Base):
    __tablename__ = "employee_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(80))
    number_masked: Mapped[str | None] = mapped_column(String(40))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    file_key: Mapped[str | None] = mapped_column(String(300))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    new_value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_by: Mapped[str] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- users and access
class AppUser(Base):
    """An employee record does not give software access. A user is created separately and
    provisioned to the identity provider (Cognito) and the biometric device, each with its own status."""
    __tablename__ = "app_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    entity_scope: Mapped[list[int]] = mapped_column(JSON, default=list)  # empty = all
    location_scope: Mapped[list[int]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    identity_sub: Mapped[str | None] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(300))  # local auth mode only
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProvisioningTask(Base):
    __tablename__ = "provisioning_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    target: Mapped[str] = mapped_column(String(20))  # identity | biometric
    action: Mapped[str] = mapped_column(String(20))  # create | disable | enable | groups
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done | failed | manual
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AuditLog(Base):
    """Append-only. On Postgres a trigger rejects UPDATE and DELETE (see migration 0001)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(40), index=True)
    employee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    before: Mapped[Any | None] = mapped_column(JSON)
    after: Mapped[Any | None] = mapped_column(JSON)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # employees | salary | punches | inputs
    filename: Mapped[str] = mapped_column(String(300))
    uploaded_by: Mapped[str] = mapped_column(String(200))
    total: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- attendance and leave
class RosterEntry(Base):
    __tablename__ = "roster"
    __table_args__ = (UniqueConstraint("employee_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    shift_code: Mapped[str] = mapped_column(String(10))


class Punch(Base):
    __tablename__ = "punches"
    __table_args__ = (UniqueConstraint("employee_id", "punched_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    punched_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # local time at the property
    device_id: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(10), default="excel")  # api | excel | manual
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))


class AttendanceDay(Base):
    __tablename__ = "attendance_days"
    __table_args__ = (UniqueConstraint("employee_id", "work_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    shift_code: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    first_in: Mapped[datetime | None] = mapped_column(DateTime)
    last_out: Mapped[datetime | None] = mapped_column(DateTime)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ot_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    regularised: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Regularisation(Base):
    __tablename__ = "regularisations"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # missed_punch | ot
    in_time: Mapped[str | None] = mapped_column(String(5))
    out_time: Mapped[str | None] = mapped_column(String(5))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_by: Mapped[str] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LeaveType(Base):
    __tablename__ = "leave_types"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    annual_quota: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    paid: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaveBalance(Base):
    __tablename__ = "leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "leave_code", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_code: Mapped[str] = mapped_column(ForeignKey("leave_types.code"))
    year: Mapped[int] = mapped_column(Integer)
    opening: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    used: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_code: Mapped[str] = mapped_column(ForeignKey("leave_types.code"))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending_hod")  # pending_hod | pending_hr | approved | rejected | cancelled
    requested_by: Mapped[str] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- payroll
class MonthlyInput(Base):
    __tablename__ = "monthly_inputs"
    __table_args__ = (UniqueConstraint("period", "employee_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    code: Mapped[str] = mapped_column(String(30))  # SERVICE_CHARGE | INCENTIVE | ARREAR | ADVANCE | LOAN_EMI | OTHER_DEDUCTION | TDS_OVERRIDE
    amount: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(String(300))


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("entity_id", "period", "run_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    period: Mapped[str] = mapped_column(String(7))
    run_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="calculated")  # calculated | reviewed | hr_approved | finance_approved | locked
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)  # rule snapshot used
    missed_punch_rule: Mapped[str | None] = mapped_column(String(10))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    totals: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    prepared_by: Mapped[str] = mapped_column(String(200))
    hr_approved_by: Mapped[str | None] = mapped_column(String(200))
    finance_approved_by: Mapped[str | None] = mapped_column(String(200))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payslips_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PayrollLine(Base):
    __tablename__ = "payroll_lines"
    __table_args__ = (UniqueConstraint("run_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    paid_days: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    lop_days: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    earnings: Mapped[dict[str, str]] = mapped_column(JSON)
    deductions: Mapped[dict[str, str]] = mapped_column(JSON)
    employer: Mapped[dict[str, str]] = mapped_column(JSON)
    gross: Mapped[Decimal] = mapped_column(Money)
    total_deductions: Mapped[Decimal] = mapped_column(Money)
    net: Mapped[Decimal] = mapped_column(Money)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=100)
    full_result: Mapped[dict[str, Any]] = mapped_column(JSON)  # whole-person result incl. other entities' shares
    flags: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    decision: Mapped[str | None] = mapped_column(String(10))  # accept | hold
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    hold: Mapped[bool] = mapped_column(Boolean, default=False)


class StatutoryChallan(Base):
    __tablename__ = "statutory_challans"
    __table_args__ = (UniqueConstraint("item_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_key: Mapped[str] = mapped_column(String(80))  # e.g. EPF:VHPL:2026-11
    challan_no: Mapped[str] = mapped_column(String(80))
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    entered_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- exit
class ExitCase(Base):
    __tablename__ = "exit_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    resigned_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    last_working_day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="notice")  # notice | fnf_calculated | fnf_approved | closed
    fnf: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fnf_due_on: Mapped[date | None] = mapped_column(Date)
    fnf_approved_by: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClearanceTask(Base):
    __tablename__ = "clearance_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    exit_id: Mapped[int] = mapped_column(ForeignKey("exit_cases.id", ondelete="CASCADE"), index=True)
    department: Mapped[str] = mapped_column(String(60))
    item: Mapped[str] = mapped_column(String(200))
    owner: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    done_by: Mapped[str | None] = mapped_column(String(200))


# ---------------------------------------------------------------- performance
class ReviewCycle(Base):
    __tablename__ = "review_cycles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    opens_on: Mapped[date] = mapped_column(Date)
    closes_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    templates: Mapped[dict[str, list[str]]] = mapped_column(JSON, default=dict)  # department -> KRAs


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("cycle_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("review_cycles.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    self_ratings: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    self_rating: Mapped[int | None] = mapped_column(Integer)
    manager_rating: Mapped[int | None] = mapped_column(Integer)
    manager_comment: Mapped[str | None] = mapped_column(Text)
    final_rating: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending_self")  # pending_self | pending_manager | pending_calibration | done


class Increment(Base):
    __tablename__ = "increments"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("review_cycles.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | hr_approved | gm_approved | applied
    hr_by: Mapped[str | None] = mapped_column(String(200))
    gm_by: Mapped[str | None] = mapped_column(String(200))


# ---------------------------------------------------------------- communication
class Circular(Base):
    __tablename__ = "circulars"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[dict[str, str]] = mapped_column(JSON)  # {"en": …, "ta": …, "hi": …}
    audience: Mapped[dict[str, list[int]]] = mapped_column(JSON, default=dict)  # entity_ids / location_ids / department_ids
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[str | None] = mapped_column(String(200))
    recipients: Mapped[int] = mapped_column(Integer, default=0)


class CircularRead(Base):
    __tablename__ = "circular_reads"
    __table_args__ = (UniqueConstraint("circular_id", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    circular_id: Mapped[int] = mapped_column(ForeignKey("circulars.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Outbox(Base):
    """Messages to send (WhatsApp/email). Sending is switched on once the WhatsApp Business account exists."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    to: Mapped[str] = mapped_column(String(200))
    employee_id: Mapped[int | None] = mapped_column(Integer)
    template: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- monitoring (SCRUM-130, migration 0002)
class MonitorSample(Base):
    """One health check of one core service. Kept for MONITOR_KEEP_DAYS days."""
    __tablename__ = "monitor_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    service: Mapped[str] = mapped_column(String(20), index=True)  # web | api | database | signin | biometric
    status: Mapped[str] = mapped_column(String(10))  # up | degraded | down | unknown
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(String(300))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class MonitorAlert(Base):
    """Raised when a service is down or degraded on consecutive checks; resolved when it recovers."""
    __tablename__ = "monitor_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # critical | warning
    message: Mapped[str] = mapped_column(String(300))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
