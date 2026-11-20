"""Starting data loaded into every new client. It is data, not code: after loading, roles and permissions
are changed through the role-permissions entity (27); a client's YAML can override them before first start.
"""
from __future__ import annotations

from typing import Any

from .specs import ACTIONS, SPECS

DEFAULT_ROLES = {
    "master_admin": "Master admin",
    "hr": "HR",
    "payroll_preparer": "Payroll preparer",
    "finance_approver": "Finance approver",
    "hod": "Head of department",
    "employee": "Employee",
}

ALL = list(ACTIONS)
MANAGE = ["view", "create", "change", "deactivate", "import", "approve"]
SENSITIVE_PERSON = ["pan", "aadhaar", "identity_documents"]
PEOPLE = ("persons", "employment-assignments", "reporting-lines")


def default_permissions() -> list[dict[str, Any]]:
    """One row per role and resource: actions, scope mode and masked fields."""
    rows: list[dict[str, Any]] = [
        {"role": "master_admin", "resource": "*", "actions": ALL, "scope": "all", "masked_fields": []},
        {"role": "hr", "resource": "users", "actions": ["view", "create", "change"], "scope": "scoped", "masked_fields": []},
        {"role": "hr", "resource": "audit", "actions": ["view"], "scope": "scoped", "masked_fields": []},
        {"role": "hr", "resource": "changes", "actions": ["view", "approve"], "scope": "scoped", "masked_fields": []},
        {"role": "hr", "resource": "client", "actions": ["view"], "scope": "all", "masked_fields": []},
    ]
    for key in SPECS:
        hr_actions = ["view"] if key == "role-permissions" else MANAGE
        rows.append({"role": "hr", "resource": key, "actions": hr_actions, "scope": "scoped", "masked_fields": []})
        rows.append({"role": "payroll_preparer", "resource": key, "scope": "scoped", "masked_fields": [],
                     "actions": ["view", "change"] if key == "payroll-calendars" else ["view"]})
        rows.append({"role": "finance_approver", "resource": key, "scope": "scoped", "masked_fields": [],
                     "actions": ["view", "approve"] if key == "payroll-calendars" else ["view"]})
    for role in ("payroll_preparer", "finance_approver", "hod", "employee"):
        rows.append({"role": role, "resource": "client", "actions": ["view"], "scope": "all", "masked_fields": []})
    for key in PEOPLE:
        rows.append({"role": "hod", "resource": key, "actions": ["view"], "scope": "team", "masked_fields": SENSITIVE_PERSON})
        rows.append({"role": "employee", "resource": key, "actions": ["view"], "scope": "self", "masked_fields": []})
    for key in ("legal-entities", "locations", "departments", "designations", "grades", "shifts", "weekly-offs", "leave-types",
                "holiday-calendars", "employment-types"):
        for role in ("hod", "employee"):
            rows.append({"role": role, "resource": key, "actions": ["view"], "scope": "all", "masked_fields": ["pan"]})
    return rows


DEFAULT_WORKFLOWS = [
    # Backdated changes to Company Setup: approved by a master admin or HR user other than the requester.
    {"code": "BACKDATED", "name": "Backdated changes", "request_type": "backdated_change",
     "steps": [{"approver_type": "role", "value": ["master_admin", "hr"]}], "limits": {}},
]

# States and union territories of India (ISO 3166-2:IN codes). Loaded for clients whose country is IN.
INDIA_STATES = [
    ("AN", "Andaman and Nicobar Islands"), ("AP", "Andhra Pradesh"), ("AR", "Arunachal Pradesh"), ("AS", "Assam"), ("BR", "Bihar"),
    ("CH", "Chandigarh"), ("CT", "Chhattisgarh"), ("DH", "Dadra and Nagar Haveli and Daman and Diu"), ("DL", "Delhi"), ("GA", "Goa"),
    ("GJ", "Gujarat"), ("HR", "Haryana"), ("HP", "Himachal Pradesh"), ("JK", "Jammu and Kashmir"), ("JH", "Jharkhand"),
    ("KA", "Karnataka"), ("KL", "Kerala"), ("LA", "Ladakh"), ("LD", "Lakshadweep"), ("MP", "Madhya Pradesh"), ("MH", "Maharashtra"),
    ("MN", "Manipur"), ("ML", "Meghalaya"), ("MZ", "Mizoram"), ("NL", "Nagaland"), ("OR", "Odisha"), ("PY", "Puducherry"),
    ("PB", "Punjab"), ("RJ", "Rajasthan"), ("SK", "Sikkim"), ("TN", "Tamil Nadu"), ("TG", "Telangana"), ("TR", "Tripura"),
    ("UP", "Uttar Pradesh"), ("UT", "Uttarakhand"), ("WB", "West Bengal"),
]
