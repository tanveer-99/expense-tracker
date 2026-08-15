"""Shared pytest fixtures/helpers for the Spendly test suite.

Why the DB_PATH dance below:
`database/db.py` has no env var or config knob to redirect `get_db()` at a
different SQLite file — it always connects to a hardcoded
`DB_PATH = <repo>/expense_tracker.db`. `app.py` also calls `init_db()` and
`seed_db()` against that path *at import time* (inside
`with app.app_context(): init_db(); seed_db()`), before any pytest fixture
gets a chance to run. So the only way to keep tests from reading/writing the
real dev DB is to monkeypatch `database.db.DB_PATH` to a throwaway temp file
*before* `app` is imported anywhere. This module is guaranteed by pytest to
be imported before any test module in this directory, so we do the patch
here, once, for the whole test session.

Because there's no per-test DB reset knob, isolation between tests is
achieved by giving every test its own unique user (unique email) and only
ever asserting on data scoped to `WHERE user_id = ?` for that user. Demo/seed
data and data from other tests living in the same on-disk SQLite file is
irrelevant as long as tests never assert on unscoped/global data.
"""
import tempfile
import uuid
from pathlib import Path

import pytest

import database.db as db_module

_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"spendly_test_{uuid.uuid4().hex}.db"
db_module.DB_PATH = _TEST_DB_PATH

# Import the Flask app AFTER patching DB_PATH, so the init_db()/seed_db()
# calls app.py makes at import time land on the isolated test DB.
from app import app as flask_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db():
    yield
    try:
        _TEST_DB_PATH.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture
def app():
    flask_app.config.update({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def register_user(client, name="Test User", email=None, password="testpass123"):
    """Register a brand-new user with a unique email (unless given one).

    Returns (email, password) so the caller can log in.
    """
    if email is None:
        email = f"user_{uuid.uuid4().hex}@example.com"
    client.post(
        "/register",
        data={
            "name": name,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    return email, password


def login_user(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def register_and_login(client, name="Test User"):
    """Register + log in a fresh, unique user. Returns (email, user_id)."""
    email, password = register_user(client, name=name)
    login_user(client, email, password)
    return email, get_user_id(email)


def get_user_id(email):
    conn = db_module.get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def insert_expense(user_id, amount, category, date_str, description="Test expense"):
    """Insert a single expense row directly (bypassing any HTTP route, since
    expense-creation routes are unimplemented placeholders as of this step).
    """
    conn = db_module.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date_str, description),
        )
        conn.commit()
    finally:
        conn.close()
