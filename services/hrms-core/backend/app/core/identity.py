"""Sign-in and user provisioning.

AUTH_MODE=cognito: AWS Cognito (cognito-local container in Docker, the client's own user pool on AWS).
AUTH_MODE=local:   passwords kept by this app — for quick native runs and automated tests only.

Both modes behave the same for the user: new users get a temporary password and must set their own
on first sign-in (Cognito's NEW_PASSWORD_REQUIRED challenge).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from .defaults import DEFAULT_ROLES
from .security import hash_password, issue_local_token, password_ok, verify_local_token, verify_password

log = logging.getLogger("hrms.identity")
settings = get_settings()

NEW_PASSWORD = "NEW_PASSWORD_REQUIRED"


def _active_user(db: Session, email: str) -> m.AppUser:
    u = db.scalar(select(m.AppUser).where(m.AppUser.email == email.lower().strip()))
    if not u or not u.is_active:
        raise HTTPException(401, "Email or password is wrong, or the account is not active.")
    return u


class LocalIdentity:
    mode = "local"

    def authenticate(self, db: Session, email: str, password: str) -> dict[str, Any]:
        u = _active_user(db, email)
        if not verify_password(password, u.password_hash):
            raise HTTPException(401, "Email or password is wrong, or the account is not active.")
        if u.must_change_password:
            exp = datetime.now(timezone.utc) + timedelta(minutes=10)
            session = jwt.encode({"sub": u.email, "purpose": "npw", "exp": exp}, settings.jwt_secret, algorithm="HS256")
            return {"challenge": NEW_PASSWORD, "session": session}
        return {"token": issue_local_token(u.email)}

    def complete_new_password(self, db: Session, email: str, new_password: str, session: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(session, settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as e:
            raise HTTPException(401, "The sign-in session expired. Sign in again.") from e
        if claims.get("purpose") != "npw" or claims.get("sub") != email.lower().strip():
            raise HTTPException(401, "Invalid session")
        if err := password_ok(new_password):
            raise HTTPException(400, err)
        u = _active_user(db, email)
        u.password_hash = hash_password(new_password)
        u.must_change_password = False
        db.commit()
        return {"token": issue_local_token(u.email)}

    def verify(self, token: str) -> str:
        try:
            return verify_local_token(token)["email"]
        except jwt.PyJWTError as e:
            raise HTTPException(401, "Session expired. Sign in again.") from e

    def create_user(self, db: Session, user: m.AppUser, temp_password: str) -> str:
        user.password_hash = hash_password(temp_password)
        user.must_change_password = True
        return f"local-{user.email}"

    def set_groups(self, db: Session, user: m.AppUser) -> None:
        return None

    def set_permanent_password(self, db: Session, user: m.AppUser, password: str) -> None:
        """Demo users on laptops only: a known password, no change at first sign-in."""
        user.password_hash = hash_password(password)
        user.must_change_password = False

    def set_enabled(self, db: Session, user: m.AppUser, enabled: bool) -> None:
        return None

    def bootstrap(self, db: Session) -> None:
        return None


class CognitoIdentity:
    mode = "cognito"

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client("cognito-idp", region_name=settings.cognito_region, endpoint_url=settings.cognito_endpoint or None)

    # ---- pool and client ids come from settings, or from the database after bootstrap (cognito-local)
    def ids(self, db: Session) -> tuple[str, str]:
        pool, client = settings.cognito_user_pool_id, settings.cognito_client_id
        if not pool or not client:
            p = db.get(m.AppSetting, "cognito_user_pool_id")
            c = db.get(m.AppSetting, "cognito_client_id")
            pool, client = (p.value if p else None), (c.value if c else None)
        if not pool or not client:
            raise HTTPException(503, "Cognito is not configured (set COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID, or COGNITO_BOOTSTRAP=true).")
        return pool, client

    def bootstrap(self, db: Session) -> None:
        """Create the pool, app client and role groups once (cognito-local). On AWS they are set up by the
        infrastructure owner (PEAKHRMS-132) and passed in COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID."""
        if settings.cognito_user_pool_id or db.get(m.AppSetting, "cognito_user_pool_id"):
            return
        pool = self.client.create_user_pool(
            PoolName=f"hrms-{str(settings.client.get('client', {}).get('code', 'core')).lower()}",
            Policies={"PasswordPolicy": {"MinimumLength": 8, "RequireUppercase": True, "RequireLowercase": True, "RequireNumbers": True,
                                         "RequireSymbols": False}},
        )["UserPool"]["Id"]
        client = self.client.create_user_pool_client(UserPoolId=pool, ClientName="hrms-web", GenerateSecret=False,
                                                     ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]
        for role, label in DEFAULT_ROLES.items():
            try:
                self.client.create_group(UserPoolId=pool, GroupName=role, Description=label)
            except Exception as e:  # noqa: BLE001 - group may already exist / not supported locally
                log.warning("create_group %s: %s", role, e)
        db.merge(m.AppSetting(key="cognito_user_pool_id", value=pool))
        db.merge(m.AppSetting(key="cognito_client_id", value=client))
        db.commit()
        log.info("Cognito bootstrap: pool %s client %s", pool, client)

    @staticmethod
    def _code(e: Exception) -> str:
        return getattr(e, "response", {}).get("Error", {}).get("Code", "")

    def authenticate(self, db: Session, email: str, password: str) -> dict[str, Any]:
        _active_user(db, email)
        _, client = self.ids(db)
        try:
            r = self.client.initiate_auth(AuthFlow="USER_PASSWORD_AUTH", ClientId=client,
                                          AuthParameters={"USERNAME": email.lower().strip(), "PASSWORD": password})
        except Exception as e:  # noqa: BLE001
            if self._code(e) in ("NotAuthorizedException", "UserNotFoundException"):
                raise HTTPException(401, "Email or password is wrong, or the account is not active.") from e
            raise
        if r.get("ChallengeName"):
            return {"challenge": r["ChallengeName"], "session": r.get("Session")}
        return {"token": _remember_sub(db, email, r["AuthenticationResult"]["AccessToken"])}

    def complete_new_password(self, db: Session, email: str, new_password: str, session: str) -> dict[str, Any]:
        if err := password_ok(new_password):
            raise HTTPException(400, err)
        _, client = self.ids(db)
        try:
            r = self.client.respond_to_auth_challenge(ClientId=client, ChallengeName=NEW_PASSWORD, Session=session,
                                                      ChallengeResponses={"USERNAME": email.lower().strip(), "NEW_PASSWORD": new_password})
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Could not set the new password ({self._code(e) or e}).") from e
        return {"token": _remember_sub(db, email, r["AuthenticationResult"]["AccessToken"])}

    @lru_cache(maxsize=4)  # noqa: B019 - one client per pool, process lifetime
    def _jwks(self, url: str) -> jwt.PyJWKClient:
        return _jwks_client(url)

    def verify(self, token: str, db: Session | None = None) -> str:
        from ..db import SessionLocal

        own = db is None
        db = db or SessionLocal()
        try:
            pool, client = self.ids(db)
        finally:
            if own:
                db.close()
        base = f"{settings.cognito_endpoint.rstrip('/')}/{pool}" if settings.cognito_endpoint else f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/{pool}"
        try:
            key = self._jwks(base + "/.well-known/jwks.json").get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], options={"verify_aud": False, "verify_iss": False})
        except (jwt.PyJWTError, jwt.PyJWKClientError) as e:
            log.warning("Cognito token rejected: %s", e)
            raise HTTPException(401, "Session expired. Sign in again.") from e
        if not str(claims.get("iss", "")).rstrip("/").endswith(pool):
            log.warning("Cognito token from another pool: %s", claims.get("iss"))
            raise HTTPException(401, "Token from another user pool")
        if claims.get("token_use") == "access" and claims.get("client_id") not in (None, client):
            raise HTTPException(401, "Token for another app")
        # Cognito access tokens carry no email. With email sign-in the username is a generated id equal to `sub`,
        # so the caller looks the user up by identity_sub first and by email second.
        ident = claims.get("sub") or claims.get("username") or claims.get("cognito:username") or claims.get("email")
        if not ident:
            raise HTTPException(401, "Token has no user id")
        return str(ident)

    def create_user(self, db: Session, user: m.AppUser, temp_password: str) -> str:
        pool, _ = self.ids(db)
        try:
            r = self.client.admin_create_user(UserPoolId=pool, Username=user.email, TemporaryPassword=temp_password, MessageAction="SUPPRESS",
                                              UserAttributes=[{"Name": "email", "Value": user.email}, {"Name": "email_verified", "Value": "true"},
                                                              {"Name": "name", "Value": user.display_name}])
            attrs = r["User"].get("Attributes", [])
        except Exception as e:  # noqa: BLE001
            if self._code(e) != "UsernameExistsException":
                raise
            attrs = self.client.admin_get_user(UserPoolId=pool, Username=user.email).get("UserAttributes", [])
        self.set_groups(db, user)
        return next((a["Value"] for a in attrs if a["Name"] == "sub"), user.email)

    def set_groups(self, db: Session, user: m.AppUser) -> None:
        pool, _ = self.ids(db)
        for role in user.roles or []:
            try:
                self.client.admin_add_user_to_group(UserPoolId=pool, Username=user.email, GroupName=role)
            except Exception as e:  # noqa: BLE001 - roles are enforced from our database; groups are a mirror
                log.warning("add to group %s failed: %s", role, e)

    def set_permanent_password(self, db: Session, user: m.AppUser, password: str) -> None:
        """Demo users on laptops only: a known password, no change at first sign-in."""
        pool, _ = self.ids(db)
        self.client.admin_set_user_password(UserPoolId=pool, Username=user.email, Password=password, Permanent=True)
        user.must_change_password = False

    def set_enabled(self, db: Session, user: m.AppUser, enabled: bool) -> None:
        pool, _ = self.ids(db)
        fn = self.client.admin_enable_user if enabled else self.client.admin_disable_user
        fn(UserPoolId=pool, Username=user.email)


@lru_cache
def get_identity() -> LocalIdentity | CognitoIdentity:
    return CognitoIdentity() if settings.auth_mode == "cognito" else LocalIdentity()


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def _remember_sub(db: Session, email: str, token: str) -> str:
    """Store the Cognito `sub` on the user so later requests (whose tokens carry no email) map back to them."""
    sub = jwt.decode(token, options={"verify_signature": False}).get("sub")
    user = db.scalar(select(m.AppUser).where(m.AppUser.email == email.lower().strip()))
    if sub and user and user.identity_sub != sub:
        user.identity_sub = sub
        db.commit()
    return token
