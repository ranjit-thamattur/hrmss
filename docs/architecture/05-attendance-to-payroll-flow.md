# Attendance to payroll flow

```mermaid
flowchart TB
  P1["Biometric device / Excel export"] --> P2[("punches")]
  P2 --> P3["Process month: pair punches per shift<br/>(roster, night shifts across midnight, holidays, leave)"]
  P3 --> P4[("attendance_days")]
  P4 --> P5{"Exceptions"}
  P5 -- "missed punch" --> P6["Fix by HR, staff request + HOD approval,<br/>or the client's missed-punch rule at cut-off"]
  P5 -- "OT" --> P7["HOD approves OT"]
  P6 --> P4
  P7 --> P4
  P4 --> P8["Month summary: paid days, LOP, approved OT, night shifts"]
  P9[("monthly_inputs")] --> P10
  P8 --> P10["Payroll run per entity<br/>(locks attendance)"]
  P11[("salary_structures, entity_allocations,<br/>statutory_rule_versions")] --> P10
  P10 --> P12[("payroll_runs, payroll_lines")]
  P12 --> P13{"Flagged lines"}
  P13 --> P14["Accept with note or hold<br/>(negative pay: hold only)"]
  P14 --> P15["Submit → HR approve → Finance approve → Lock"]
  P15 --> P16["Bank file, Tally, EPF ECR, ESI, payslips, statutory calendar"]
```

- Payroll is blocked while missed punches are open and the missed-punch rule is not set (no default).
- Payroll work is on hold until the client's salary sheets arrive; the flow above is built and tested with synthetic data.
