# Hotel Vivek backend (client HV)

Everything that makes a deployment "Hotel Vivek". The core loads it through `CLIENT_CONFIG` (this folder's `client.yaml`), which names
the package `hotel_vivek` (decision 0007).

| Path | What |
|---|---|
| `client.yaml` | client code HV, name, country, currency, database `hrms_hv`, domain, AWS account (placeholders), onboarding rules |
| `hotel_vivek/client.py` | `CODE`, `ROUTERS` (this client's APIs), `load_demo` |
| `hotel_vivek/api/employees.py` | `POST /api/employee/add` and the other employee APIs (docs/features/06-onboarding.md) |
| `hotel_vivek/demo.py` | **synthetic** demo data for laptops: 3 entities, 5 locations, 27 people, 7 logins |
| `tests/` | onboarding and employee API tests: `pytest -q` in this folder |
| `Dockerfile` | API image = hrms-core backend + this YAML and package (build context: `services/`) |

Never put real Hotel Vivek data in this folder. Real data is entered only in QA/production, through the APIs or the Excel imports.
