"""Data Redundancy Removal engine.

Every incoming record goes through four steps:
  1. VALIDATE   - reject malformed data (bad email, bad phone, empty name...)
  2. NORMALIZE  - make equivalent values look identical
                  (Ali.Khan+shop@gmail.com == alikhan@gmail.com, +92 300 1234567 == 03001234567)
  3. CLASSIFY   - compare against existing data and decide:
        unique          -> new, verified record  -> appended
        redundant       -> duplicate of existing -> rejected
        false_positive  -> looked like a duplicate, but verification proved it is a
                           different record     -> appended and flagged
        invalid         -> failed validation     -> rejected
  4. STORE      - only unique / verified records are written; every decision is
                  kept in an audit log.

The database also enforces UNIQUE(content_hash) and UNIQUE(email_norm), so even two
simultaneous requests can never insert the same record twice.
"""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

SAME_PHONE_NAME_SIMILARITY = 0.60   # same phone + names this similar  -> redundant
SIMILAR_NAME_SIMILARITY = 0.85      # names this similar in same city   -> flag for verification

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    phone        TEXT NOT NULL DEFAULT '',
    city         TEXT NOT NULL DEFAULT '',
    name_key     TEXT NOT NULL,
    email_norm   TEXT NOT NULL UNIQUE,
    phone_norm   TEXT NOT NULL DEFAULT '',
    city_norm    TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL UNIQUE,
    flagged      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_phone ON records(phone_norm);
CREATE INDEX IF NOT EXISTS idx_records_city  ON records(city_norm);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    input      TEXT NOT NULL,
    decision   TEXT NOT NULL,
    reason     TEXT NOT NULL,
    matched_id INTEGER,
    record_id  INTEGER
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- validate
def validate(raw):
    """Return (clean_record, errors)."""
    clean = {k: str(raw.get(k, "") or "").strip() for k in ("name", "email", "phone", "city")}
    errors = []
    if len(clean["name"]) < 2 or len(clean["name"]) > 80 or not re.search(r"[A-Za-z]", clean["name"]):
        errors.append("Name must be 2-80 characters and contain letters")
    if not EMAIL_RE.match(clean["email"]) or len(clean["email"]) > 120:
        errors.append("Email address is not valid")
    if clean["phone"]:
        digits = re.sub(r"\D", "", clean["phone"])
        if not 7 <= len(digits) <= 15:
            errors.append("Phone number must have 7-15 digits")
    if len(clean["city"]) > 60:
        errors.append("City is too long (max 60 characters)")
    return clean, errors


# --------------------------------------------------------------- normalize
def normalize_name(name):
    tokens = re.sub(r"[^a-z\s]", " ", name.lower()).split()
    return " ".join(sorted(tokens))      # "Khan Ali" == "Ali Khan"


def normalize_email(email):
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]       # drop +tags
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")   # gmail ignores dots
        domain = "gmail.com"
    return f"{local}@{domain}"


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("92") and len(digits) == 12:   # +92 300 1234567 -> 03001234567
        digits = "0" + digits[2:]
    return digits


def normalize(clean):
    n = {
        "name_key": normalize_name(clean["name"]),
        "email": normalize_email(clean["email"]),
        "phone": normalize_phone(clean["phone"]),
        "city": re.sub(r"\s+", " ", clean["city"].lower()).strip(),
    }
    n["hash"] = hashlib.sha256("|".join([n["name_key"], n["email"], n["phone"], n["city"]]).encode()).hexdigest()
    return n


def name_similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- classify
def classify(conn, n):
    """Compare a normalized record with the database. Uses indexed lookups only
    (hash, email, phone, city), so cost stays low even with many records."""
    row = conn.execute("SELECT id FROM records WHERE content_hash = ?", (n["hash"],)).fetchone()
    if row:
        return {"decision": "redundant", "reason": f"Exact duplicate of record #{row['id']}", "matched_id": row["id"]}

    row = conn.execute("SELECT id FROM records WHERE email_norm = ?", (n["email"],)).fetchone()
    if row:
        return {"decision": "redundant", "reason": f"Same email address as record #{row['id']}", "matched_id": row["id"]}

    shared_phone = None
    if n["phone"]:
        for row in conn.execute("SELECT id, name_key FROM records WHERE phone_norm = ?", (n["phone"],)):
            sim = name_similarity(n["name_key"], row["name_key"])
            if sim >= SAME_PHONE_NAME_SIMILARITY:
                return {"decision": "redundant", "matched_id": row["id"],
                        "reason": f"Same phone number and similar name ({sim:.0%}) as record #{row['id']}"}
            shared_phone = (row["id"], sim)

    similar_name = None
    if n["city"]:
        for row in conn.execute("SELECT id, name_key FROM records WHERE city_norm = ?", (n["city"],)):
            sim = name_similarity(n["name_key"], row["name_key"])
            if sim >= SIMILAR_NAME_SIMILARITY:
                similar_name = (row["id"], sim)
                break

    if shared_phone:
        rid, sim = shared_phone
        return {"decision": "false_positive", "matched_id": rid,
                "reason": f"Shares a phone number with record #{rid} but names differ ({sim:.0%} similar): verified as a different person"}
    if similar_name:
        rid, sim = similar_name
        return {"decision": "false_positive", "matched_id": rid,
                "reason": f"Name looks similar to record #{rid} ({sim:.0%}) but email and phone differ: verified as a different person"}
    return {"decision": "unique", "reason": "New unique record", "matched_id": None}


# ------------------------------------------------------------------- store
def _log(conn, raw, decision, reason, matched_id, record_id):
    conn.execute(
        "INSERT INTO audit_log (created_at, input, decision, reason, matched_id, record_id) VALUES (?,?,?,?,?,?)",
        (_now(), json.dumps(raw, ensure_ascii=False), decision, reason, matched_id, record_id),
    )
    conn.commit()
    return {"decision": decision, "reason": reason, "matched_id": matched_id, "record_id": record_id}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def process_record(conn, raw):
    """Run one record through validate -> normalize -> classify -> store."""
    clean, errors = validate(raw)
    if errors:
        return _log(conn, clean, "invalid", "; ".join(errors), None, None)

    n = normalize(clean)
    verdict = classify(conn, n)
    if verdict["decision"] == "redundant":
        return _log(conn, clean, "redundant", verdict["reason"], verdict["matched_id"], None)

    try:
        cur = conn.execute(
            """INSERT INTO records (name, email, phone, city, name_key, email_norm, phone_norm,
                                    city_norm, content_hash, flagged, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (clean["name"], clean["email"], clean["phone"], clean["city"], n["name_key"], n["email"],
             n["phone"], n["city"], n["hash"], 1 if verdict["decision"] == "false_positive" else 0, _now()),
        )
    except sqlite3.IntegrityError:
        # Another request inserted the same data a moment ago; the database constraint caught it.
        return _log(conn, clean, "redundant", "Blocked by database unique constraint", None, None)
    return _log(conn, clean, verdict["decision"], verdict["reason"], verdict["matched_id"], cur.lastrowid)


# ----------------------------------------------------------------- reports
def stats(conn):
    counts = {r["decision"]: r["c"] for r in conn.execute("SELECT decision, COUNT(*) c FROM audit_log GROUP BY decision")}
    submitted = sum(counts.values())
    stored = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    redundant = counts.get("redundant", 0)
    return {
        "submitted": submitted,
        "stored": stored,
        "unique": counts.get("unique", 0),
        "false_positive": counts.get("false_positive", 0),
        "redundant": redundant,
        "invalid": counts.get("invalid", 0),
        "duplicates_blocked_percent": round(100 * redundant / submitted, 1) if submitted else 0.0,
    }


def list_records(conn, limit=200):
    rows = conn.execute("SELECT id, name, email, phone, city, flagged, created_at FROM records ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def list_audit(conn, limit=200):
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["input"] = json.loads(d["input"])
        out.append(d)
    return out
