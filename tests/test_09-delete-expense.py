"""Tests for Step 9: Delete Expense (.claude/specs/09-delete-expense.md).

Scope, derived strictly from the spec (not from reading app.py's /
database/queries.py's actual logic):

  - `database/queries.py::delete_expense(expense_id, user_id)` deletes the
    row scoped to `id = ? AND user_id = ?`:
      * correct owner -> row removed
      * wrong user_id -> row remains, 0 rows affected, no error raised
      * non-existent expense_id -> no error raised, DB unchanged
  - `POST /expenses/<id>/delete` (unauthenticated) redirects (302) to
    `/login`.
  - `POST /expenses/<id>/delete` (authenticated, own expense) redirects
    (302) to `/profile` and the row no longer exists in the DB.
  - `POST /expenses/<id>/delete` (authenticated, another user's expense)
    returns 404 and the row still exists.
  - `POST /expenses/<id>/delete` (authenticated, non-existent id) returns
    404.
  - `GET /expenses/<id>/delete` (any user) returns 405.

Isolation strategy: shared per-session temp SQLite DB (see conftest.py);
every test uses its own unique user (via register_and_login) and only ever
asserts on data scoped to that user's rows.
"""
import database.queries as queries
from conftest import insert_expense, register_and_login
from database.db import get_db


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _expense_exists(expense_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _insert_and_get_id(user_id, amount=42.0, category="Food", date_str="2026-03-20"):
    insert_expense(user_id, amount, category, date_str)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# database/queries.py::delete_expense (unit tests)
# --------------------------------------------------------------------------- #

class TestDeleteExpenseQuery:
    def test_delete_expense_removes_row_for_correct_owner(self, client):
        _, user_id = register_and_login(client, name="Owner One")
        expense_id = _insert_and_get_id(user_id)

        queries.delete_expense(expense_id, user_id)

        assert not _expense_exists(expense_id)

    def test_delete_expense_wrong_user_leaves_row_intact(self, client):
        _, owner_id = register_and_login(client, name="Owner Two")
        expense_id = _insert_and_get_id(owner_id)

        other_client = client.application.test_client()
        _, other_id = register_and_login(other_client, name="Intruder")

        queries.delete_expense(expense_id, other_id)

        assert _expense_exists(expense_id), "wrong user_id must not delete another user's row"

    def test_delete_expense_nonexistent_id_raises_no_error(self, client):
        _, user_id = register_and_login(client, name="Owner Three")

        queries.delete_expense(999999, user_id)  # must not raise


# --------------------------------------------------------------------------- #
# Auth guard
# --------------------------------------------------------------------------- #

class TestDeleteExpenseAuthGuard:
    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post("/expenses/1/delete")

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# --------------------------------------------------------------------------- #
# Route behavior
# --------------------------------------------------------------------------- #

class TestDeleteExpenseRoute:
    def test_post_own_expense_redirects_to_profile_and_removes_row(self, client):
        _, user_id = register_and_login(client, name="Deleter")
        expense_id = _insert_and_get_id(user_id)

        response = client.post(f"/expenses/{expense_id}/delete")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/profile")
        assert not _expense_exists(expense_id)

    def test_post_other_users_expense_returns_404_and_row_remains(self, client):
        _, owner_id = register_and_login(client, name="Owner Four")
        expense_id = _insert_and_get_id(owner_id)

        attacker_client = client.application.test_client()
        register_and_login(attacker_client, name="Attacker")
        response = attacker_client.post(f"/expenses/{expense_id}/delete")

        assert response.status_code == 404
        assert _expense_exists(expense_id)

    def test_post_nonexistent_id_returns_404(self, client):
        register_and_login(client, name="Owner Five")

        response = client.post("/expenses/999999/delete")

        assert response.status_code == 404

    def test_get_returns_405(self, client):
        _, user_id = register_and_login(client, name="Owner Six")
        expense_id = _insert_and_get_id(user_id)

        response = client.get(f"/expenses/{expense_id}/delete")

        assert response.status_code == 405
