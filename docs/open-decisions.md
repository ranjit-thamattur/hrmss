# Open decisions (Hotel Vivek to confirm)

These are built as settings with **no guessed default** where a wrong guess changes pay.

| # | Decision | Where it is set | Until decided |
|---|---|---|---|
| 1 | Missed-punch rule at cut-off: present, LOP or hold | Policies (15) settings | Payroll is blocked while any missed punch is open |
| 2 | Statutory rates, slabs and basis (combined vs per-entity) | Statutory registrations (3) + rules module | Sample TN rules are used and marked *sample* |
| 3 | Biometric device vendor and API | Biometric devices (28): `connection` api / file | File import |
| 4 | Payroll day and attendance cut-off | Policies | 26th / 25th (sample) |
| 5 | OT rate and threshold | Statutory rules (`ot`) and Policies | 2× hourly, 30-minute threshold |
| 7 | Production domain and AWS account details for client.yaml (repository is on GitHub) | Infrastructure owner (PEAKHRMS-132) | Placeholders in client.yaml |
| 8 | Biometric machine model and its API / export format | PEAKHRMS-120 | Attendance runs on synthetic punches |
| 9 | Sign-in method for the Ask Brain link (single sign-on if possible) | Infrastructure owner (PEAKHRMS-131) | After the demo |
| 10 | Salary sheets for payroll checks | Client (PEAKHRMS-126) | Payroll work on hold |
