import csv
import io
import os

from flask import Flask, jsonify, render_template, request

import dedup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "data", "redundancy.db"))
MAX_BULK_ROWS = 1000

app = Flask(__name__)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
dedup.connect(DB_PATH).close()  # create tables on first run


def db():
    return dedup.connect(DB_PATH)


STATUS = {"unique": 201, "false_positive": 201, "redundant": 409, "invalid": 422}


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/records")
def add_record():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Send a JSON object with name, email, phone, city."), 400
    conn = db()
    try:
        result = dedup.process_record(conn, payload)
    finally:
        conn.close()
    return jsonify(result), STATUS[result["decision"]]


@app.post("/api/records/bulk")
def add_bulk():
    payload = request.get_json(silent=True) or {}
    if isinstance(payload.get("csv"), str):
        reader = csv.DictReader(io.StringIO(payload["csv"]))
        rows = [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]
    elif isinstance(payload.get("records"), list):
        rows = [r for r in payload["records"] if isinstance(r, dict)]
    else:
        return jsonify(error='Send {"csv": "..."} or {"records": [...]}.'), 400
    if not rows:
        return jsonify(error="No rows found."), 400
    if len(rows) > MAX_BULK_ROWS:
        return jsonify(error=f"Too many rows (max {MAX_BULK_ROWS})."), 400

    conn = db()
    try:
        results = [dedup.process_record(conn, row) for row in rows]
        summary = {}
        for r in results:
            summary[r["decision"]] = summary.get(r["decision"], 0) + 1
    finally:
        conn.close()
    return jsonify(summary=summary, total=len(results))


@app.get("/api/records")
def records():
    conn = db()
    try:
        return jsonify(dedup.list_records(conn))
    finally:
        conn.close()


@app.get("/api/audit")
def audit():
    conn = db()
    try:
        return jsonify(dedup.list_audit(conn))
    finally:
        conn.close()


@app.get("/api/stats")
def get_stats():
    conn = db()
    try:
        return jsonify(dedup.stats(conn))
    finally:
        conn.close()


@app.get("/api/sample")
def sample():
    with open(os.path.join(BASE_DIR, "sample_data.csv"), encoding="utf-8") as f:
        return jsonify(csv=f.read())


@app.get("/api/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
