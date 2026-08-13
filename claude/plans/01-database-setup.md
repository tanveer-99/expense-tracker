# Plan: Database Setup (Step 01)

## Context

`database/db.py` is currently a stub (just a comment describing what's needed). Spendly's auth (register/login) and expense-tracking features all depend on a working SQLite data layer, so this step implements it per `claude/specs/01-database-setup.md`: a `users` table, an `expenses` table, and three functions — `get_db()`, `init_db()`, `seed_db()` — wired into `app.py` startup. No routes change in this step; the placeholder routes in `app.py` stay as-is.

## Files to change

### `database/db.py` — implement all three functions

- **Module setup**: `import sqlite3`, `from pathlib import Path`, `from datetime import date`, `from werkzeug.security import generate_password_hash`. Compute `DB_PATH = Path(__file__).resolve().parent.parent / "expense_tracker.db"` so the DB always lands in the project root regardless of CWD (matches `.gitignore`, which already lists `expense_tracker.db`).

- **`get_db()`**: `sqlite3.connect(DB_PATH)`, set `conn.row_factory = sqlite3.Row`, run `conn.execute("PRAGMA foreign_keys = ON")`, return `conn`.

- **`init_db()`**: open a connection via `get_db()`, run two `CREATE TABLE IF NOT EXISTS` statements matching the spec exactly:
  - `users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))`
  - `expenses(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL, category TEXT NOT NULL, date TEXT NOT NULL, description TEXT, created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY (user_id) REFERENCES users(id))`
  
  Commit and close.

- **`seed_db()`**: open a connection, `SELECT COUNT(*) FROM users`; if `> 0`, close and return (idempotent). Otherwise:
  - Insert demo user (`Demo User`, `demo@spendly.com`, `generate_password_hash("demo123")`) via a parameterized `INSERT`, capture `cursor.lastrowid` as `user_id`.
  - Insert 8 sample expenses via parameterized `INSERT`s (loop or `executemany`), one row per fixed category (`Food, Transport, Bills, Health, Entertainment, Shopping, Other`) plus one extra (2nd Food entry) to reach 8. Use day-of-month values that are valid in every month (e.g. 1, 4, 7, 10, 13, 16, 19, 22) combined with `date.today().replace(day=...)` so dates always fall in the current month regardless of when this runs.
  - Commit and close.

  All SQL uses `?` placeholders — no string formatting anywhere.

### `app.py` — wire up startup

- Add `from database.db import init_db, seed_db` near the top (after the Flask import).
- Right after `app = Flask(__name__)`, add:
  ```python
  with app.app_context():
      init_db()
      seed_db()
  ```
- No other route changes.

## Out of scope

- `database/__init__.py` stays empty (just makes `database` a package).
- No new pip packages — only stdlib `sqlite3` and already-installed `werkzeug.security`.
- No ORM, no changes to any template or placeholder route.

## Verification

1. Delete any stray `expense_tracker.db` if present, then run `python app.py`. Confirm the file is created in the project root and the server starts without errors.
2. Inspect the DB (e.g. `python -c "from database.db import get_db; c=get_db(); print(c.execute('SELECT * FROM users').fetchall()); print(c.execute('SELECT * FROM expenses').fetchall())"`) — expect 1 user with a hashed (not plaintext) password, and 8 expenses covering all 7 categories.
3. Restart the app a second time and re-check row counts — must stay at 1 user / 8 expenses (no duplicate seeding).
4. Confirm constraint enforcement: attempt an insert with a duplicate email (expect `sqlite3.IntegrityError` on the UNIQUE constraint) and an expense insert with a bogus `user_id` (expect `sqlite3.IntegrityError` on the foreign key) via a quick ad-hoc `python -c` snippet using `get_db()`.
5. After approval, save this plan's content to `claude/plans/01-database-setup.md` per the project's documented workflow (`CLAUDE.md` → Workflow convention).
