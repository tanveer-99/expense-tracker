"""Tests for Step 7: Add Expense (.claude/specs/07-add-expense.md).

Scope, derived from the spec (not from reading app.py's / queries.py's logic):
  - GET and POST /expenses/add both require auth (redirect to /login when
    unauthenticated).
  - GET /expenses/add (authenticated) renders a form with amount, category,
    date, and description fields, a category <select> with exactly the 7
    fixed categories, and a POST form.
  - POST /expenses/add (authenticated) with valid data inserts a row into
    the expenses table and redirects to /profile.
  - POST with no description stores description as NULL.
  - POST re-renders the form (200, not a redirect) with an error message and
    the previously submitted values retained when: amount is missing, amount
    is zero, amount is non-numeric, category is not one of the 7 fixed
    values, or date is not a valid YYYY-MM-DD string.
  - database/queries.py::insert_expense inserts a row with the given fields,
    storing description=None as SQL NULL.

Note: tests/conftest.py defines its own `insert_expense` helper (a direct-DB
bypass used before this route existed). That is unrelated to
database.queries.insert_expense exercised here; this file always calls the
query-layer function via the `queries` module alias to avoid ambiguity.

Isolation strategy: shared per-session temp SQLite DB (see conftest.py);
every test uses its own unique user and only asserts on data scoped to that
user's user_id.
"""
import uuid

import database.queries as queries
from conftest import register_and_login
from database.db import create_user, get_db

FIXED_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


def _unique_email():
    return f"add_expense_{uuid.uuid4().hex}@example.com"


# --------------------------------------------------------------------------- #
# database/queries.py::insert_expense
# --------------------------------------------------------------------------- #

class TestInsertExpenseQuery:
    def test_insert_expense_creates_row(self):
        user_id = create_user("Query Test User", _unique_email(), "testpass123")
        queries.insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT amount, category, date, description FROM expenses WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "insert_expense must create a row queryable by user_id"
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_stores_none_description_as_null(self):
        user_id = create_user("Query Test User", _unique_email(), "testpass123")
        queries.insert_expense(user_id, 25.0, "Transport", "2026-03-21", None)

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT description FROM expenses WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row["description"] is None


# --------------------------------------------------------------------------- #
# Auth guard
# --------------------------------------------------------------------------- #

class TestAddExpenseAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        response = client.get("/expenses/add")
        assert response.status_code == 302, "Unauthenticated GET must redirect, not 200"
        assert "/login" in response.headers["Location"]

    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "2026-03-20"},
        )
        assert response.status_code == 302, "Unauthenticated POST must redirect, not process the form"
        assert "/login" in response.headers["Location"]


# --------------------------------------------------------------------------- #
# GET /expenses/add (authenticated)
# --------------------------------------------------------------------------- #

class TestAddExpenseGet:
    def test_get_authenticated_returns_200(self, client):
        register_and_login(client)
        response = client.get("/expenses/add")
        assert response.status_code == 200

    def test_get_renders_all_seven_categories(self, client):
        register_and_login(client)
        html = client.get("/expenses/add").data.decode()
        for cat in FIXED_CATEGORIES:
            assert f'value="{cat}"' in html, f"Category {cat!r} missing from the form"

    def test_get_renders_post_form(self, client):
        register_and_login(client)
        html = client.get("/expenses/add").data.decode()
        assert "<form" in html
        assert 'method="POST"' in html


# --------------------------------------------------------------------------- #
# POST /expenses/add — valid submissions
# --------------------------------------------------------------------------- #

class TestAddExpensePostValid:
    def test_valid_submission_redirects_to_profile(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "250", "category": "Food", "date": "2026-03-20", "description": "Coffee"},
        )
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_valid_submission_inserts_row(self, client):
        _, user_id = register_and_login(client)
        client.post(
            "/expenses/add",
            data={"amount": "250", "category": "Food", "date": "2026-03-20", "description": "Coffee"},
        )

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT amount, category, date, description FROM expenses WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row["amount"] == 250.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Coffee"

    def test_missing_description_saves_with_null(self, client):
        _, user_id = register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "40", "category": "Transport", "date": "2026-03-21"},
        )
        assert response.status_code == 302

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT description FROM expenses WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row["description"] is None


# --------------------------------------------------------------------------- #
# POST /expenses/add — validation failures
# --------------------------------------------------------------------------- #

class TestAddExpensePostValidation:
    def test_missing_amount_rerenders_with_error(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "", "category": "Food", "date": "2026-03-20"},
        )
        assert response.status_code == 200
        assert "valid amount" in response.data.decode().lower()

    def test_zero_amount_rerenders_with_error(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "0", "category": "Food", "date": "2026-03-20"},
        )
        assert response.status_code == 200
        assert "greater than 0" in response.data.decode().lower()

    def test_non_numeric_amount_rerenders_with_error(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "abc", "category": "Food", "date": "2026-03-20"},
        )
        assert response.status_code == 200
        assert "valid amount" in response.data.decode().lower()

    def test_invalid_category_rerenders_with_error(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Not-A-Category", "date": "2026-03-20"},
        )
        assert response.status_code == 200
        assert "valid category" in response.data.decode().lower()

    def test_invalid_date_rerenders_with_error(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "not-a-date"},
        )
        assert response.status_code == 200
        assert "valid date" in response.data.decode().lower()

    def test_validation_error_retains_submitted_values(self, client):
        register_and_login(client)
        response = client.post(
            "/expenses/add",
            data={"amount": "", "category": "Bills", "date": "2026-03-20", "description": "Rent"},
        )
        html = response.data.decode()
        assert 'value="2026-03-20"' in html
        assert 'value="Rent"' in html
        assert 'value="Bills" selected' in html
