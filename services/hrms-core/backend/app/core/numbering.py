"""Number series (entity 17): employee and document numbers, allocated atomically, never reused.

The counter row is locked while a number is taken (SELECT ... FOR UPDATE on Postgres), and every number
handed out is written to number_allocations, whose unique key makes a second use impossible.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, select

from .. import models as m
from .context import Ctx, current


def find_series(ctx: Ctx, obj: str, legal_entity_rid: int | None) -> m.NumberSeries | None:
    ns = m.NumberSeries
    base = and_(ns.client_id == ctx.client_id, current(ns, ctx.today), ns.is_active.is_(True), ns.object == obj)
    # the entity's own series first, else a client-wide series
    row = ctx.db.scalar(select(ns).where(base, ns.legal_entity_rid == legal_entity_rid)) if legal_entity_rid else None
    return row or ctx.db.scalar(select(ns).where(base, ns.legal_entity_rid.is_(None)))


def format_number(prefix: str | None, padding: int | None, n: int) -> str:
    return f"{prefix or ''}{str(n).zfill(max(int(padding or 0), 1))}"


def preview(ctx: Ctx, series: m.NumberSeries) -> str:
    c = ctx.db.scalar(select(m.NumberCounter).where(m.NumberCounter.client_id == ctx.client_id, m.NumberCounter.series_rid == series.rid))
    return format_number(series.prefix, series.padding, c.next_number if c else (series.start_number or 1))


def allocate(ctx: Ctx, obj: str, legal_entity_rid: int | None) -> str:
    series = find_series(ctx, obj, legal_entity_rid)
    if series is None:
        raise HTTPException(422, f"No active number series for {obj} numbers"
                                 f"{' of legal entity ' + str(legal_entity_rid) if legal_entity_rid else ''}. Create one in Company setup first.")
    nc = m.NumberCounter
    counter = ctx.db.scalar(select(nc).where(nc.client_id == ctx.client_id, nc.series_rid == series.rid).with_for_update())
    if counter is None:
        counter = nc(client_id=ctx.client_id, series_rid=series.rid, next_number=series.start_number or 1)
        ctx.db.add(counter)
        ctx.db.flush()
        counter = ctx.db.scalar(select(nc).where(nc.id == counter.id).with_for_update())
    while True:
        value = format_number(series.prefix, series.padding, counter.next_number)
        counter.next_number += 1
        taken = ctx.db.scalar(select(m.NumberAllocation.id).where(m.NumberAllocation.client_id == ctx.client_id,
                                                                  m.NumberAllocation.object == obj, m.NumberAllocation.value == value))
        if taken is None:
            break
    ctx.db.add(m.NumberAllocation(client_id=ctx.client_id, object=obj, value=value, series_rid=series.rid, allocated_by=ctx.actor))
    ctx.db.flush()
    return value
