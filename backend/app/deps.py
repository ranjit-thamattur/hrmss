from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as m
from .db import get_db
from .services.identity import CognitoIdentity, get_identity

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> m.AppUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first.")
    token = authorization.split(" ", 1)[1]
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
