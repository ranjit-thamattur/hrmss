"""Request context: who is acting, for which client, on which day.

Rule "client from the login": client_id comes from the signed-in user, never from the request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models as m


@dataclass
class Ctx:
    db: Session
    client_id: int
    actor: str
    user: m.AppUser | None = None  # None = the system itself (bootstrap, demo data)
    today: date = field(default_factory=date.today)
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def system(self) -> bool:
        return self.user is None

    @property
    def person_rid(self) -> int | None:
        return self.user.person_rid if self.user else None


def user_ctx(db: Session, user: m.AppUser) -> Ctx:
    return Ctx(db=db, client_id=user.client_id, actor=user.email, user=user)


def system_ctx(db: Session, client_id: int, actor: str = "system") -> Ctx:
    return Ctx(db=db, client_id=client_id, actor=actor, user=None)


def current(model: Any, on: date) -> Any:
    """SQL condition: the version of a record that applies on `on`."""
    return and_(model.valid_from <= on, or_(model.valid_to.is_(None), model.valid_to >= on))


def overlapping(model: Any, start: date, end: date | None) -> Any:
    """SQL condition: versions whose validity overlaps [start, end]."""
    conds = [or_(model.valid_to.is_(None), model.valid_to >= start)]
    if end is not None:
        conds.append(model.valid_from <= end)
    return and_(*conds)
