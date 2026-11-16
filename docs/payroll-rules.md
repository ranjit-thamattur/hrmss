# Payroll rules (as built)

All amounts monthly, in rupees, rounded to the rupee. The code is `backend/app/domain/payroll_engine.py`; every rule below has a unit test.

| Item | Rule (sample, confirm with auditor) |
|---|---|
| Paid days | Days in month − LOP days. Days before joining / after leaving are LOP. |
| Earnings | Each salary component × paid days ÷ days in month. Monthly inputs (service charge, incentive, arrears, bonus) are added as they are. |
| OT | (Basic + DA) ÷ days in month ÷ 8 × 2 × approved OT hours. Only OT approved by HOD/HR counts. |
| Night allowance | ₹100 per night shift worked |
| PF | 12% employee on (Basic + DA) capped at ₹15,000. Employer: EPS 8.33% (capped), EPF balance, EDLI 0.5%, admin 0.5%. |
| ESI | When fixed gross ≤ ₹21,000: 0.75% employee, 3.25% employer, rounded up |
| PT (Tamil Nadu) | Half-yearly slab, deducted in September and March |
| LWF (Tamil Nadu) | December: ₹20 employee, ₹40 employer |
| TDS | New regime: annual projection, slabs, ₹12 lakh rebate, 4% cess, spread over remaining months. TDS override input wins. |
| Advances and loans | Deducted as entered in monthly inputs |

## Checks on every line
`NEGATIVE_NET` and `NO_BANK` block; `LOP_HIGH`, `OT_HIGH`, `NET_CHANGE` (>20% vs last month), `BELOW_MIN_WAGE`, `ZERO_PAY_DAYS` and `NO_STRUCTURE` warn. Each flagged line needs a decision (accept with a note, or hold) before submission. Negative pay can only be held or fixed. Held lines are left out of the bank file.

## Flow
Calculated → Reviewed (preparer submits) → HR approved → Finance approved → Locked. A different person approves at each step. Locked runs cannot change; bank, Tally, EPF ECR, ESI files and payslips are created only from locked runs.
