# Open decisions (Hotel Vivek to confirm)

These are built as settings with **no guessed default** where a wrong guess changes pay.

| # | Decision | Where it is set | Until decided |
|---|---|---|---|
| 1 | Missed-punch rule at cut-off: present, LOP or hold | Company setup → Policies → Missed punch rule | Payroll is blocked while any missed punch is open |
| 2 | Statutory rates, slabs and basis (combined vs per-entity) | Company setup → Statutory rules | Sample TN rules are used and marked *sample* |
| 3 | Biometric device vendor and API | `BIOMETRIC_ADAPTER` | Excel export import |
| 4 | Payroll day and attendance cut-off | Policies | 26th / 25th (sample) |
| 5 | OT rate and threshold | Statutory rules (`ot`) and Policies | 2× hourly, 30-minute threshold |
| 6 | WhatsApp Business account for messages | Outbox | Messages queue but are not sent |
| 7 | Production domain, hosting, pipeline host (Bitbucket or GitHub) | Infrastructure owner (SCRUM-132) | Open |
| 8 | Biometric machine model and its API / export format | SCRUM-120 | Attendance runs on synthetic punches |
| 9 | Sign-in method for the Ask Brain link (single sign-on if possible) | Infrastructure owner (SCRUM-131) | After the demo |
| 10 | Salary sheets for payroll checks | Client (SCRUM-126) | Payroll work on hold |
