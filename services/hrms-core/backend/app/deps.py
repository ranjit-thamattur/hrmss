"""Request dependencies: database session, signed-in user, request context."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from .core.context import Ctx, user_ctx
from .core.identity import CognitoIdentity, get_identity
from .db import get_db

DB = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False, description="Token from POST /api/auth/login")


def current_user(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None) -> m.AppUser:
    if creds is None or not creds.credentials:
        raise HTTPException(401, "Sign in first (Authorization: Bearer <token>).")
    token = creds.credentials.strip()
    idp = get_identity()
    if isinstance(idp, CognitoIdentity):
        ident = idp.verify(token, db)  # Cognito sub (no email in access tokens)
        user = db.scalar(select(m.AppUser).where(or_(m.AppUser.identity_sub == ident, m.AppUser.email == ident.lower())))
    else:
        user = db.scalar(select(m.AppUser).where(m.AppUser.email == idp.verify(token)))
    if not user or not user.is_active:
        raise HTTPException(401, "Your account is not active.")
    return user


User = Annotated[m.AppUser, Depends(current_user)]


def context(db: DB, user: User) -> Ctx:
    """The client is the signed-in user's client: a client_id in the request is never used."""
    return user_ctx(db, user)


C = Annotated[Ctx, Depends(context)]


def touch_login(db: Session, email: str) -> None:
    u = db.scalar(select(m.AppUser).where(m.AppUser.email == email.lower().strip()))
    if u is not None:
        u.last_login_at = datetime.now(timezone.utc)
        db.commit()
