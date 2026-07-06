import sqlite3, json

with open("schema.json") as f:
    schema = json.load(f)

DB_PATH = schema["db_path"]
extra   = schema["extra_columns"]

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("""
    CREATE TABLE IF NOT EXISTS config (
        ID        INTEGER PRIMARY KEY AUTOINCREMENT,
        PV_NAME   TEXT    DEFAULT '',
        row_order INTEGER DEFAULT 0
    )
""")
for col in extra:
    try:
        conn.execute(f'ALTER TABLE config ADD COLUMN "{col}" TEXT DEFAULT \'\'')
    except Exception:
        pass  # already exists

conn.commit()
conn.close()
print(f"Database initialised: {DB_PATH}")