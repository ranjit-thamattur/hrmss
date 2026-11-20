# 02 Company Setup

Every entity in the catalogue gets the same endpoints (`{path}` = `/api/setup/<entity>` or `/api/hr/<entity>`, see the data dictionary):

| Call | Result |
|---|---|
| `GET {path}?as_of=&include_inactive=&q=&page=&size=&<field>=` | list in your data scope |
| `POST {path}` | create -> 201 |
| `GET {path}/{rid}?as_of=` | one record as on a date |
| `GET {path}/{rid}/history` | all versions |
| `PUT {path}/{rid}` with `effective_from` | change from a date -> 200, or 202 when backdated |
| `POST {path}/{rid}/deactivate`, `/reactivate` | with `effective_from`; deactivate shows `still_referenced_by` |
| `POST {path}/{rid}/end` with `end_date` | end a link or a job |
| `DELETE {path}/{rid}` | always 405 |
| `GET {path}/template.xlsx`, `POST {path}/import` | Excel (see 04) |

Extra reads: `GET /api/setup/client` (from client.yaml), `GET /api/setup/locations/{rid}/holidays?year=`,
`GET /api/setup/number-series/{rid}/preview`, `GET /api/setup/policies/resolve?legal_entity_rid=&location_rid=&department_rid=&grade_rid=`,
`POST /api/setup/documents/upload` (multipart) or `/upload-base64`, `GET /api/setup/documents/{rid}/file`.

Checks done on every write: unique code per client (not case-sensitive); references exist and are active on the start date;
no overlapping active links (entity-location, department-entity, statutory registration per type and state, one calendar per location
per year, one payroll period per entity); entity hooks (PAN/GSTIN formats, department tree has no loops, shift times, weekly-off days,
approval steps, permissions use known resources and actions).
