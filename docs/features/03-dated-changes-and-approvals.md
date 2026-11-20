# 03 Dated changes, backdating and approvals

- Every change has an `effective_from` (default today) and a `change_reason`.
- `effective_from` today or later: applied at once. Same day as the current version -> corrected in place; later -> new version.
- `effective_from` before today: **202 Accepted**, saved as a pending change (secrets stay encrypted in it).
  - `GET /api/setup/changes?status=pending|approved|rejected|all`
  - `POST /api/setup/changes/{id}/approve` or `/reject` with an optional note.
  - Approvers come from the approval workflow with request type `backdated_change` (default: master_admin or hr, one step).
    The requester can never approve their own change (403).
- Ending a record on yesterday or later applies directly; ending it further back needs approval.
- A change from a date the record does not cover (before it starts, after it ended) is refused at once (422).
