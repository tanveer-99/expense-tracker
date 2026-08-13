# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Spendly — a Flask-based personal expense tracker, built incrementally as a series of guided steps (auth, profile, expense CRUD, etc.). Many routes in `app.py` are intentionally unimplemented placeholders ("Step 3", "Step 7", ...) — do not implement a placeholder route unless the current task specifically asks for it.

## Commands

- Run the app: `python app.py` (Flask dev server, debug mode, port 5001)
- Install deps: `pip install -r requirements.txt` (project uses a `venv/` — activate it first)
- Run tests: `pytest` (test infra — `pytest`, `pytest-flask` — is installed but no test files exist yet)

## Architecture

- `app.py` — single-file Flask app; all routes live here directly (no blueprints).
- `templates/` — Jinja2 templates. `base.html` defines the shared layout (nav/footer) via `{% block content %}`; page templates `{% extend "base.html" %}`. Follow this pattern for new pages rather than duplicating layout markup.
- `static/css/style.css`, `static/js/main.js` — single global stylesheet/script, no bundler or framework. JS is vanilla only.
- `database/` — the data-access layer. `db.py` is built out incrementally per spec (see Workflow below); when implemented it exposes `get_db()`, `init_db()`, `seed_db()` backed by SQLite, called from `app.py` inside `app.app_context()` at startup.

### Data layer rules (apply whenever touching `database/db.py` or SQL)

- No ORM — raw `sqlite3` only.
- Parameterized queries only; never build SQL with string formatting.
- Every connection must set `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`.
- Passwords are hashed with `werkzeug.security.generate_password_hash`.
- `seed_db()` must be idempotent (check for existing data before inserting).

## Workflow convention

This repo is developed step-by-step, each step driven by a spec doc:

1. A spec for the step is saved to `.claude/specs/NN-<step-name>.md`.
2. Plan mode is used to turn the spec (plus the relevant existing files) into an implementation plan saved to `.claude/plans/NN-<step-name>.md`.
3. The plan is implemented, then validated against the spec doc before committing.

When asked to work on a numbered step, check `.claude/specs/` and `.claude/plans/` first for the authoritative requirements rather than guessing scope.
