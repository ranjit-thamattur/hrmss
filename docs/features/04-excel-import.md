# 04 Excel import

1. `GET {path}/template.xlsx` - a "Data" sheet with the columns and a "How to" sheet explaining each one. References are entered by
   code (`state_code`, `legal_entity_code`, `location_codes` separated by `;`).
2. `POST {path}/import` (multipart: `file`, `dry_run=true|false`).
3. Every row goes through the same create as the API. Bad rows are rejected with the reason; good rows are imported.
   The report always reconciles: `imported + rejected = total` (`counts_reconcile: true`). Duplicate codes inside the file are rejected.
4. `dry_run=true` checks everything and saves nothing.

Sample with good and bad rows: `postman/samples/departments-import.xlsx`.
