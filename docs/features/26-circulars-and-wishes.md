# Circulars and wishes

**Jira:** SCRUM-90 (part)  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

HR writes a circular in English plus the client's other languages, for all staff or chosen locations and departments. Each employee gets their own language. Read tracking per circular. Birthday and work-anniversary wishes are queued daily.

## Who uses it

| Role | Uses it to |
|---|---|
| HR, Master admin | Send circulars |
| Employees | Receive |

## Screens

- Circulars (`/circulars`) → Circulars, Outbox

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  subgraph SYS["Peak HRMS: Circulars and wishes"]
    U1(["Send circular"])
    U2(["Queue wishes"])
    U3(["See outbox"])
    U4(["Read circular"])
  end
  AEmployee(("Employee"))
  AHR --- U1
  AHR --- U2
  AHR --- U3
  U4 --- AEmployee
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| Send circular | `POST /api/circulars` | employees | circulars, outbox, audit_log |
| Mark read | `POST /api/circulars/{id}/read` | circulars | circular_reads |
| Queue today's wishes | `POST /api/wishes/today` | employees | outbox |
| See outbox | `GET /api/outbox` | outbox | — |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Circulars"]
  P1["Send circular<br/><small>POST /api/circulars</small>"]
  S --> P1
  P1 --> Tcirculars[("circulars")]
  P1 --> Toutbox[("outbox")]
  P2["Mark read<br/><small>POST /api/circulars/{id}/read</small>"]
  S --> P2
  P2 --> Tcircular_reads[("circular_reads")]
  P3["Queue today's wishes<br/><small>POST /api/wishes/today</small>"]
  S --> P3
  P3 --> Toutbox[("outbox")]
  P4["See outbox<br/><small>GET /api/outbox</small>"]
  S --> P4
```

## Rules and limits

- No automatic translation; translations are typed and checked by a native speaker.
- WhatsApp sending is not live (outbox only).

## Code and tests

- `services/hrms-core/backend/app/routers/people.py`
- `services/hrms-core/frontend/src/pages/Comms.jsx`
- Test: `test_api_hv.py::test_reports_dashboard_circular`
