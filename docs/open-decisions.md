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
| 7 | Production domain and TLS certificate | CDK | CloudFront default domain |
