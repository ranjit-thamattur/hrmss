"""Entity catalogue: one Spec per entity in the Company Setup design (numbers = catalogue numbers).

Everything generic is driven from here: the tables (app/models.py is generated from these specs and a test
checks they match), the request schemas, the REST endpoints, validation, data scope, masking and the Excel
templates. To add a field: add it here, run `python scripts/gen_models.py`, add an Alembic migration.

Not here (own code): 1 Client (from the client YAML), 16 User and role (login identity in Cognito).
Later stage, not built yet: 23 Salary component, 24 Exit clearance department, 25 Letter template.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Field kinds -> stored as
#   str, email, enum, time, period : String      text : Text        int, year : Integer   decimal : Numeric(14,2)
#   bool : Boolean    date : Date    datetime : DateTime   json : JSON   ref : Integer (rid)   refs : JSON (list of rid)
#   secret : Text (encrypted, masked by role)    secret_json : Text (encrypted JSON list, masked by role)
KINDS = {"str", "text", "email", "enum", "time", "period", "int", "year", "decimal", "bool", "date", "datetime", "json", "ref", "refs",
         "secret", "secret_json"}

PATTERNS = {
    "pan": r"^[A-Z]{5}[0-9]{4}[A-Z]$",
    "tan": r"^[A-Z]{4}[0-9]{5}[A-Z]$",
    "gstin": r"^[0-9]{2}[A-Z0-9]{13}$",
    "cin": r"^[A-Z0-9]{21}$",
    "ifsc": r"^[A-Z]{4}0[A-Z0-9]{6}$",
    "aadhaar": r"^[0-9]{12}$",
    "account": r"^[0-9]{6,20}$",
    "pincode": r"^[0-9]{6}$",
    "phone": r"^\+?[0-9][0-9 ]{6,19}$",
    "code": r"^[A-Za-z0-9][A-Za-z0-9_.\-/]*$",
}

ACTIONS = ("view", "create", "change", "deactivate", "approve", "import", "export")
SCOPE_MODES = ("all", "scoped", "team", "self")
STATUTORY_TYPES = ("PF", "ESI", "PT", "LWF", "TDS", "OTHER")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
REQUEST_TYPES = ("leave", "attendance_fix", "overtime", "detail_change", "payroll", "backdated_change")


@dataclass(frozen=True)
class F:
    name: str
    kind: str
    required: bool = False
    ref: str | None = None  # spec key a ref/refs field points to
    choices: tuple[str, ...] = ()
    max_len: int = 200
    pattern: str | None = None  # key in PATTERNS
    default: object = None
    readonly: bool = False  # set by the system; ignored in requests
    label: str = ""

    @property
    def title(self) -> str:
        return self.label or self.name.removesuffix("_rid").removesuffix("_rids").replace("_", " ").capitalize()


@dataclass
class Spec:
    key: str  # URL segment
    table: str
    model: str  # class name in app/models.py
    title: str
    number: int  # catalogue number in the design document
    group: str  # setup (/api/setup/...) or hr (/api/hr/...)
    stage: int
    fields: list[F]
    code_field: str | None = "code"  # unique per client, not case-sensitive
    name_field: str | None = "name"
    # data scope: field -> dimension (entity | location | department); "rid" = the record itself
    scope: dict[str, str] = field(default_factory=dict)
    scope_special: str | None = None  # person | assignment | owner | location_list
    unique_overlap: tuple[tuple[str, ...], ...] = ()  # no two active records with these values may overlap in time
    unique_fields: tuple[tuple[str, ...], ...] = ()  # no two active records with these values, whatever the dates
    creatable: bool = True
    dedupe_hash: str | None = None  # secret field kept as a keyed hash too, for duplicate checks
    hook: str | None = None  # extra validation in app/core/hooks.py
    help: str = ""

    @property
    def path(self) -> str:
        return f"/api/{self.group}/{self.key}"

    def f(self, name: str) -> F:
        return next(x for x in self.fields if x.name == name)

    @property
    def input_fields(self) -> list[F]:
        return [x for x in self.fields if not x.readonly]

    @property
    def secret_fields(self) -> list[F]:
        return [x for x in self.fields if x.kind in ("secret", "secret_json")]

    @property
    def ref_fields(self) -> list[F]:
        return [x for x in self.fields if x.kind in ("ref", "refs")]


def _code(required: bool = True) -> F:
    return F("code", "str", required, max_len=30, pattern="code")


SPECS_LIST: list[Spec] = [
    # ---------------------------------------------------------------- Stage 1: the spine
    Spec("states", "states", "State", "State / region", 5, "setup", 1, [
        F("country", "str", True, max_len=2, default="IN"),
        F("code", "str", True, max_len=10, pattern="code"),
        F("name", "str", True),
    ], help="Reference list; drives state rules (PT, LWF). India's states are loaded when a client is created."),
    Spec("legal-entities", "legal_entities", "LegalEntity", "Legal entity", 2, "setup", 1, [
        _code(),
        F("registered_name", "str", True),
        F("short_name", "str", max_len=100),
        F("pan", "secret", pattern="pan", label="PAN"),
        F("tan", "str", max_len=10, pattern="tan", label="TAN"),
        F("gstin", "str", max_len=15, pattern="gstin", label="GSTIN"),
        F("cin", "str", max_len=21, pattern="cin", label="CIN"),
        F("state_rid", "ref", ref="states", label="Registered state"),
        F("registered_address", "text"),
        F("correspondence_address", "text"),
        F("signatories", "json", label="Signatories (name, designation, valid_from, valid_to)"),
    ], name_field="registered_name", scope={"rid": "entity"}, hook="legal_entity"),
    Spec("locations", "locations", "Location", "Location", 6, "setup", 1, [
        _code(),
        F("name", "str", True),
        F("state_rid", "ref", True, ref="states", label="State"),
        F("address", "text"),
        F("city", "str", max_len=100),
        F("pincode", "str", max_len=6, pattern="pincode"),
        F("time_zone", "str", max_len=40, default="Asia/Kolkata"),
    ], scope={"rid": "location"}),
    Spec("entity-locations", "entity_locations", "EntityLocation", "Entity at location", 7, "setup", 1, [
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
        F("location_rid", "ref", True, ref="locations"),
    ], code_field=None, name_field=None, scope={"legal_entity_rid": "entity", "location_rid": "location"},
        unique_overlap=(("legal_entity_rid", "location_rid"),),
        help="Dated many-to-many link: a location can host several entities, and that changes over time."),
    Spec("departments", "departments", "Department", "Department", 8, "setup", 1, [
        _code(),
        F("name", "str", True),
        F("parent_rid", "ref", ref="departments", label="Parent department"),
        F("head_person_rid", "ref", ref="persons", label="Head (person)"),
    ], scope={"rid": "department"}, hook="department", help="A tree: each department can have a parent."),
    # ---------------------------------------------------------------- Stage 2: people and structure
    Spec("department-entities", "department_entities", "DepartmentEntity", "Department in entity", 9, "setup", 2, [
        F("department_rid", "ref", True, ref="departments"),
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
    ], code_field=None, name_field=None, scope={"department_rid": "department", "legal_entity_rid": "entity"},
        unique_overlap=(("department_rid", "legal_entity_rid"),)),
    Spec("designations", "designations", "Designation", "Designation", 10, "setup", 2, [
        _code(),
        F("title", "str", True),
        F("job_family", "str", max_len=100),
    ], name_field="title"),
    Spec("cost-centres", "cost_centres", "CostCentre", "Cost centre", 11, "setup", 2, [
        _code(),
        F("name", "str", True),
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
    ], scope={"legal_entity_rid": "entity"}),
    Spec("persons", "persons", "Person", "Person", 12, "setup", 2, [
        F("first_name", "str", True, max_len=100),
        F("middle_name", "str", max_len=100),
        F("last_name", "str", max_len=100),
        F("preferred_name", "str", max_len=100),
        F("date_of_birth", "date"),
        F("gender", "enum", choices=("female", "male", "other")),
        F("email", "email"),
        F("phone", "str", max_len=20, pattern="phone"),
        F("address", "text"),
        F("language", "str", max_len=10),
        F("pan", "secret", pattern="pan", label="PAN"),
        F("aadhaar", "secret", pattern="aadhaar", label="Aadhaar"),
        F("identity_documents", "secret_json", label="Identity documents (type, number, valid_to)"),
        F("emergency_contact", "str", max_len=200),
    ], code_field=None, name_field="first_name", scope_special="person", dedupe_hash="pan", hook="person",
        help="One record per human, not the employment. Employments are employment assignments."),
    Spec("statutory-registrations", "statutory_registrations", "StatutoryRegistration", "Statutory registration", 3, "setup", 2, [
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
        F("type", "enum", True, choices=STATUTORY_TYPES),
        F("other_name", "str", max_len=100, label="Name (when type is OTHER)"),
        F("number", "str", max_len=60),
        F("state_rid", "ref", ref="states"),
        F("status", "enum", choices=("active", "exempt", "applied", "cancelled"), default="active"),
    ], code_field=None, name_field="type", scope={"legal_entity_rid": "entity"},
        unique_overlap=(("legal_entity_rid", "type", "state_rid"),), hook="statutory",
        help="Configurable list per entity and state. None is mandatory; exemptions are allowed."),
    Spec("holiday-calendars", "holiday_calendars", "HolidayCalendar", "Holiday calendar", 14, "setup", 2, [
        _code(),
        F("name", "str", True),
        F("year", "year", True),
        F("holidays", "json", True, label="Holidays (date, name, kind: fixed | optional)"),
        F("location_rids", "refs", ref="locations", label="Locations"),
    ], scope_special="location_list", hook="holiday_calendar", help="Assigned to locations; a location can have its own calendar."),
    Spec("biometric-devices", "biometric_devices", "BiometricDevice", "Biometric device", 28, "setup", 2, [
        F("code", "str", True, max_len=60, pattern="code", label="Device ID"),
        F("make", "str", max_len=100),
        F("model", "str", max_len=100),
        F("location_rid", "ref", True, ref="locations"),
        F("connection", "enum", True, choices=("api", "file")),
        F("endpoint", "str", max_len=300),
        F("last_sync_at", "datetime", readonly=True),
    ], name_field="model", scope={"location_rid": "location"}, help="Punches map to a location through the device; not tied to one vendor."),
    Spec("payroll-calendars", "payroll_calendars", "PayrollCalendar", "Payroll calendar", 30, "setup", 2, [
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
        F("period", "period", True, max_len=7, label="Period (YYYY-MM)"),
        F("attendance_cutoff", "date", True),
        F("pay_date", "date", True),
        F("locked", "bool", default=False),
    ], code_field=None, name_field="period", scope={"legal_entity_rid": "entity"}, unique_fields=(("legal_entity_rid", "period"),),
        hook="payroll_calendar", help="One per legal entity per pay period; locked when payroll is locked."),
    # ---------------------------------------------------------------- Stage 3: employment and access
    Spec("grades", "grades", "Grade", "Grade / band", 19, "hr", 3, [
        _code(),
        F("name", "str", True),
        F("level", "int"),
        F("pay_min", "decimal"),
        F("pay_max", "decimal"),
    ], hook="grade"),
    Spec("employment-types", "employment_types", "EmploymentType", "Employment type", 31, "hr", 3, [
        _code(),
        F("name", "str", True),
        F("statutory_types", "json", label="Statutory items that apply (PF, ESI, PT, LWF, TDS)"),
        F("leave_type_rids", "refs", ref="leave-types", label="Leave types that apply"),
    ], hook="employment_type"),
    Spec("shifts", "shifts", "Shift", "Shift", 20, "hr", 3, [
        _code(),
        F("name", "str", True),
        F("location_rid", "ref", ref="locations", label="Location (empty = all)"),
        F("start_time", "time", True, max_len=5),
        F("end_time", "time", True, max_len=5),
        F("crosses_midnight", "bool", readonly=True),
        F("break_minutes", "int", default=0),
        F("grace_minutes", "int", default=0),
        F("half_day_minutes", "int"),
    ], scope={"location_rid": "location"}, hook="shift"),
    Spec("weekly-offs", "weekly_off_patterns", "WeeklyOffPattern", "Weekly-off pattern", 21, "hr", 3, [
        _code(),
        F("name", "str", True),
        F("days_off", "json", True, label="Days off (monday ... sunday)"),
        F("rotation", "json"),
        F("location_rid", "ref", ref="locations"),
        F("shift_rid", "ref", ref="shifts"),
    ], scope={"location_rid": "location"}, hook="weekly_off"),
    Spec("bank-accounts", "bank_accounts", "BankAccount", "Bank account", 4, "setup", 3, [
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
        F("bank_name", "str", True, max_len=100),
        F("branch", "str", max_len=100),
        F("ifsc", "str", True, max_len=11, pattern="ifsc", label="IFSC"),
        F("account_number", "secret", True, pattern="account"),
        F("purpose", "enum", choices=("salary", "vendor", "statutory", "other"), default="salary"),
    ], code_field=None, name_field="bank_name", scope={"legal_entity_rid": "entity"}, help="Masked by role; never in logs."),
    Spec("policies", "policies", "Policy", "Policy", 15, "setup", 3, [
        _code(),
        F("name", "str", True),
        F("applies_to", "json", label="Applies to (legal_entity_rids, location_rids, department_rids, grade_rids)"),
        F("settings", "json"),
    ], hook="policy", help="Versioned: earlier months keep the version that applied."),
    Spec("number-series", "number_series", "NumberSeries", "Number series", 17, "setup", 3, [
        _code(),
        F("object", "enum", True, choices=("employee", "document")),
        F("legal_entity_rid", "ref", ref="legal-entities", label="Legal entity (empty = whole client)"),
        F("prefix", "str", max_len=20, default=""),
        F("padding", "int", default=4),
        F("start_number", "int", default=1),
    ], name_field="prefix", scope={"legal_entity_rid": "entity"}, unique_overlap=(("object", "legal_entity_rid"),), hook="number_series",
        help="Numbers are allocated atomically and never reused."),
    Spec("leave-types", "leave_types", "LeaveType", "Leave type", 22, "hr", 3, [
        _code(),
        F("name", "str", True),
        F("paid", "bool", default=True),
        F("accrual_days_per_year", "decimal"),
        F("accrual_frequency", "enum", choices=("monthly", "quarterly", "yearly", "none"), default="yearly"),
        F("carry_forward_max", "decimal"),
        F("encashable", "bool", default=False),
        F("eligibility", "json", label="Eligibility (employment_type_rids, grade_rids, min_service_months, gender)"),
        F("policy_rid", "ref", ref="policies"),
    ]),
    Spec("approval-workflows", "approval_workflows", "ApprovalWorkflow", "Approval workflow", 26, "setup", 3, [
        _code(),
        F("name", "str", True),
        F("request_type", "enum", True, choices=REQUEST_TYPES),
        F("steps", "json", True, label="Steps [{approver_type: role | reporting_level, value}]"),
        F("limits", "json"),
    ], unique_overlap=(("request_type",),), hook="approval_workflow", help="No one approves their own request."),
    Spec("role-permissions", "role_permissions", "RolePermission", "Role permission", 27, "setup", 3, [
        F("role", "str", True, max_len=40, pattern="code"),
        F("resource", "str", True, max_len=60, label="Resource (entity key, users, audit, changes, employee, client or *)"),
        F("actions", "json", True, label="Actions (view, create, change, deactivate, approve, import, export)"),
        F("scope", "enum", choices=SCOPE_MODES, default="scoped"),
        F("masked_fields", "json", label="Fields shown masked to this role"),
    ], code_field=None, name_field="role", unique_overlap=(("role", "resource"),), hook="role_permission",
        help="Checked on the server on every call."),
    Spec("employment-assignments", "employment_assignments", "EmploymentAssignment", "Employment assignment", 18, "hr", 3, [
        F("person_rid", "ref", True, ref="persons"),
        F("legal_entity_rid", "ref", True, ref="legal-entities"),
        F("location_rid", "ref", True, ref="locations"),
        F("department_rid", "ref", True, ref="departments"),
        F("designation_rid", "ref", True, ref="designations"),
        F("grade_rid", "ref", ref="grades"),
        F("employment_type_rid", "ref", ref="employment-types"),
        F("cost_centre_rid", "ref", ref="cost-centres"),
        F("shift_rid", "ref", ref="shifts"),
        F("weekly_off_rid", "ref", ref="weekly-offs"),
        F("pay_share", "decimal", default=100, label="Pay share %"),
        F("is_primary", "bool", default=True),
        F("employee_number", "str", max_len=40, readonly=True),
    ], code_field=None, name_field="employee_number", scope={"legal_entity_rid": "entity", "location_rid": "location", "department_rid": "department"},
        hook="assignment", help="One per job. Places, legal structure and organisation meet here."),
    Spec("reporting-lines", "reporting_lines", "ReportingLine", "Reporting line", 13, "setup", 3, [
        F("assignment_rid", "ref", True, ref="employment-assignments"),
        F("reports_to_person_rid", "ref", True, ref="persons"),
        F("type", "enum", choices=("line", "functional"), default="line"),
    ], code_field=None, name_field="type", scope_special="assignment", unique_overlap=(("assignment_rid", "type"),), hook="reporting_line",
        help="Dated; each job can have its own line and functional manager."),
    Spec("documents", "documents", "Document", "Document", 29, "setup", 3, [
        F("doc_type", "str", True, max_len=60),
        F("owner_type", "enum", True, choices=("legal-entities", "persons", "policies", "locations", "employment-assignments")),
        F("owner_rid", "int", True),
        F("file_name", "str", max_len=255, readonly=True),
        F("content_type", "str", max_len=100, readonly=True),
        F("size_bytes", "int", readonly=True),
        F("storage_key", "str", max_len=300, readonly=True),
    ], code_field=None, name_field="doc_type", scope_special="owner", creatable=False,
        help="Uploaded through /api/setup/documents/upload. Stored once; access follows the owner record's scope."),
]

SPECS: dict[str, Spec] = {s.key: s for s in SPECS_LIST}

# Resources that are not entity specs but are permission-checked
EXTRA_RESOURCES = ("users", "audit", "changes", "employee", "client")


def check_catalogue() -> list[str]:
    """Consistency checks for the catalogue itself (run by the tests)."""
    errs = []
    for s in SPECS_LIST:
        names = [x.name for x in s.fields]
        if len(names) != len(set(names)):
            errs.append(f"{s.key}: duplicate field names")
        for x in s.fields:
            if x.kind not in KINDS:
                errs.append(f"{s.key}.{x.name}: unknown kind {x.kind}")
            if x.kind in ("ref", "refs") and x.ref not in SPECS:
                errs.append(f"{s.key}.{x.name}: ref to unknown spec {x.ref}")
            if x.kind == "enum" and not x.choices:
                errs.append(f"{s.key}.{x.name}: enum without choices")
            if x.pattern and x.pattern not in PATTERNS:
                errs.append(f"{s.key}.{x.name}: unknown pattern {x.pattern}")
        for group in s.unique_overlap + s.unique_fields:
            for n in group:
                if n not in names:
                    errs.append(f"{s.key}: unique key uses unknown field {n}")
        for n in s.scope:
            if n != "rid" and n not in names:
                errs.append(f"{s.key}: scope uses unknown field {n}")
        if s.code_field and s.code_field not in names:
            errs.append(f"{s.key}: code field {s.code_field} missing")
        if s.name_field and s.name_field not in names:
            errs.append(f"{s.key}: name field {s.name_field} missing")
        if s.dedupe_hash and s.dedupe_hash not in [x.name for x in s.secret_fields]:
            errs.append(f"{s.key}: dedupe_hash must name a secret field")
    return errs
