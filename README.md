# CodeAlpha_DataRedundancyRemoval

**Data Redundancy Removal System** for the CodeAlpha Cloud Computing Internship (Task 1).

The system checks every new record before it reaches the database. Duplicates are rejected,
look-alike records are verified, and only unique or verified entries are appended.

## How it works
Every record goes through four steps (`dedup.py`):

| Step | What happens |
|------|--------------|
| 1. Validate | Rejects bad email, bad phone, empty or numeric-only name |
| 2. Normalize | `Ali.Khan+shop@gmail.com` = `alikhan@gmail.com`, `+92 300 1234567` = `03001234567`, `Khan Ali` = `Ali Khan` |
| 3. Classify | Compares with existing data using indexed lookups (hash, email, phone, city) |
| 4. Store | Appends only unique and verified records, and logs every decision |

### Classification
| Decision | Meaning | Stored? |
|----------|---------|---------|
| `unique` | New record | Yes |
| `redundant` | Exact duplicate, same email, or same phone with a similar name | No |
| `false_positive` | Looked like a duplicate (shared phone or similar name) but verification proved it is a different person | Yes, flagged |
| `invalid` | Failed validation | No |

### Accuracy and efficiency
- A SHA-256 content hash and the normalized email are `UNIQUE` in the database, so duplicates are blocked even if two requests arrive at the same time.
- Only indexed columns are searched, so cost stays low as data grows.
- Every decision is saved in an audit log (the "Decision log" tab).

## Run locally
Windows: double-click `run.bat` (tests: `test.bat`). Or from a terminal inside this folder:
```bash
python -m pip install -r requirements.txt
python app.py
```
Open http://localhost:5001, click **Run sample data**, and watch the decisions.

## Tests
```bash
python -m unittest tests/test_dedup.py -v
```

## API
| Method | URL | Purpose |
|--------|-----|---------|
| POST | `/api/records` | Add one record. 201 stored, 409 redundant, 422 invalid |
| POST | `/api/records/bulk` | `{"csv": "..."}` or `{"records": [...]}` |
| GET | `/api/records` | Stored records |
| GET | `/api/audit` | Decision log |
| GET | `/api/stats` | Counters |

Example:
```bash
curl -X POST http://localhost:5001/api/records -H "Content-Type: application/json" \
  -d '{"name":"Ali Khan","email":"ali@example.com","phone":"03001234567","city":"Karachi"}'
```

## Deploy to the cloud
Host the Flask app on a cloud platform such as PythonAnywhere (free plan keeps files on disk, which
suits SQLite) or Render. Set `DATABASE_PATH` to change where the database file is stored.
On Render's free plan the disk is erased on restart, so use a persistent disk or a managed
database for permanent data.

## Tech stack
Python, Flask, SQLite, HTML/CSS/JavaScript
