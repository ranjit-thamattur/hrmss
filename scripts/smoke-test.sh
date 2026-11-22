#!/usr/bin/env bash
# Smoke test from a clean checkout (PEAKHRMS-123): waits for the API, signs in as every demo role and shows
# what each role sees. Laptop only, SYNTHETIC demo data. Needs: curl (Git Bash has it).
#   ./scripts/smoke-test.sh                 against http://localhost:8000
#   BASE=http://localhost:8000 ./scripts/smoke-test.sh
set -u
BASE="${BASE:-http://localhost:8000}"
PASSWORD="${DEMO_PASSWORD:-Peak@12345}"
fail=0

echo "Waiting for $BASE/api/health ..."
for _ in $(seq 1 60); do
  if curl -fsS "$BASE/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
health=$(curl -fsS "$BASE/api/health") || { echo "FAIL: API not reachable. Run: docker compose up --build -d"; exit 1; }
echo "OK   health: $health"

field() { sed -n "s/.*\"$1\":\([0-9]*\).*/\1/p"; }

for who in admin hr hr.ooty payroll finance hod employee; do
  email="$who@hotelvivek.local"
  resp=$(curl -sS -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" -d "{\"email\":\"$email\",\"password\":\"$PASSWORD\"}")
  token=$(printf '%s' "$resp" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  if [ -z "$token" ]; then echo "FAIL $email: $resp"; fail=1; continue; fi
  roles=$(curl -sS "$BASE/api/auth/me" -H "Authorization: Bearer $token" | sed -n 's/.*"roles":\[\([^]]*\)\].*/\1/p')
  people=$(curl -sS "$BASE/api/employee?size=1" -H "Authorization: Bearer $token" | field total)
  locs=$(curl -sS "$BASE/api/setup/locations?size=1" -H "Authorization: Bearer $token" | field total)
  printf 'OK   %-28s roles=%-22s sees people=%-4s locations=%s\n' "$email" "$roles" "${people:-403}" "${locs:-403}"
done

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/setup/locations")
[ "$code" = "401" ] && echo "OK   no token -> 401" || { echo "FAIL no token -> $code"; fail=1; }

[ $fail -eq 0 ] && echo "SMOKE TEST PASSED" || { echo "SMOKE TEST FAILED"; exit 1; }
