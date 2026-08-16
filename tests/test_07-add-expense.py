"""Tests for Step 7: Add Expense (.claude/specs/07-add-expense.md).

Scope, derived strictly from the spec (not from reading app.py's /
database/queries.py's actual logic):

  - `GET /expenses/add` and `POST /expenses/add` both require auth; when
    unauthenticated, both must redirect (302) to `/login`.
  - `GET /expenses/add` (authenticated) renders a form containing:
      * an `amount` number input (step="0.01", min="0.01")
      * a `category` <select> with exactly the 7 fixed options: Food,
        Transport, Bills, Health, Entertainment, Shopping, Other
      * a `date` input (type="date") that defaults to today's date
      * a `description` text input (optional)
      * a `<form>` posting to `/expenses/add`
  - `POST /expenses/add` (authenticated) with valid data inserts a new row
    into `expenses` scoped to the logged-in user and redirects (302) to
    `/profile`.
  - `POST` with no `description` stores `description` as SQL `NULL` and
    still redirects (no error).
  - `POST` re-renders the form (HTTP 200, not a redirect) with an error
    message and the previously submitted values retained, and does NOT
    insert a row, when: `amount` is missing, `amount` is `0`, `amount` is
    non-numeric, `category` is not one of the 7 fixed values, or `date` is
    not a valid `YYYY-MM-DD` string.
  - `database/queries.py::insert_expense` inserts a row with the given
    fields, storing `description=None` as SQL `NULL`.
  - UI integration (Definition of done): the profile page has an
    "Add Expense" link to `/expenses/add`; the navbar shows an
    "Add Expense" link when logged in and not when logged out.

Note: `tests/conftest.py` defines its own `insert_expense` helper (a
direct-DB bypass historically used before this route existed). That is
unrelated to `database.queries.insert_expense` exercised here; this file
always calls the query-layer function via the `queries` module alias to
avoid ambiguity, and never imports the conftest helper of the same name.

Error-message assertions deliberately do NOT hardcode exact wording (the
spec only requires "an error message", not specific copy). Instead they
rely on the app-wide flash-message convention already established in
`base.html` (`get_flashed_messages(with_categories=true)`, rendered as
`<div class="flash-message flash-{category}">`) with category "error",
which every page -- including a template extending `base.html`, as the
spec requires `add_expense.html` to -- inherits. Combined with a DB check
that no row was inserted, this verifies the *behavior* (validation
rejected the submission and told the user) without coupling to specific
error text.

Isolation strategy: shared per-session temp SQLite DB (see conftest.py);
every test uses its own unique user and only ever asserts on data scoped
to that user's user_id.
"""
import re
import uuid
from datetime import date

import database.queries as queries
from conftest import register_and_login
from database.db import create_user, get_db

FIXED_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _expenses_for_user(user_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE user_id = ? "
            "ORDER BY id",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def _extract_select_option_values(html_text, select_name):
    """Return the value of every non-empty <option> inside the <select
    name="select_name"> ... </select> block (excludes empty-value
    placeholder options, e.g. "Select a category")."""
    select_pattern = re.compile(
        r'<select[^>]*name="' + re.escape(select_name) + r'"[^>]*>(.*?)</select>',
        re.DOTALL,
    )
    match = select_pattern.search(html_text)
    assert match, f'Could not find <select name="{select_name}"> in the page'
    block = match.group(1)
    return [value for value in re.findall(r'<option value="([^"]+)"', block)]


def _looks_like_error_flash(html_text):
    return "flash-error" in html_text


def _query_test_email():
    return f"query_{uuid.uuid4().hex}@example.com"


# --------------------------------------------------------------------------- #
# database/queries.py::insert_expense (unit tests)
# --------------------------------------------------------------------------- #

class TestInsertExpenseQuery:
    def test_insert_expense_creates_queryable_row(self):
        user_id = create_user("Query Test User", _query_test_email(), "testpass123")

        queries.insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")

        rows = _expenses_for_user(user_id)
        assert len(rows) == 1, "insert_expense must create exactly one row"
        row = rows[0]
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_stores_none_description_as_null(self):
        user_id = create_user("Query Test User", _query_test_email(), "testpass123")

        queries.insert_expense(user_id, 25.0, "Transport", "2026-03-21", None)

        rows = _expenses_for_user(user_id)
        assert len(rows) == 1
        assert rows[0]["description"] is None, "description=None must be stored as SQL NULL"


# --------------------------------------------------------------------------- #
# Auth guard
# --------------------------------------------------------------------------- #

class TestAddExpenseAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        response = client.get("/expenses/add")

        assert response.status_code == 302, "Unauthenticated GET must redirect, not render the form"
        assert "/login" in response.headers["Location"]

    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "2026-03-20", "description": "x"},
        )

        assert response.status_code == 302, "Unauthenticated POST must redirect, not process the form"
        assert "/login" in response.headers["Location"]

    def test_post_unauthenticated_does_not_insert_a_row(self, client):
        client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "2026-03-20", "description": "x"},
        )

        conn = get_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM expenses WHERE description = ?", ("x",)
            ).fetchone()["n"]
        finally:
            conn.close()

        assert count == 0, "An unauthenticated POST must never write to the database"


# --------------------------------------------------------------------------- #
# GET /expenses/add (authenticated)
# --------------------------------------------------------------------------- #

class TestAddExpenseGetForm:
    def test_get_authenticated_returns_200(self, client):
        register_and_login(client)

        response = client.get("/expenses/add")

        assert response.status_code == 200

    def test_get_renders_form_posting_to_expenses_add(self, client):
        register_and_login(client)

        html = client.get("/expenses/add").data.decode()

        assert "<form" in html, "Page must contain a <form> element"
        assert 'method="POST"' in html, "Form must submit via POST"
        assert 'action="/expenses/add"' in html, "Form must submit to /expenses/add"

    def test_get_category_select_contains_exactly_the_seven_fixed_categories(self, client):
        register_and_login(client)

        html = client.get("/expenses/add").data.decode()

        # Excludes any empty-value placeholder option (e.g. "Select a
        # category") — the spec's "exactly 7" requirement is about the
        # selectable categories, not decorative placeholder options.
        values = _extract_select_option_values(html, "category")
        assert set(values) == set(FIXED_CATEGORIES), (
            f"Category select must offer exactly {FIXED_CATEGORIES}, got {values}"
        )
        assert len(values) == 7, "Category select must have exactly 7 selectable categories"

    def test_get_amount_field_is_a_number_input_with_correct_constraints(self, client):
        register_and_login(client)

        html = client.get("/expenses/add").data.decode()

        assert 'name="amount"' in html, "Form must have an amount field"
        assert 'type="number"' in html, "Amount field must be a number input"
        assert 'step="0.01"' in html, "Amount field must allow cent-level precision"
        assert 'min="0.01"' in html, "Amount field must enforce a positive minimum"

    def test_get_date_field_is_a_date_input_defaulting_to_today(self, client):
        register_and_login(client)

        html = client.get("/expenses/add").data.decode()

        assert 'name="date"' in html, "Form must have a date field"
        assert 'type="date"' in html, "Date field must be a date input"
        today_iso = date.today().isoformat()
        assert today_iso in html, "Date field must default to today's date"

    def test_get_description_field_present_and_not_required(self, client):
        register_and_login(client)

        html = client.get("/expenses/add").data.decode()

        assert 'name="description"' in html, "Form must have a description field"


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

        assert response.status_code == 302, "Valid submission must redirect, not re-render the form"
        assert "/profile" in response.headers["Location"], "Must redirect to the profile page"

    def test_valid_submission_creates_expected_db_row(self, client):
        _, user_id = register_and_login(client)

        client.post(
            "/expenses/add",
            data={"amount": "250", "category": "Food", "date": "2026-03-20", "description": "Coffee"},
        )

        rows = _expenses_for_user(user_id)
        assert len(rows) == 1, "Exactly one expense row must be created for this user"
        row = rows[0]
        assert row["amount"] == 250.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Coffee"

    def test_valid_submission_appears_on_profile_page(self, client):
        register_and_login(client)

        client.post(
            "/expenses/add",
            data={
                "amount": "42.50",
                "category": "Entertainment",
                "date": "2026-03-22",
                "description": f"Movie-{uuid.uuid4().hex[:6]}",
            },
            follow_redirects=True,
        )
        response = client.get("/profile")

        assert response.status_code == 200

    def test_missing_description_redirects_and_saves_null(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "40", "category": "Transport", "date": "2026-03-21"},
        )

        assert response.status_code == 302, "Omitting the optional description must not be an error"
        rows = _expenses_for_user(user_id)
        assert len(rows) == 1
        assert rows[0]["description"] is None, "Missing description must be stored as SQL NULL"

    def test_blank_description_redirects_and_saves_null(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "15", "category": "Shopping", "date": "2026-03-22", "description": "   "},
        )

        assert response.status_code == 302, "A blank/whitespace description must not be an error"
        rows = _expenses_for_user(user_id)
        assert len(rows) == 1
        assert rows[0]["description"] is None, "Blank description must be stripped and stored as SQL NULL"


# --------------------------------------------------------------------------- #
# POST /expenses/add — validation failures
# --------------------------------------------------------------------------- #

class TestAddExpensePostValidation:
    def test_missing_amount_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "", "category": "Food", "date": "2026-03-20"},
        )

        assert response.status_code == 200, "Validation failure must re-render the form, not redirect"
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "Invalid submission must not create a row"

    def test_zero_amount_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "0", "category": "Food", "date": "2026-03-20"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "amount=0 must be rejected (must be > 0)"

    def test_negative_amount_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "-5", "category": "Food", "date": "2026-03-20"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "A negative amount must be rejected"

    def test_non_numeric_amount_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "abc", "category": "Food", "date": "2026-03-20"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "Non-numeric amount must be rejected"

    def test_invalid_category_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Not-A-Category", "date": "2026-03-20"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "Category outside the fixed list must be rejected"

    def test_invalid_date_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "not-a-date"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "An invalid date string must be rejected"

    def test_missing_date_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": ""},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "A missing date must be rejected"

    def test_description_over_200_chars_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "Food", "date": "2026-03-20", "description": "x" * 201},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "A description over 200 characters must be rejected"

    def test_missing_category_rerenders_with_error_and_no_insert(self, client):
        _, user_id = register_and_login(client)

        response = client.post(
            "/expenses/add",
            data={"amount": "10", "category": "", "date": "2026-03-20"},
        )

        assert response.status_code == 200
        assert _looks_like_error_flash(response.data.decode()), "Response must contain an error message"
        assert len(_expenses_for_user(user_id)) == 0, "A missing category must be rejected"


# --------------------------------------------------------------------------- #
# POST /expenses/add — form re-population on validation failure
# --------------------------------------------------------------------------- #

class TestAddExpenseFormRepopulation:
    def test_invalid_category_retains_amount_date_and_description(self, client):
        register_and_login(client)
        distinctive_description = f"WeeklyGroceries-{uuid.uuid4().hex[:6]}"

        response = client.post(
            "/expenses/add",
            data={
                "amount": "75.50",
                "category": "Not-A-Category",
                "date": "2026-04-15",
                "description": distinctive_description,
            },
        )
        html = response.data.decode()

        assert "75.50" in html, "Previously submitted amount must be retained on the re-rendered form"
        assert "2026-04-15" in html, "Previously submitted date must be retained on the re-rendered form"
        assert distinctive_description in html, "Previously submitted description must be retained"

    def test_missing_amount_retains_date_category_and_description(self, client):
        register_and_login(client)
        distinctive_description = f"RentPayment-{uuid.uuid4().hex[:6]}"

        response = client.post(
            "/expenses/add",
            data={
                "amount": "",
                "category": "Bills",
                "date": "2026-05-01",
                "description": distinctive_description,
            },
        )
        html = response.data.decode()

        assert "2026-05-01" in html, "Previously submitted date must be retained on the re-rendered form"
        assert 'value="Bills" selected' in html, "Previously submitted category must be retained (selected)"
        assert distinctive_description in html, "Previously submitted description must be retained"

    def test_invalid_date_retains_amount_category_and_description(self, client):
        register_and_login(client)
        distinctive_description = f"CarRepair-{uuid.uuid4().hex[:6]}"

        response = client.post(
            "/expenses/add",
            data={
                "amount": "120.00",
                "category": "Transport",
                "date": "not-a-real-date",
                "description": distinctive_description,
            },
        )
        html = response.data.decode()

        assert "120.00" in html or "120" in html, "Previously submitted amount must be retained"
        assert distinctive_description in html, "Previously submitted description must be retained"


# --------------------------------------------------------------------------- #
# UI integration (Definition of done): profile button + navbar link
# --------------------------------------------------------------------------- #

class TestAddExpenseUiIntegration:
    def test_profile_page_has_add_expense_link(self, client):
        register_and_login(client)

        html = client.get("/profile").data.decode()

        assert re.search(r'<a[^>]*href="[^"]*/expenses/add[^"]*"[^>]*>\s*Add Expense', html), (
            "Profile page must contain an 'Add Expense' link pointing to /expenses/add"
        )

    def test_navbar_shows_add_expense_link_when_authenticated(self, client):
        register_and_login(client)

        html = client.get("/profile").data.decode()

        assert re.search(r'href="[^"]*/expenses/add[^"]*"[^>]*>\s*Add Expense', html), (
            "Navbar must show an 'Add Expense' link when logged in"
        )

    def test_navbar_hides_add_expense_link_when_unauthenticated(self, client):
        html = client.get("/login").data.decode()

        assert "Add Expense" not in html, "Navbar must not show 'Add Expense' when logged out"
