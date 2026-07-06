# Run FastAPI server

pip install -r requirements.txt
python init_db.py        # once, creates config.db
uvicorn main:app --host 0.0.0.0 --port 8000

# Configuration UI

Open index.html and set the API constant at the top to the
FastAPI machine's address, e.g. http://192.168.1.50:8000.

# From Driver

import httpx
rows = httpx.get("http://192.168.1.50:8000/rows").json()