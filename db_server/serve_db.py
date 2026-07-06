import sqlite3, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

with open("schema.json") as f:
    _schema = json.load(f)

DB_PATH  = _schema["db_path"]
EXTRA    = _schema["extra_columns"]
EDITABLE = {"PV_NAME"} | set(EXTRA)

def q(col):
    """Double-quote a column name so SQLite accepts any identifier."""
    return f'"{col}"'

SEL_COLS = ", ".join([q("ID"), q("PV_NAME")] + [q(c) for c in EXTRA])
SELECT   = f"SELECT {SEL_COLS} FROM config"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/schema")
def get_schema():
    return {"title": _schema.get("title", "Config"), "extra_columns": EXTRA}

@app.get("/rows")
def get_rows():
    conn = db()
    rows = conn.execute(f"{SELECT} ORDER BY row_order").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/rows")
def add_row():
    conn = db()
    cur = conn.execute("SELECT COALESCE(MAX(row_order), -1) + 1 FROM config")
    next_order = cur.fetchone()[0]
    all_cols = ["PV_NAME"] + EXTRA
    cur = conn.execute(
        f"INSERT INTO config ({', '.join(q(c) for c in all_cols)}, row_order) "
        f"VALUES ({', '.join(['?'] * len(all_cols))}, ?)",
        [""] * len(all_cols) + [next_order]
    )
    conn.commit()
    row = conn.execute(f"{SELECT} WHERE ID = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

class CellUpdate(BaseModel):
    field: str
    value: str

@app.patch("/rows/{row_id}")
def update_cell(row_id: int, update: CellUpdate):
    if update.field not in EDITABLE:
        raise HTTPException(400, "Invalid or non-editable field")
    conn = db()
    conn.execute(f"UPDATE config SET {q(update.field)} = ? WHERE ID = ?", (update.value, row_id))
    conn.commit()
    conn.close()
    return {"ok": True}

class ReorderRequest(BaseModel):
    ids: List[int]

@app.put("/rows/reorder")
def reorder_rows(req: ReorderRequest):
    conn = db()
    for i, row_id in enumerate(req.ids):
        conn.execute("UPDATE config SET row_order = ? WHERE ID = ?", (i, row_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/rows/{row_id}")
def delete_row(row_id: int):
    conn = db()
    conn.execute("DELETE FROM config WHERE ID = ?", (row_id,))
    conn.commit()
    conn.close()
    return {"ok": True}