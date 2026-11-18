# Request and sign-in flow

```mermaid
sequenceDiagram
  actor U as User
  participant W as Web app
  participant A as API
  participant C as Cognito
  participant D as Database
  U->>W: email + password
  W->>A: POST /api/auth/login
  A->>D: user active?
  A->>C: InitiateAuth (USER_PASSWORD_AUTH)
  alt first sign-in
    C-->>A: NEW_PASSWORD_REQUIRED + session
    A-->>W: challenge
    U->>W: new password
    W->>A: POST /api/auth/new-password
    A->>C: RespondToAuthChallenge
  end
  C-->>A: access token (sub, groups, no email)
  A->>D: save sub on app_users.identity_sub
  A-->>W: token
  W->>A: GET /api/auth/me (Bearer token)
  A->>C: signing keys (JWKS, cached)
  A->>D: find user by identity_sub, then email
  A-->>W: user, roles, permissions, company
  W->>A: any /api call
  A->>A: check permission (access.py), limit to entity/location/team, mask fields
  A->>D: read / write (+ audit_log on change)
```

- On laptops without Docker, `AUTH_MODE=local` replaces Cognito with app-held passwords; the flow is the same for the user.
- The menu hides what a role cannot do, but the API is where access is decided.
