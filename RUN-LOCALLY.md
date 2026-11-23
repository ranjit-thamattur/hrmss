# Run Peak HRMS on your own machine

This guide gets the whole HRMS backend running on a laptop with Docker: database, sign-in and API, loaded with
**synthetic** Hotel Vivek demo data. It works the same on Windows, macOS and Linux. Nothing else needs to be installed.

> Laptops hold synthetic data only. Never load real client data on a laptop; real data lives only in QA/production
> (the client's own AWS account).

---

## 1. What you need

| Tool | Get it | Check it |
|---|---|---|
| Docker Desktop (Windows / macOS) or Docker Engine + Compose plugin (Linux) | https://www.docker.com/products/docker-desktop | `docker compose version` |
| Git | https://git-scm.com/downloads (Windows: includes Git Bash) | `git --version` |
| Postman (optional, to test the APIs) | https://www.postman.com/downloads | - |

- **Windows:** use **Git Bash** for the commands below. Docker Desktop must use the WSL 2 engine (the default).
- Docker Desktop must be **running** (whale icon in the taskbar / menu bar) before you start.
- About 2 GB free disk space and 4 GB RAM for Docker.

## 2. Get the code

```bash
git clone https://github.com/ranjit-thamattur/hrmss.git
cd hrmss
git checkout qa            # or the branch you were told to use, e.g. feature/PEAKHRMS-135-company-setup-onboarding
```

Already have it? `cd hrmss && git pull`.

## 3. Start everything

```bash
docker compose up --build -d
```

The first start takes 2-3 minutes (downloads Postgres and Python, builds the API). It starts three containers:

| Container | What it is | Port on your machine |
|---|---|---|
| `db` | PostgreSQL 16, database `hrms_hv` | 5432 |
| `cognito` | local stand-in for AWS Cognito (sign-in) | 9229 |
| `api` | the HRMS API (FastAPI) | **8000** |

On the first start the API creates the tables, sets up the client Hotel Vivek from `client.yaml`, and loads the demo data.
Watch it happen:

```bash
docker compose logs -f api
```

Wait for these lines, then press **Ctrl+C** (this only stops watching; the API keeps running):

```
Client HV (Hotel Vivek) ready in database hrms_hv.
Demo data: 3 entities, 5 locations, 27 people, 7 logins (password: DEMO_PASSWORD).
Uvicorn running on http://0.0.0.0:8000
```

## 4. Check it works

```bash
curl http://localhost:8000/api/health
bash scripts/smoke-test.sh
```

- Health returns `{"status":"ok", ..., "client":"HV", "environment":"local"}`.
- The smoke test signs in as every role and ends with **SMOKE TEST PASSED**.

## 5. Use it

### Logins (synthetic, laptop only) - password `Peak@12345` for all

| Email | Role | Sees |
|---|---|---|
| admin@hotelvivek.local | master admin | everything |
| hr@hotelvivek.local | HR | all setup and people; onboards employees |
| hr.ooty@hotelvivek.local | HR, Ooty only | only Ooty and its people |
| payroll@hotelvivek.local | payroll preparer | view everything |
| finance@hotelvivek.local | finance approver | view everything |
| hod@hotelvivek.local | head of department | own team; PAN/Aadhaar masked |
| employee@hotelvivek.local | employee | only themselves |

### API docs in the browser (Swagger)
1. Open **http://localhost:8000/docs**.
2. `POST /api/auth/login` → **Try it out** → body `{"email": "admin@hotelvivek.local", "password": "Peak@12345"}` → **Execute**.
3. Copy the `token` value (without quotes) → click **Authorize** (top right) → paste → **Authorize** → **Close**.
4. Every endpoint can now be tried with **Try it out**.

### Postman
1. Postman → **Import** → select both files in `postman/`:
   `Peak-HRMS-Core.postman_collection.json` and `local.postman_environment.json`.
2. Top right: choose the environment **Peak HRMS local (synthetic)**.
3. Right-click the collection → **Run** → **Run Peak HRMS...**. Every request has tests; all should pass.
4. The two import requests need a file. If Postman says it cannot find it, open that request → **Body** → pick the file from
   `postman/samples/` (`departments-import.xlsx`, `employee-master-import.xlsx`).

### Look inside the database (optional)
- Web viewer: `docker compose --profile tools up -d`, then **http://localhost:8081**
  (System *PostgreSQL*, Server `db`, Username `hrms`, Password `hrms`, Database `hrms_hv`).
- Command line: `docker compose exec db psql -U hrms -d hrms_hv` (type `\dt` for tables, `\q` to quit).
- Any desktop tool (DBeaver, pgAdmin): host `localhost`, port `5432`, same user / password / database.

## 6. Everyday commands

| I want to... | Command |
|---|---|
| Start (after a restart of the laptop) | `docker compose up -d` |
| See what is running | `docker compose ps` (api should say *healthy*) |
| Watch the API log | `docker compose logs -f api` |
| Get new code and run it | `git pull` then `docker compose up --build -d` |
| Stop (keep my data) | `docker compose down` |
| Start again with fresh demo data | `docker compose down -v` then `docker compose up --build -d` |
| Create my own admin login | `docker compose exec api python -m app.admin create-admin you@example.com "Your Name"` |
| Run the backend tests | see `README.md` → Test |

## 7. Change ports or settings (optional)

Copy the example settings file and edit it:

```bash
cp .env.example .env
```

| Setting | Default | Use it when |
|---|---|---|
| `API_PORT` | 8000 | port 8000 is already used on your machine (then open http://localhost:NEW/docs and run `BASE=http://localhost:NEW bash scripts/smoke-test.sh`) |
| `DB_PORT` | 5432 | you already run Postgres locally |
| `COGNITO_PORT`, `ADMINER_PORT` | 9229, 8081 | those ports are taken |
| `AUTH_MODE` | cognito | set `local` if sign-in through the local Cognito container fails |
| `SEED_DEMO` | true | set `false` to start with an empty client (create an admin with the command above) |
| `DEMO_PASSWORD` | Peak@12345 | you want another password for the demo logins (before the first start) |

After changing `.env`: `docker compose up -d` (add `--build` if the code changed). Changing `SEED_DEMO` or
`DEMO_PASSWORD` only matters for a fresh database (`docker compose down -v` first).

## 8. When something goes wrong

| You see | Do this |
|---|---|
| `no configuration file provided: not found` | You are not in the `hrmss` folder, or on a branch without `docker-compose.yml`. `cd hrmss`, `git status`, switch to `qa`. |
| `Cannot connect to the Docker daemon` / `error during connect` | Start Docker Desktop and wait until it says *running*. |
| `port is already allocated` / `address already in use` | Another program uses that port: change it in `.env` (section 7), or stop the other program. |
| `api` keeps restarting | `docker compose logs api` and read the last lines. Often fixed by `docker compose down -v` then `up --build -d`. |
| Sign-in returns an error | Wait 30 seconds after start. If it persists: set `AUTH_MODE=local` in `.env`, then `docker compose down -v` and `up --build -d`. |
| `This database belongs to client ...` | The database volume is from another client: `docker compose down -v`, then start again. |
| Old containers from an earlier version still running | `docker compose -p peak-hrms down -v`, then `docker compose up --build -d`. |
| `exec ./docker-entrypoint.sh: no such file` (Windows) | Line endings were changed by Git; the image fixes this itself - rebuild with `docker compose build --no-cache api`. |
| Apple Silicon (M1/M2/M3) image error for `cognito` | Add `platform: linux/amd64` under `cognito:` in `docker-compose.yml`, or use `AUTH_MODE=local`. |
| Everything is slow / out of disk | Docker Desktop → Settings → Resources: give 4 GB RAM; `docker system prune` removes old images. |

Still stuck: send the output of `docker compose ps` and `docker compose logs --tail 80 api` to the backend owner.

## 9. What is where

| Path | What |
|---|---|
| `docker-compose.yml` | the local stack described above |
| `.env.example` | optional local settings (copy to `.env`) |
| `services/hrms-core/backend/` | the HRMS core API |
| `services/hotel_vivek_backend/` | Hotel Vivek: `client.yaml`, its APIs, the synthetic demo data |
| `postman/` | Postman collection, environment and sample Excel files |
| `scripts/smoke-test.sh` | signs in as every role and checks what each sees |
| `docs/` | features, architecture, data dictionary, handover |
