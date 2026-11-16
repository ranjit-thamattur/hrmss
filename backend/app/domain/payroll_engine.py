"""Payroll rules engine.

Pure Python, no database and no AI: the same inputs and the same rule version always give the
same result. Every rule value comes from a versioned rule set (see DEFAULT_RULES and the
statutory_rules table), never from code constants scattered around.

All amounts are Decimal and rounded to the rupee (half up) per line. ESI is rounded up, as ESIC does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

D = Decimal
ZERO = D("0")


def rupee(x: Any) -> Decimal:
    return D(str(x)).quantize(D("1"), rounding=ROUND_HALF_UP)


def ceil_rupee(x: Any) -> Decimal:
    return D(math.ceil(D(str(x))))


# SAMPLE rule set. Values must be confirmed by Hotel Vivek's payroll consultant (SCRUM-119) and are
# stored as dated versions in the database; this dict is only the starting version.
DEFAULT_RULES: dict[str, Any] = {
    "version": "2026-11-sample",
    "hours_per_day": 8,
    "ot": {"multiplier": 2, "base_components": ["BASIC", "HRA", "CONV", "SPECIAL"]},
    "night_allowance_per_shift": 100,
    "variable_earnings": ["SERVICE_CHARGE", "INCENTIVE", "ARREAR", "BONUS", "OTHER_EARNING"],
    "variable_deductions": ["ADVANCE", "LOAN_EMI", "OTHER_DEDUCTION"],
    "pf": {
        "wage_components": ["BASIC", "DA"],
        "employee_rate": "0.12",
        "eps_rate": "0.0833",
        "edli_rate": "0.005",
        "admin_rate": "0.005",
        "wage_ceiling": 15000,
        "cap_employee_at_ceiling": True,
    },
    "esi": {"employee_rate": "0.0075", "employer_rate": "0.0325", "eligibility_ceiling": 21000, "exclude": []},
    # Tamil Nadu professional tax, half-yearly, deducted in September and March (sample slabs).
    "pt": {
        "months": [9, 3],
        "half_year_slabs": [[21000, 0], [30000, 180], [45000, 425], [60000, 930], [75000, 1025], [None, 1250]],
    },
    # Tamil Nadu labour welfare fund, yearly, deducted in December (sample).
    "lwf": {"month": 12, "employee": 20, "employer": 40},
    # Income tax, new regime (sample FY 2025-26 slabs). Monthly TDS = projected annual tax / 12.
    "tds": {
        "standard_deduction": 75000,
        "slabs": [[400000, 0], [800000, "0.05"], [1200000, "0.10"], [1600000, "0.15"], [2000000, "0.20"], [2400000, "0.25"], [None, "0.30"]],
        "rebate_limit": 1200000,
        "cess": "0.04",
    },
    # How statutory deductions are worked out for staff paid by more than one entity (open decision:
    # Gerald's Case 2 vs Case 4). "combined": on total pay, then shared by each entity's share of gross.
    # "per_entity": each entity computes on its own share.
    "statutory_basis": "combined",
    "checks": {"net_change_pct": 20, "ot_hours_high": 50, "lop_days_high": 5, "min_wage_monthly": 0},
}


@dataclass
class Allocation:
    entity: str
    method: str = "percent"  # percent | fixed
    value: Decimal = D("100")
    primary: bool = False


@dataclass
class PayInput:
    employee_code: str
    name: str
    components: dict[str, Decimal]  # monthly fixed salary components, e.g. BASIC, HRA, CONV, SPECIAL
    days_in_month: int
    paid_days: Decimal
    month: int
    year: int
    ot_hours: Decimal = ZERO
    night_shifts: int = 0
    variable: dict[str, Decimal] = field(default_factory=dict)
    pf_applicable: bool = True
    esi_applicable: bool = True
    pt_applicable: bool = True
    lwf_applicable: bool = True
    tds_override: Decimal | None = None
    has_bank: bool = True
    previous_net: Decimal | None = None
    default_entity: str = ""
    allocations: list[Allocation] = field(default_factory=list)


@dataclass
class Flag:
    code: str
    severity: str  # block | warn
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class PayResult:
    employee_code: str
    earnings: dict[str, Decimal]
    deductions: dict[str, Decimal]
    employer: dict[str, Decimal]
    gross: Decimal
    total_deductions: Decimal
    net: Decimal
    paid_days: Decimal
    lop_days: Decimal
    flags: list[Flag]
    by_entity: dict[str, dict[str, Any]]
    rule_version: str

    def as_dict(self) -> dict[str, Any]:
        s = lambda d: {k: str(v) for k, v in d.items()}  # noqa: E731
        return {
            "employee_code": self.employee_code,
            "earnings": s(self.earnings),
            "deductions": s(self.deductions),
            "employer": s(self.employer),
            "gross": str(self.gross),
            "total_deductions": str(self.total_deductions),
            "net": str(self.net),
            "paid_days": str(self.paid_days),
            "lop_days": str(self.lop_days),
            "flags": [f.as_dict() for f in self.flags],
            "by_entity": {e: {k: (s(v) if isinstance(v, dict) else str(v)) for k, v in d.items()} for e, d in self.by_entity.items()},
            "rule_version": self.rule_version,
        }


# ---------------------------------------------------------------- individual rules
def slab_tax(amount: Decimal, slabs: list[list[Any]]) -> Decimal:
    """Progressive tax: slabs are [upper_limit, rate]; upper None = no limit."""
    tax, lower = ZERO, ZERO
    for upper, rate in slabs:
        top = D(str(upper)) if upper is not None else amount
        if amount > lower:
            tax += (min(amount, top) - lower) * D(str(rate))
        if upper is None or amount <= top:
            break
        lower = top
    return tax


def annual_income_tax(annual_gross: Decimal, rules: dict[str, Any]) -> Decimal:
    t = rules["tds"]
    taxable = max(ZERO, annual_gross - D(str(t["standard_deduction"])))
    if taxable <= D(str(t["rebate_limit"])):
        return ZERO
    tax = slab_tax(taxable, t["slabs"])
    return rupee(tax * (1 + D(str(t["cess"]))))


def pt_for(half_year_gross: Decimal, rules: dict[str, Any]) -> Decimal:
    for upper, amount in rules["pt"]["half_year_slabs"]:
        if upper is None or half_year_gross <= D(str(upper)):
            return D(str(amount))
    return ZERO


def split_amount(total: Decimal, ratios: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split a rupee amount by ratios; the last entity absorbs the rounding so parts add up exactly."""
    keys = list(ratios)
    out: dict[str, Decimal] = {}
    running = ZERO
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            out[k] = total - running
        else:
            out[k] = rupee(total * ratios[k])
            running += out[k]
    return out


def entity_ratios(gross: Decimal, inp: PayInput) -> dict[str, Decimal]:
    """Share of gross for each paying entity. Fixed amounts first, the rest by percent."""
    allocs = inp.allocations or [Allocation(inp.default_entity or "DEFAULT", "percent", D("100"), True)]
    if len(allocs) == 1 or gross <= 0:
        return {allocs[0].entity: D("1")}
    amounts: dict[str, Decimal] = {a.entity: ZERO for a in allocs}
    remaining = gross
    for a in allocs:
        if a.method == "fixed":
            take = min(D(str(a.value)), remaining)
            amounts[a.entity] += take
            remaining -= take
    pct = [a for a in allocs if a.method == "percent"]
    pct_total = sum((D(str(a.value)) for a in pct), ZERO)
    if pct and pct_total > 0:
        for a in pct:
            amounts[a.entity] += remaining * D(str(a.value)) / pct_total
        remaining = ZERO
    if remaining > 0:  # nothing on percent: remainder to the primary entity
        primary = next((a for a in allocs if a.primary), allocs[0])
        amounts[primary.entity] += remaining
    return {k: (v / gross) for k, v in amounts.items()}


# ---------------------------------------------------------------- main calculation
def _compute(inp: PayInput, rules: dict[str, Any], *, skip_alloc_checks: bool = False) -> PayResult:
    days = D(inp.days_in_month)
    paid = min(D(str(inp.paid_days)), days)
    lop = days - paid
    factor = paid / days if days else ZERO

    earnings: dict[str, Decimal] = {}
    for code, amount in inp.components.items():
        earnings[code] = rupee(D(str(amount)) * factor)

    fixed_monthly = sum((D(str(v)) for v in inp.components.values()), ZERO)
    ot_base = sum((D(str(inp.components.get(c, 0))) for c in rules["ot"]["base_components"]), ZERO)
    if inp.ot_hours:
        rate = ot_base / days / D(rules["hours_per_day"]) * D(str(rules["ot"]["multiplier"]))
        earnings["OT"] = rupee(rate * D(str(inp.ot_hours)))
    if inp.night_shifts:
        earnings["NIGHT_ALLOWANCE"] = rupee(D(inp.night_shifts) * D(str(rules["night_allowance_per_shift"])))
    for code in rules["variable_earnings"]:
        if inp.variable.get(code):
            earnings[code] = rupee(inp.variable[code])
    gross = sum(earnings.values(), ZERO)

    deductions: dict[str, Decimal] = {}
    employer: dict[str, Decimal] = {}

    # Provident fund
    if inp.pf_applicable:
        pf = rules["pf"]
        pf_wage = sum((earnings.get(c, ZERO) for c in pf["wage_components"]), ZERO)
        ceiling = D(pf["wage_ceiling"])
        ee_wage = min(pf_wage, ceiling) if pf["cap_employee_at_ceiling"] else pf_wage
        capped = min(pf_wage, ceiling)
        ee = rupee(ee_wage * D(pf["employee_rate"]))
        eps = rupee(capped * D(pf["eps_rate"]))
        deductions["PF"] = ee
        employer["EPS"] = eps
        employer["EPF_ER"] = ee - eps if ee >= eps else ZERO
        employer["EDLI"] = rupee(capped * D(pf["edli_rate"]))
        employer["PF_ADMIN"] = rupee(capped * D(pf["admin_rate"]))

    # Employees' State Insurance: eligibility by fixed monthly wages
    esi = rules["esi"]
    if inp.esi_applicable and fixed_monthly <= D(esi["eligibility_ceiling"]):
        esi_wage = gross - sum((earnings.get(c, ZERO) for c in esi["exclude"]), ZERO)
        if esi_wage > 0:
            deductions["ESI"] = ceil_rupee(esi_wage * D(esi["employee_rate"]))
            employer["ESI_ER"] = ceil_rupee(esi_wage * D(esi["employer_rate"]))

    # Professional tax (half-yearly)
    if inp.pt_applicable and inp.month in rules["pt"]["months"]:
        amount = pt_for(gross * 6, rules)
        if amount:
            deductions["PT"] = amount

    # Labour welfare fund (yearly)
    lwf = rules["lwf"]
    if inp.lwf_applicable and inp.month == lwf["month"]:
        deductions["LWF"] = D(lwf["employee"])
        employer["LWF_ER"] = D(lwf["employer"])

    # Income tax
    if inp.tds_override is not None:
        tds = rupee(inp.tds_override)
    else:
        tds = rupee(annual_income_tax(fixed_monthly * 12, rules) / 12)
    if tds:
        deductions["TDS"] = tds

    for code in rules["variable_deductions"]:
        if inp.variable.get(code):
            deductions[code] = rupee(inp.variable[code])

    total_ded = sum(deductions.values(), ZERO)
    net = gross - total_ded

    flags: list[Flag] = []
    chk = rules["checks"]
    if net < 0:
        flags.append(Flag("NEGATIVE_NET", "block", f"Net pay is {net}. Negative pay cannot be approved as it is."))
    if not inp.has_bank and net > 0:
        flags.append(Flag("NO_BANK", "block", "No bank account on record; the line cannot go in the bank file."))
    if paid == 0:
        flags.append(Flag("ZERO_PAY_DAYS", "warn", "No paid days this month."))
    if lop >= D(chk["lop_days_high"]):
        flags.append(Flag("LOP_HIGH", "warn", f"{lop} loss-of-pay days."))
    if D(str(inp.ot_hours)) >= D(chk["ot_hours_high"]):
        flags.append(Flag("OT_HIGH", "warn", f"{inp.ot_hours} OT hours this month."))
    if inp.previous_net and inp.previous_net > 0:
        change = (net - inp.previous_net) / inp.previous_net * 100
        if abs(change) > D(chk["net_change_pct"]):
            flags.append(Flag("NET_CHANGE", "warn", f"Net pay {'up' if change > 0 else 'down'} {abs(change):.0f}% vs last month."))
    if chk["min_wage_monthly"] and fixed_monthly < D(chk["min_wage_monthly"]):
        flags.append(Flag("BELOW_MIN_WAGE", "block", "Fixed monthly wages are below the minimum wage set in the rules."))
    if not inp.components:
        flags.append(Flag("NO_STRUCTURE", "block", "No salary structure in force for this month."))

    return PayResult(inp.employee_code, earnings, deductions, employer, gross, total_ded, net, paid, lop, flags, {}, rules["version"])


def calculate(inp: PayInput, rules: dict[str, Any] | None = None) -> PayResult:
    rules = rules or DEFAULT_RULES
    result = _compute(inp, rules)
    ratios = entity_ratios(result.gross, inp)

    if len(ratios) == 1:
        (ent,) = ratios
        result.by_entity = {ent: {"earnings": result.earnings, "deductions": result.deductions, "employer": result.employer,
                                  "gross": result.gross, "net": result.net}}
        return result

    if rules.get("statutory_basis") == "per_entity":
        parts: dict[str, PayResult] = {}
        for ent, r in ratios.items():
            sub = PayInput(**{**inp.__dict__, "components": {k: D(str(v)) * r for k, v in inp.components.items()},
                              "variable": {k: D(str(v)) * r for k, v in inp.variable.items()},
                              "ot_hours": D(str(inp.ot_hours)) * r, "allocations": [], "default_entity": ent,
                              "tds_override": (D(str(inp.tds_override)) * r if inp.tds_override is not None else None)})
            parts[ent] = _compute(sub, rules)
        total = lambda key: {k: sum((getattr(p, key).get(k, ZERO) for p in parts.values()), ZERO)  # noqa: E731
                             for k in {kk for p in parts.values() for kk in getattr(p, key)}}
        result.earnings, result.deductions, result.employer = total("earnings"), total("deductions"), total("employer")
        result.gross = sum(result.earnings.values(), ZERO)
        result.total_deductions = sum(result.deductions.values(), ZERO)
        result.net = result.gross - result.total_deductions
        result.by_entity = {e: {"earnings": p.earnings, "deductions": p.deductions, "employer": p.employer, "gross": p.gross, "net": p.net}
                            for e, p in parts.items()}
        return result

    # combined: shares of every line follow the entity's share of gross
    by: dict[str, dict[str, Any]] = {e: {"earnings": {}, "deductions": {}, "employer": {}} for e in ratios}
    for key in ("earnings", "deductions", "employer"):
        for code, amount in getattr(result, key).items():
            for e, part in split_amount(amount, ratios).items():
                by[e][key][code] = part
    for e in by:
        by[e]["gross"] = sum(by[e]["earnings"].values(), ZERO)
        by[e]["net"] = by[e]["gross"] - sum(by[e]["deductions"].values(), ZERO)
    result.by_entity = by
    return result


def apply_decision(result: PayResult, decision: str) -> None:
    """Guard used by the API: a blocking flag can be resolved only by fixing inputs or holding the line."""
    blocking = [f for f in result.flags if f.severity == "block"]
    if decision == "accept" and any(f.code == "NEGATIVE_NET" for f in blocking):
        raise ValueError("Negative pay cannot be approved as it is: change the inputs or hold the line.")
