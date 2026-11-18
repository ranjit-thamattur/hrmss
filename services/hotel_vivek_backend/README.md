# Hotel Vivek – backend client package (tenant HV)

Everything in the API that is specific to Hotel Vivek. hrms-core loads it with `TENANT=HV` and `TENANT_PACKAGE=hotel_vivek` (decision 0006).

| Path | What |
|---|---|
| `hotel_vivek/tenant.py` | Code `HV`, name, laptop demo users, **synthetic** organisation and staff, KRA templates, Excel template examples |
| `tests/` | Hotel Vivek end-to-end API tests (run: `pytest` in this folder) |
| `samples/` | Synthetic Excel files for import testing (`python scripts/make_samples.py` rebuilds them) |
| `Dockerfile` | API image = hrms-core backend + this package (build context: `services/`) |

Never put real Hotel Vivek data in this folder. Real data is loaded only in QA/production, through Company setup and the Excel imports.
