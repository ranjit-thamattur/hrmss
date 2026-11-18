# Monitoring flow (SCRUM-130)

```mermaid
flowchart LR
  subgraph APIBOX["API process"]
    LOOP["Every 60 s: run checks"] --> C1["web: GET MONITOR_WEB_URL"]
    LOOP --> C2["api: requests, errors, p95 (15 min)"]
    LOOP --> C3["database: SELECT 1, size, connections"]
    LOOP --> C4["signin: Cognito user pool call, failed sign-in tasks"]
    LOOP --> C5["biometric: device API (http) and age of newest punch"]
    C1 & C2 & C3 & C4 & C5 --> S[("monitor_samples")]
    S --> R{"Alert rules"}
    R -- "down x2" --> AC["critical"]
    R -- "degraded x3" --> AW["warning"]
    R -- "up" --> AR["resolve open alert"]
    AC & AW --> A[("monitor_alerts")]
    AC & AW --> O[("outbox: email to MONITOR_ALERT_EMAILS")]
  end
  A --> UI["Monitoring screen (master admin)<br/>status, uptime 24 h, history, acknowledge"]
  A --> DSH["Dashboard: system alerts open"]
```

| Service | Up | Degraded | Down |
|---|---|---|---|
| Web app | HTTP 200 under 1.5 s | slower | not reachable / not 200 |
| API | normal | >5% server errors (≥20 requests) or p95 > 2 s | — (cannot report itself; container health check and infrastructure monitoring cover it) |
| Database | SELECT 1 under 500 ms | slower | error |
| Sign-in | user pool answers | failed sign-in provisioning tasks | Cognito not reachable |
| Biometric | punches newer than 26 h | no new punches for 26 h, or none yet | device API not reachable (http adapter) |

Settings: `MONITOR_INTERVAL_SECONDS` (60), `MONITOR_WEB_URL`, `MONITOR_BIOMETRIC_STALE_HOURS` (26), `MONITOR_ALERT_EMAILS`, `MONITOR_KEEP_DAYS` (7).
