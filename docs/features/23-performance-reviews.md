# Performance review cycles

**Jira:** SCRUM-85, SCRUM-86 (part)  
**Status:** built (synthetic data on laptops). Items marked "not built" below are open.

## What it does

HR launches a review cycle; each employee gets KRAs from the department template in the client package. Self ratings (API only), manager rating and comment, and HR's calibrated final rating.

## Who uses it

| Role | Uses it to |
|---|---|
| HR | Launches and calibrates |
| HOD | Rates team |
| Employee | Self-review (API only for now) |

## Screens

- Performance (`/performance`) → Reviews

## Use cases

```mermaid
flowchart LR
  AHR(("HR"))
  AHOD(("HOD"))
  subgraph SYS["Peak HRMS: Performance review cycles"]
    U1(["Launch cycle"])
    U2(["Calibrate final rating"])
    U3(["Rate team member"])
    U4(["Self-review"])
  end
  AEmployee(("Employee"))
  AHR --- U1
  AHR --- U2
  AHOD --- U3
  U4 --- AEmployee
```

## Data flow (screen → API → tables)

| Screen action | API | Reads | Writes |
|---|---|---|---|
| Launch cycle | `POST /api/performance/cycles` | employees | review_cycles, reviews, outbox, audit_log |
| Open reviews | `GET /api/performance/cycles/{id}/reviews` | reviews, employees | — |
| Rate | `PUT /api/performance/reviews/{id}` | reviews | reviews, audit_log |

Diagram of the writes (every change also adds a row to `audit_log`, left out of the diagram for clarity):

```mermaid
flowchart LR
  S["Screen: Performance"]
  P1["Launch cycle<br/><small>POST /api/performance/cycles</small>"]
  S --> P1
  P1 --> Treview_cycles[("review_cycles")]
  P1 --> Treviews[("reviews")]
  P1 --> Toutbox[("outbox")]
  P2["Open reviews<br/><small>GET /api/performance/cycles/{id}/reviews</small>"]
  S --> P2
  P3["Rate<br/><small>PUT /api/performance/reviews/{id}</small>"]
  S --> P3
  P3 --> Treviews[("reviews")]
```

## Rules and limits

- Hotel Vivek KRA templates: services/hotel_vivek_backend/hotel_vivek/tenant.py (KRA_TEMPLATES).
- No screen yet for staff self-review; no drafted comment (SCRUM-86).

## Code and tests

- `services/hrms-core/backend/app/routers/people.py`
- Test: none yet
