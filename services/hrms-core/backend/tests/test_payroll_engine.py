"""Payroll engine tests. Payroll code cannot merge without these passing (decision 0002).
Scenario numbers follow SCRUM-124 (three-entity model scenarios)."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from app.domain.payroll_engine import DEFAULT_RULES, Allocation, PayInput, annual_income_tax, calculate, entity_ratios, slab_tax, split_amount

STRUCT = {"BASIC": D(10000), "HRA": D(4000), "CONV": D(1600), "SPECIAL": D(2400)}  # 18,000 gross


def make(**kw):
    base = dict(employee_code="HV0001", name="Test", components=dict(STRUCT), days_in_month=30, paid_days=D(30), month=11, year=2026,
                default_entity="VHPL")
    base.update(kw)
    return PayInput(**base)


# ---------------- scenario 1: one employee, one entity, full month
def test_s1_single_entity_full_month():
    r = calculate(make())
    assert r.gross == D(18000)
    assert r.deductions["PF"] == D(1200)  # 12% of 10,000 basic
    assert r.deductions["ESI"] == D(135)  # 0.75% of 18,000
    assert r.employer["EPS"] == D(833)
    assert r.employer["EPF_ER"] == D(367)
    assert r.employer["ESI_ER"] == D(585)
    assert "PT" not in r.deductions and "LWF" not in r.deductions and "TDS" not in r.deductions
    assert r.net == D(18000 - 1200 - 135)
    assert r.flags == []
    assert list(r.by_entity) == ["VHPL"]


# ---------------- scenario 2: loss of pay pro-rates every fixed component
def test_s2_lop_prorates():
    r = calculate(make(paid_days=D(27)))
    assert r.lop_days == D(3)
    assert r.earnings["BASIC"] == D(9000)
    assert r.earnings["HRA"] == D(3600)
    assert r.gross == D(16200)


# ---------------- scenario 3: split 60/40 across two entities by percent
def test_s3_split_two_entities_percent():
    r = calculate(make(allocations=[Allocation("VHPL", "percent", D(60), True), Allocation("VRL", "percent", D(40))]))
    assert r.by_entity["VHPL"]["gross"] == D(10800)
    assert r.by_entity["VRL"]["gross"] == D(7200)
    for key in ("earnings", "deductions", "employer"):
        for code, amount in getattr(r, key).items():
            assert sum(r.by_entity[e][key].get(code, D(0)) for e in r.by_entity) == amount, (key, code)
    assert r.by_entity["VHPL"]["net"] + r.by_entity["VRL"]["net"] == r.net


# ---------------- scenario 4: three entities
def test_s4_split_three_entities():
    r = calculate(make(allocations=[Allocation("VHPL", "percent", D(50), True), Allocation("VRL", "percent", D(30)), Allocation("VFS", "percent", D(20))]))
    assert [r.by_entity[e]["gross"] for e in ("VHPL", "VRL", "VFS")] == [D(9000), D(5400), D(3600)]
    assert sum(r.by_entity[e]["net"] for e in r.by_entity) == r.net


# ---------------- scenario 5: fixed amount in one entity, rest in primary
def test_s5_fixed_plus_remainder():
    ratios = entity_ratios(D(18000), make(allocations=[Allocation("VFS", "fixed", D(5000)), Allocation("VHPL", "percent", D(100), True)]))
    assert ratios["VFS"] * 18000 == D(5000)
    r = calculate(make(allocations=[Allocation("VFS", "fixed", D(5000)), Allocation("VHPL", "percent", D(100), True)]))
    assert r.by_entity["VFS"]["gross"] == D(5000)
    assert r.by_entity["VHPL"]["gross"] == D(13000)


# ---------------- scenario 6: no PF / no ESI
def test_s6_without_pf_and_esi():
    r = calculate(make(pf_applicable=False, esi_applicable=False))
    assert "PF" not in r.deductions and "ESI" not in r.deductions
    assert r.net == r.gross


# ---------------- scenario 7: above ESI ceiling, PF capped at 15,000 wage
def test_s7_high_salary_caps():
    r = calculate(make(components={"BASIC": D(30000), "HRA": D(12000), "SPECIAL": D(8000)}))
    assert "ESI" not in r.deductions
    assert r.deductions["PF"] == D(1800)  # 12% of the 15,000 ceiling
    assert r.employer["EPS"] == D(1250)


# ---------------- scenario 8: retro salary change paid as arrears
def test_s8_retro_change_as_arrear():
    r = calculate(make(variable={"ARREAR": D(1500)}))
    assert r.earnings["ARREAR"] == D(1500)
    assert r.gross == D(19500)


# ---------------- scenario 9: exit mid-month (paid to last working day)
def test_s9_exit_mid_month():
    r = calculate(make(paid_days=D(15)))
    assert r.gross == D(9000)
    assert r.deductions["PF"] == D(600)


# ---------------- scenario 10: statutory per entity vs combined (open decision Case 2 vs Case 4)
def test_s10_statutory_basis_options():
    allocs = [Allocation("VHPL", "percent", D(50), True), Allocation("VRL", "percent", D(50))]
    comps = {"BASIC": D(24000), "HRA": D(6000)}
    combined = calculate(make(components=comps, allocations=allocs))
    rules = deepcopy(DEFAULT_RULES)
    rules["statutory_basis"] = "per_entity"
    per = calculate(make(components=comps, allocations=allocs), rules)
    assert combined.deductions["PF"] == D(1800)  # ceiling applied once on total
    assert per.deductions["PF"] == D(2880)  # each entity: 12% of 12,000 (below its own ceiling)
    assert per.gross == combined.gross


# ---------------- flags and guards
def test_negative_net_is_blocking():
    r = calculate(make(paid_days=D(5), variable={"ADVANCE": D(12000)}))
    assert r.net < 0
    assert any(f.code == "NEGATIVE_NET" and f.severity == "block" for f in r.flags)


def test_missing_bank_and_net_change_flags():
    r = calculate(make(has_bank=False, previous_net=D(10000)))
    codes = {f.code for f in r.flags}
    assert {"NO_BANK", "NET_CHANGE"} <= codes


def test_ot_and_night_allowance():
    r = calculate(make(ot_hours=D(10), night_shifts=4))
    # hourly = 18,000 / 30 / 8 = 75; x2 = 150; 10 hrs = 1,500
    assert r.earnings["OT"] == D(1500)
    assert r.earnings["NIGHT_ALLOWANCE"] == D(400)


def test_pt_only_in_september_and_march():
    assert "PT" not in calculate(make(month=11)).deductions
    r = calculate(make(month=9, components={"BASIC": D(20000), "HRA": D(8000)}))
    # half-year gross 168,000 -> top slab
    assert r.deductions["PT"] == D(1250)


def test_lwf_in_december():
    r = calculate(make(month=12))
    assert r.deductions["LWF"] == D(20) and r.employer["LWF_ER"] == D(40)


def test_tds_rebate_and_slabs():
    assert annual_income_tax(D(1200000), DEFAULT_RULES) == D(0)  # taxable 11.25 L: rebate
    tax = annual_income_tax(D(2400000), DEFAULT_RULES)  # taxable 23.25 L
    expected = slab_tax(D(2325000), DEFAULT_RULES["tds"]["slabs"]) * D("1.04")
    assert tax == expected.quantize(D(1))
    r = calculate(make(components={"BASIC": D(100000), "HRA": D(50000), "SPECIAL": D(50000)}))
    assert r.deductions["TDS"] > 0


def test_tds_override():
    assert calculate(make(tds_override=D(999))).deductions["TDS"] == D(999)


def test_split_amount_adds_up():
    parts = split_amount(D(1001), {"a": D(1) / 3, "b": D(1) / 3, "c": D(1) / 3})
    assert sum(parts.values()) == D(1001)


def test_same_inputs_same_result():
    a, b = calculate(make(ot_hours=D(3))).as_dict(), calculate(make(ot_hours=D(3))).as_dict()
    assert a == b


@pytest.mark.parametrize("paid", [D(0), D("0.5"), D(29.5), D(30)])
def test_paid_days_bounds(paid):
    r = calculate(make(paid_days=paid))
    assert r.gross >= 0 and r.paid_days == paid
