"""REST endpoints for every catalogue entity, generated from the specs (Company Setup: /api/setup/...,
HR records: /api/hr/...). Plus: the client, pending (backdated) changes, the audit log and a few
entity-specific reads.

Per entity:
  GET    {path}                      list (as_of, include_inactive, q, page, size, any field as a filter)
  POST   {path}                      create                          201
  GET    {path}/template.xlsx        Excel template
  POST   {path}/import               Excel import (file, dry_run)
  GET    {path}/{rid}                one record (as_of)
  GET    {path}/{rid}/history        all versions
  PUT    {path}/{rid}                change from effective_from      200, or 202 when backdated (waits for approval)
  POST   {path}/{rid}/deactivate     deactivate from effective_from  200 / 202
  POST   {path}/{rid}/reactivate     reactivate                      200 / 202
  POST   {path}/{rid}/end            end on end_date                 200 / 202
  DELETE {path}/{rid}                always refused (405): deactivate, never delete

Note: this module deliberately has no `from __future__ import annotations`: the request body types are
built at run time from the catalogue and FastAPI must see the real classes.
"""
import base64
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import models as m
from ..core import access, engine, importer, numbering, storage
from ..core.audit import jsonable
from ..core.context import Ctx, current
from ..core.records import at, must_exist
from ..core.schemas import EndRecord, StatusChange, change_schema, create_schema, split_change, split_create
from ..core.specs import SPECS, SPECS_LIST, Spec
from ..deps import C

RESERVED = {"as_of", "include_inactive", "q", "page", "size", "client_id"}


def _result(ctx: Ctx, spec: Spec, row: Any, pending: Any, response: Response, extra: Optional[dict] = None) -> dict:
    ctx.db.commit()
    if pending is not None:
        response.status_code = 202
        return {"message": "Backdated: saved for approval. It applies once approved (see /api/setup/changes).",
                "pending_change": engine.pending_out(pending)}
    out = engine.get_record(ctx, spec, row.rid, row.valid_from if row.valid_from > ctx.today else None) if row is not None else {}
    return {**out, **(extra or {})}


def build_router(spec: Spec) -> APIRouter:
    r = APIRouter(prefix=spec.path, tags=[f"{spec.number:02d} {spec.title}"])
    Create = create_schema(spec.key)
    Change = change_schema(spec.key)

    # ---- entity-specific routes first (fixed paths must come before /{rid})
    if spec.key == "policies":
        @r.get("/resolve", summary="Policies that apply to an entity / location / department / grade")
        def resolve(ctx: C, legal_entity_rid: Optional[int] = None, location_rid: Optional[int] = None, department_rid: Optional[int] = None,
                    grade_rid: Optional[int] = None, as_of: Optional[date] = None) -> list:
            want = {"legal_entity_rids": legal_entity_rid, "location_rids": location_rid, "department_rids": department_rid, "grade_rids": grade_rid}
            items = engine.list_records(ctx, spec, on=as_of, size=500)["items"]
            out = []
            for p in items:
                ap = p.get("applies_to") or {}
                if all(not ap.get(k) or v is None or v in ap[k] for k, v in want.items()):
                    out.append(p)
            return out

    if spec.key == "documents":
        @r.post("/upload", status_code=201, summary="Upload a document file for an owner record")
        async def upload(ctx: C, response: Response, owner_type: str = Form(...), owner_rid: int = Form(...), doc_type: str = Form(...),
                         valid_from: Optional[date] = Form(None), valid_to: Optional[date] = Form(None), file: UploadFile = File(...)) -> dict:
            data = await file.read()
            return _store_document(ctx, response, owner_type, owner_rid, doc_type, valid_from, valid_to, file.filename or "file", file.content_type, data)

        @r.post("/upload-base64", status_code=201, summary="Upload a document as base64 (for API clients and Postman)")
        def upload_b64(ctx: C, response: Response, body: DocumentB64) -> dict:
            try:
                data = base64.b64decode(body.content_base64, validate=True)
            except ValueError as e:
                raise HTTPException(422, "content_base64 is not valid base64.") from e
            return _store_document(ctx, response, body.owner_type, body.owner_rid, body.doc_type, body.valid_from, body.valid_to,
                                   body.file_name, body.content_type, data)

        @r.get("/{rid}/file", summary="Download the document file")
        def file_(rid: int, ctx: C) -> RawResponse:
            rec = engine.get_record(ctx, spec, rid)
            owner = SPECS[rec["owner_type"]]
            engine.get_record(ctx, owner, rec["owner_rid"])  # access follows the owner record's scope
            return RawResponse(storage.read(rec["storage_key"]), media_type=rec["content_type"] or "application/octet-stream",
                               headers={"Content-Disposition": f'attachment; filename="{rec["file_name"]}"'})

    if spec.key == "locations":
        @r.get("/{rid}/holidays", summary="Holidays that apply at a location in a year")
        def holidays(rid: int, ctx: C, year: Optional[int] = None) -> dict:
            engine.get_record(ctx, spec, rid)
            year = year or ctx.today.year
            hc = m.HolidayCalendar
            access.require(ctx, "holiday-calendars", "view")
            cals = [c for c in ctx.db.scalars(select(hc).where(hc.client_id == ctx.client_id, hc.year == year, hc.is_active.is_(True),
                                                               current(hc, ctx.today))) if rid in (c.location_rids or [])]
            hol = sorted(((h["date"], h["name"], h.get("kind", "fixed"), c.code) for c in cals for h in (c.holidays or [])))
            return {"location_rid": rid, "year": year, "calendars": [c.code for c in cals],
                    "holidays": [{"date": d, "name": n, "kind": k, "calendar": cc} for d, n, k, cc in hol]}

    if spec.key == "number-series":
        @r.get("/{rid}/preview", summary="The next number this series would give (nothing is allocated)")
        def preview(rid: int, ctx: C) -> dict:
            engine.get_record(ctx, spec, rid)
            row = at(ctx, spec, rid, ctx.today)
            if row is None:
                raise HTTPException(404, "No version in force today.")
            return {"rid": rid, "next": numbering.preview(ctx, row)}

    # ---- generic routes
    @r.get("", summary=f"List {spec.title.lower()} records")
    def list_(request: Request, ctx: C, as_of: Optional[date] = None, include_inactive: bool = False, q: Optional[str] = None,
              page: int = 1, size: int = 50) -> dict:
        filters = {k: v for k, v in request.query_params.items() if k not in RESERVED}
        return engine.list_records(ctx, spec, on=as_of, include_inactive=include_inactive, filters=filters, q=q, page=page, size=size)

    @r.get("/template.xlsx", summary="Excel template for import")
    def template(ctx: C) -> RawResponse:
        access.require(ctx, spec.key, "import")
        return RawResponse(importer.template(spec), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           headers={"Content-Disposition": f'attachment; filename="{spec.key}-template.xlsx"'})

    if spec.creatable:
        @r.post("", status_code=201, summary=f"Create a {spec.title.lower()}")
        def create(body: Create, ctx: C, response: Response) -> dict:  # type: ignore[valid-type]
            data, vf, vt, reason = split_create(body.model_dump())  # type: ignore[attr-defined]
            row = engine.create(ctx, spec, data, vf, vt, reason)
            response.status_code = 201
            return _result(ctx, spec, row, None, response)

        @r.post("/import", summary="Import from Excel: row-by-row report; imported + rejected = rows in the file")
        async def import_(ctx: C, file: UploadFile = File(...), dry_run: bool = Form(False)) -> dict:
            report = importer.import_file(ctx, spec, await file.read(), dry_run)
            if dry_run:
                ctx.db.rollback()
            else:
                ctx.db.commit()
            return jsonable(report)

    @r.get("/{rid}", summary=f"One {spec.title.lower()} (as_of a date)")
    def get_(rid: int, ctx: C, as_of: Optional[date] = None) -> dict:
        return engine.get_record(ctx, spec, rid, as_of)

    @r.get("/{rid}/history", summary="All versions, oldest first")
    def history(rid: int, ctx: C) -> list:
        return engine.history(ctx, spec, rid)

    @r.put("/{rid}", summary="Change from effective_from (default today; earlier = needs approval)")
    def change(rid: int, body: Change, ctx: C, response: Response) -> dict:  # type: ignore[valid-type]
        data, eff, reason = split_change(body.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
        row, pending = engine.change(ctx, spec, rid, data, eff, reason)
        return _result(ctx, spec, row, pending, response)

    @r.post("/{rid}/deactivate", summary="Deactivate (records are never deleted)")
    def deactivate(rid: int, body: StatusChange, ctx: C, response: Response) -> dict:
        uses = engine.in_use(ctx, spec, rid)
        row, pending = engine.set_active(ctx, spec, rid, False, body.effective_from, body.change_reason)
        return _result(ctx, spec, row, pending, response, {"still_referenced_by": uses})

    @r.post("/{rid}/reactivate", summary="Reactivate (its references must be active)")
    def reactivate(rid: int, body: StatusChange, ctx: C, response: Response) -> dict:
        row, pending = engine.set_active(ctx, spec, rid, True, body.effective_from, body.change_reason)
        return _result(ctx, spec, row, pending, response)

    @r.post("/{rid}/end", summary="End the record on end_date (e.g. a link or a job)")
    def end_(rid: int, body: EndRecord, ctx: C, response: Response) -> dict:
        row, pending = engine.end(ctx, spec, rid, body.end_date, body.change_reason)
        if pending is not None:
            return _result(ctx, spec, None, pending, response)
        ctx.db.commit()
        return {"rid": rid, "valid_to": row.valid_to, "message": f"Ends on {row.valid_to}."}

    @r.delete("/{rid}", status_code=405, summary="Not allowed: deactivate instead")
    def delete_(rid: int, ctx: C) -> dict:
        must_exist(ctx, spec, rid)
        raise HTTPException(405, f"{spec.title} records are never deleted. Use POST {spec.path}/{rid}/deactivate.")

    return r


class DocumentB64(BaseModel):
    owner_type: str
    owner_rid: int
    doc_type: str
    file_name: str
    content_type: Optional[str] = "application/octet-stream"
    content_base64: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


MAX_FILE = 15 * 1024 * 1024


def _store_document(ctx: Ctx, response: Response, owner_type: str, owner_rid: int, doc_type: str, valid_from: Optional[date],
                    valid_to: Optional[date], file_name: str, content_type: Optional[str], data: bytes) -> dict:
    spec = SPECS["documents"]
    if owner_type not in spec.f("owner_type").choices:
        raise HTTPException(422, f"owner_type must be one of {', '.join(spec.f('owner_type').choices)}.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    if len(data) > MAX_FILE:
        raise HTTPException(413, "The file is larger than 15 MB.")
    engine.get_record(ctx, SPECS[owner_type], owner_rid)  # the owner must exist and be visible to this user
    key = storage.save(ctx.client_id, file_name, data, content_type)
    row = engine.create(ctx, spec, {"doc_type": doc_type, "owner_type": owner_type, "owner_rid": owner_rid}, valid_from, valid_to, "Upload",
                        system_values={"file_name": file_name[:255], "content_type": content_type, "size_bytes": len(data), "storage_key": key})
    response.status_code = 201
    return _result(ctx, spec, row, None, response)


# ---------------------------------------------------------------- client, pending changes, audit
extra = APIRouter(tags=["01 Client, approvals and audit"])


@extra.get("/api/setup/client", summary="This client (from its YAML file; change the YAML and redeploy to update)")
def client(ctx: C) -> dict:
    access.require(ctx, "client", "view")
    c = ctx.db.get(m.Client, ctx.client_id)
    return {"id": c.id, "code": c.code, "name": c.name, "country": c.country, "default_currency": c.default_currency,
            "financial_year_start_month": c.fy_start_month, "aws_account_id": c.aws_account_id, "aws_region": c.aws_region,
            "domain": c.domain, "database_name": c.database_name, "settings": c.settings, "updated_at": c.updated_at}


@extra.get("/api/setup/changes", summary="Backdated changes waiting for approval (status=pending|approved|rejected|all)")
def changes(ctx: C, status: str = "pending") -> list:
    access.require(ctx, "changes", "view")
    q = select(m.PendingChange).where(m.PendingChange.client_id == ctx.client_id).order_by(m.PendingChange.requested_at.desc())
    if status != "all":
        q = q.where(m.PendingChange.status == status)
    return [engine.pending_out(p) for p in ctx.db.scalars(q.limit(500))]


class Decision(BaseModel):
    note: Optional[str] = Field(None, max_length=300)


@extra.post("/api/setup/changes/{change_id}/approve", summary="Approve (not your own request); applies it after the last step")
def approve(change_id: int, body: Decision, ctx: C) -> dict:
    pc = engine.decide(ctx, change_id, True, body.note)
    ctx.db.commit()
    return engine.pending_out(pc)


@extra.post("/api/setup/changes/{change_id}/reject", summary="Reject")
def reject(change_id: int, body: Decision, ctx: C) -> dict:
    pc = engine.decide(ctx, change_id, False, body.note)
    ctx.db.commit()
    return engine.pending_out(pc)


@extra.get("/api/setup/audit", summary="Audit log (append-only; sensitive values masked)")
def audit(ctx: C, resource: Optional[str] = None, rid: Optional[int] = None, actor: Optional[str] = None, page: int = 1, size: int = 100) -> dict:
    access.require(ctx, "audit", "view")
    a = m.AuditLog
    q = select(a).where(a.client_id == ctx.client_id)
    if resource:
        q = q.where(a.resource == resource)
    if rid is not None:
        q = q.where(a.rid == rid)
    if actor:
        q = q.where(a.actor == actor.lower())
    size = max(1, min(size, 500))
    rows = ctx.db.scalars(q.order_by(a.id.desc()).offset((max(page, 1) - 1) * size).limit(size))
    return {"page": page, "size": size, "items": [{"id": x.id, "at": x.at, "actor": x.actor, "action": x.action, "resource": x.resource, "rid": x.rid,
                                                   "before": x.before, "after": x.after, "reason": x.reason, "approved_by": x.approved_by} for x in rows]}


routers = [build_router(s) for s in SPECS_LIST]
