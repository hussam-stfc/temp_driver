# sqlite-web-test

Web UI for editing a SQLite config table, served via FastAPI.

## Stack
- **FastAPI** + plain `sqlite3` (synchronous, no ORM)
- **Tabulator 6** via CDN for the table UI
- **schema.json** drives column definitions — both backend and frontend read from it at startup/load

## Files
- `schema.json` — instance config: `title`, `db_path`, `extra_columns`
- `init_db.py` — run once to create/migrate the DB from schema
- `serve_db.py` — FastAPI app, run with uvicorn
- `index.html` — single-file UI, served statically or by FastAPI

## Schema
Fixed columns (always present): `ID` (PK, hidden in UI), `PV_NAME`, `row_order` (display order).  
Variable columns: defined in `schema.json` under `extra_columns`.  
Column names may start with digits or contain special characters — always double-quote them in SQL.

## API
- `GET /schema` — returns title and extra_columns
- `GET /rows` — all rows ordered by row_order
- `POST /rows` — insert new row (blank strings, appended to end)
- `PATCH /rows/{id}` — update a single cell `{ field, value }`
- `PUT /rows/reorder` — reorder via `{ ids: [...] }` list
- `DELETE /rows/{id}` — delete a row

## Notes
- Multiple deployments share identical `serve_db.py` and `index.html`; only `schema.json` and the db file differ
- WAL mode is enabled on init
- CORS is open (`*`) — tighten for production