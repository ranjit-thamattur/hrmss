# 03 Request and sign-in flow

1. `POST /api/auth/login` (email, password) -> Cognito (cognito-local on laptops) -> access token. First sign-in with a temporary
   password returns a `NEW_PASSWORD_REQUIRED` challenge; `POST /api/auth/new-password` completes it.
2. Every other call sends `Authorization: Bearer <token>`. `deps.current_user` verifies the token and finds the login (by Cognito `sub`).
3. **Client from the login (rule 1):** the request context takes `client_id` from the user. A `client_id` in a request body is ignored.
4. **Role:** `access.require(resource, action)` reads the client's role-permission rows (data, not code). No row = 403.
5. **Data scope (rule 7):** the permission's scope mode - `all`, `scoped` (the user's entities / locations / departments, widened through
   entity-at-location and department-in-entity links), `team` (people reporting to the user), `self`. A record outside the scope is 404.
6. **Masking (rule 8):** fields listed in the permission's `masked_fields` are shown as `XXXX1234`. Secrets (PAN, Aadhaar, account
   numbers) are stored encrypted and masked in the audit log.
7. The router commits once; on any error nothing is saved.
