"""Tests for Step 6: Date Filter for Profile (.claude/specs/06-date-filter-profile.md).

Scope, derived from the spec (not from reading app.py's / queries.py's logic):
  - GET /profile with no query params behaves like the unfiltered Step 5 view.
  - The four quick-select presets (This Month, Last 3 Months, Last 6 Months,
    All Time) filter all three sections (summary stats, recent transactions,
    category breakdown).
  - A valid custom date_from/date_to range filters all three sections and is
    inclusive on both ends (SQLite BETWEEN semantics).
  - date_from > date_to falls back to unfiltered + flashes
    "Start date must be before end date."
  - Malformed / empty / SQL-injection-attempt date strings never crash the
    app and silently fall back to the unfiltered view.
  - A range with zero matching expenses shows a "no data" state (₹0.00 total,
    0 transactions, empty category breakdown) without erroring.
  - GET /profile requires auth (redirects to /login when unauthenticated).
  - The date_from/date_to plumbing in get_summary_stats, get_recent_transactions
    and get_category_breakdown (database/queries.py) is correct at the DB
    layer: unfiltered-by-default, inclusive bounds, correct filtering,
    zero-match empty results.

Isolation strategy: `database/db.py` has no env var/config hook to point
get_db() at a different SQLite file, and app.py runs init_db()/seed_db() at
import time. tests/conftest.py works around this by monkeypatching
`database.db.DB_PATH` to a throwaway temp file *before* `app` is imported, so
this whole test session runs against an isolated DB rather than the dev DB.
Within that shared-per-session DB file, every test registers its own unique
user (unique email) and only ever asserts on data scoped to that user's
`user_id`, so tests are independent of each other and of the demo/seed data.
"""
import re
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from conftest import get_user_id, insert_expense, register_and_login
from database.db import create_user
from database.queries import get_category_breakdown, get_recent_transactions, get_summary_stats


# --------------------------------------------------------------------------- #
# HTML-scraping helpers (used only to discover what date range a preset LINK
# actually points at, so tests can follow it end-to-end rather than guessing
# app.py's internal date-math formula, which the spec only describes loosely
# for "Last 3/6 Months").
# --------------------------------------------------------------------------- #

def extract_href(html_text, link_text):
    """Return the (unescaped) href of the first <a>...link_text...</a> tag."""
    pattern = re.compile(r'<a href="([^"]*)"[^>]*>' + re.escape(link_text) + r"</a>")
    match = pattern.search(html_text)
    assert match, f"Could not find a link with text {link_text!r} on the profile page"
    return match.group(1).replace("&amp;", "&")


def extract_preset_params(html_text, link_text):
    href = extract_href(html_text, link_text)
    qs = parse_qs(urlparse(href).query)
    return qs.get("date_from", [None])[0], qs.get("date_to", [None])[0]


def unmoney(text):
    """Strip thousands-separators so ₹ amount assertions don't depend on
    whether the app formats with commas."""
    return text.replace(",", "")


# --------------------------------------------------------------------------- #
# Auth guard
# --------------------------------------------------------------------------- #

class TestProfileAuthGuard:
    def test_get_profile_unauthenticated_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302, "Unauthenticated GET /profile must redirect, not 200"
        assert "/login" in response.headers["Location"], "Must redirect to the login page"


# --------------------------------------------------------------------------- #
# Happy path: no filter == Step 5 behaviour
# --------------------------------------------------------------------------- #

class TestProfileUnfiltered:
    def test_no_query_params_shows_all_expenses(self, client):
        email, user_id = register_and_login(client)
        desc = f"Baseline-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 77.5, "Food", date.today().isoformat(), desc)

        response = client.get("/profile")
        body = unmoney(response.data.decode())

        assert response.status_code == 200
        assert desc in body, "Expense must appear in the unfiltered transaction list"
        assert "₹77.50" in body, "Total spent must reflect the (only) expense, with ₹ symbol"

    def test_no_query_params_includes_expenses_from_multiple_months(self, client):
        email, user_id = register_and_login(client)
        recent_desc = f"Recent-{uuid.uuid4().hex[:6]}"
        old_desc = f"Old-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 10.0, "Food", date.today().isoformat(), recent_desc)
        insert_expense(user_id, 20.0, "Food", "2000-01-01", old_desc)

        response = client.get("/profile")
        body = response.data.decode()

        assert recent_desc in body
        assert old_desc in body, "Unfiltered view (All Time) must include expenses regardless of age"


# --------------------------------------------------------------------------- #
# Quick-select presets
# --------------------------------------------------------------------------- #

class TestProfilePresets:
    def test_this_month_preset_date_from_is_first_of_current_month(self, client):
        register_and_login(client)
        baseline = client.get("/profile")
        date_from, _ = extract_preset_params(baseline.data.decode(), "This Month")

        expected_first_of_month = date.today().replace(day=1).isoformat()
        assert date_from == expected_first_of_month, (
            "Spec: 'This Month' preset date_from must be the first day of the current month"
        )

    def test_this_month_preset_includes_boundary_excludes_day_before(self, client):
        email, user_id = register_and_login(client)
        baseline = client.get("/profile")
        html = baseline.data.decode()
        date_from, _ = extract_preset_params(html, "This Month")
        href = extract_href(html, "This Month")

        inside_desc = f"InsideThisMonth-{uuid.uuid4().hex[:6]}"
        outside_desc = f"OutsideThisMonth-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 10.0, "Food", date_from, inside_desc)  # exactly the lower bound
        day_before = (date.fromisoformat(date_from) - timedelta(days=1)).isoformat()
        insert_expense(user_id, 20.0, "Food", day_before, outside_desc)

        response = client.get(href)
        body = response.data.decode()

        assert response.status_code == 200
        assert inside_desc in body, "Expense dated exactly at date_from must be included (BETWEEN is inclusive)"
        assert outside_desc not in body, "Expense from the previous calendar month must be excluded"

    def test_last_3_months_preset_ends_today(self, client):
        register_and_login(client)
        baseline = client.get("/profile")
        _, date_to = extract_preset_params(baseline.data.decode(), "Last 3 Months")

        assert date_to == date.today().isoformat(), (
            "Spec: 'Last 3 Months' is a '3-month window ending today'"
        )

    def test_last_3_months_preset_includes_boundary_excludes_day_before(self, client):
        email, user_id = register_and_login(client)
        baseline = client.get("/profile")
        html = baseline.data.decode()
        date_from, _ = extract_preset_params(html, "Last 3 Months")
        href = extract_href(html, "Last 3 Months")

        inside_desc = f"InsideLast3-{uuid.uuid4().hex[:6]}"
        outside_desc = f"OutsideLast3-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 10.0, "Food", date_from, inside_desc)
        day_before = (date.fromisoformat(date_from) - timedelta(days=1)).isoformat()
        insert_expense(user_id, 20.0, "Food", day_before, outside_desc)

        response = client.get(href)
        body = response.data.decode()

        assert inside_desc in body, "Expense exactly at the window's lower bound must be included"
        assert outside_desc not in body, "Expense one day before the window must be excluded"

    def test_last_6_months_preset_ends_today(self, client):
        register_and_login(client)
        baseline = client.get("/profile")
        _, date_to = extract_preset_params(baseline.data.decode(), "Last 6 Months")

        assert date_to == date.today().isoformat(), (
            "Spec: 'Last 6 Months' is a '6-month window ending today'"
        )

    def test_last_6_months_preset_includes_boundary_excludes_day_before(self, client):
        email, user_id = register_and_login(client)
        baseline = client.get("/profile")
        html = baseline.data.decode()
        date_from, _ = extract_preset_params(html, "Last 6 Months")
        href = extract_href(html, "Last 6 Months")

        inside_desc = f"InsideLast6-{uuid.uuid4().hex[:6]}"
        outside_desc = f"OutsideLast6-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 10.0, "Food", date_from, inside_desc)
        day_before = (date.fromisoformat(date_from) - timedelta(days=1)).isoformat()
        insert_expense(user_id, 20.0, "Food", day_before, outside_desc)

        response = client.get(href)
        body = response.data.decode()

        assert inside_desc in body, "Expense exactly at the window's lower bound must be included"
        assert outside_desc not in body, "Expense one day before the window must be excluded"

    def test_all_time_preset_link_has_no_query_params(self, client):
        register_and_login(client)
        baseline = client.get("/profile")
        href = extract_href(baseline.data.decode(), "All Time")
        parsed = urlparse(href)

        assert parsed.path.endswith("/profile")
        assert parsed.query == "", "Spec: 'All Time' preset must pass no query params (clean /profile URL)"

    def test_all_time_preset_shows_all_expenses_regardless_of_age(self, client):
        email, user_id = register_and_login(client)
        old_desc = f"VeryOld-{uuid.uuid4().hex[:6]}"
        new_desc = f"BrandNew-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 15.0, "Food", "2000-01-01", old_desc)
        insert_expense(user_id, 25.0, "Food", date.today().isoformat(), new_desc)

        baseline = client.get("/profile")
        href = extract_href(baseline.data.decode(), "All Time")
        response = client.get(href)
        body = response.data.decode()

        assert old_desc in body
        assert new_desc in body


# --------------------------------------------------------------------------- #
# Custom date range
# --------------------------------------------------------------------------- #

class TestProfileCustomRange:
    def test_custom_range_shows_only_expenses_within_range(self, client):
        email, user_id = register_and_login(client)
        in_range_desc = f"InRange-{uuid.uuid4().hex[:6]}"
        out_range_desc = f"OutRange-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 40.0, "Bills", "2024-05-15", in_range_desc)
        insert_expense(user_id, 60.0, "Bills", "2024-07-01", out_range_desc)

        response = client.get("/profile?date_from=2024-05-01&date_to=2024-05-31")
        body = response.data.decode()

        assert response.status_code == 200
        assert in_range_desc in body
        assert out_range_desc not in body

    def test_custom_range_inclusive_on_both_endpoints(self, client):
        email, user_id = register_and_login(client)
        lower_desc = f"LowerBound-{uuid.uuid4().hex[:6]}"
        upper_desc = f"UpperBound-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 11.0, "Food", "2024-03-01", lower_desc)
        insert_expense(user_id, 22.0, "Food", "2024-03-31", upper_desc)

        response = client.get("/profile?date_from=2024-03-01&date_to=2024-03-31")
        body = response.data.decode()

        assert lower_desc in body, "date_from bound must be inclusive"
        assert upper_desc in body, "date_to bound must be inclusive"

    def test_custom_range_reflects_in_category_breakdown_and_stats(self, client):
        email, user_id = register_and_login(client)
        insert_expense(user_id, 100.0, "Food", "2024-06-05")
        insert_expense(user_id, 50.0, "Transport", "2024-06-10")
        insert_expense(user_id, 999.0, "Shopping", "2024-09-01")  # outside range

        response = client.get("/profile?date_from=2024-06-01&date_to=2024-06-30")
        body = unmoney(response.data.decode())

        assert "₹150.00" in body, "Total spent must sum only in-range expenses"
        assert "Food" in body
        assert "Transport" in body
        assert "Shopping" not in body, "Out-of-range category must not appear in the breakdown"

    def test_custom_range_zero_matches_shows_empty_state(self, client):
        email, user_id = register_and_login(client)
        known_desc = f"NotInFuture-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 33.0, "Food", date.today().isoformat(), known_desc)

        response = client.get("/profile?date_from=2099-01-01&date_to=2099-12-31")
        body = unmoney(response.data.decode())

        assert response.status_code == 200
        assert known_desc not in body
        assert "₹0.00" in body, "Spec: zero-match range must show ₹0.00 total spent"
        assert '<span class="mock-stat-value">0</span>' in body, "Spec: zero-match range must show 0 transactions"


# --------------------------------------------------------------------------- #
# Edge cases: invalid input must never crash, must fall back to unfiltered
# --------------------------------------------------------------------------- #

class TestProfileFilterEdgeCases:
    def test_date_from_after_date_to_flashes_error_and_falls_back(self, client):
        email, user_id = register_and_login(client)
        desc = f"Fallback-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 99.0, "Food", date.today().isoformat(), desc)

        response = client.get(
            "/profile?date_from=2024-12-31&date_to=2024-01-01", follow_redirects=True
        )
        body = response.data.decode()

        assert response.status_code == 200
        assert "Start date must be before end date." in body, "Spec-mandated flash message text"
        assert desc in body, "Must fall back to showing all expenses (unfiltered)"

    def test_malformed_date_strings_do_not_crash_and_fall_back(self, client):
        email, user_id = register_and_login(client)
        desc = f"Malformed-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 15.0, "Food", date.today().isoformat(), desc)

        response = client.get("/profile?date_from=not-a-date&date_to=also-not-a-date")
        body = response.data.decode()

        assert response.status_code == 200, "Malformed dates must not raise a 500"
        assert desc in body, "Must silently fall back to the unfiltered view"

    def test_one_malformed_one_valid_date_falls_back_to_unfiltered(self, client):
        email, user_id = register_and_login(client)
        desc = f"PartialMalformed-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 5.0, "Food", date.today().isoformat(), desc)

        response = client.get(f"/profile?date_from={date.today().isoformat()}&date_to=nonsense")
        body = response.data.decode()

        assert response.status_code == 200
        assert desc in body, "A single malformed param must be treated as absent, falling back to unfiltered"

    def test_empty_string_date_params_fall_back_to_unfiltered(self, client):
        email, user_id = register_and_login(client)
        desc = f"EmptyParams-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 5.0, "Food", date.today().isoformat(), desc)

        response = client.get("/profile?date_from=&date_to=")
        body = response.data.decode()

        assert response.status_code == 200
        assert desc in body

    def test_sql_injection_attempt_does_not_crash_or_corrupt_data(self, client):
        email, user_id = register_and_login(client)
        desc = f"Injection-{uuid.uuid4().hex[:6]}"
        insert_expense(user_id, 5.0, "Food", date.today().isoformat(), desc)

        malicious = "2024-01-01'); DROP TABLE expenses;--"
        response = client.get(f"/profile?date_from={malicious}&date_to=2024-12-31")

        assert response.status_code == 200, "A SQL-injection-shaped date string must not crash the app"

        # The expenses table must still exist and be fully queryable afterwards
        # (parameterized queries mean the string is never executed as SQL).
        followup = client.get("/profile")
        assert followup.status_code == 200
        assert desc in followup.data.decode(), "Data must be intact; injection attempt must have no effect"


# --------------------------------------------------------------------------- #
# DB-level correctness of the three query helpers' date-range plumbing
# --------------------------------------------------------------------------- #

class TestQueryHelpersDateFilterCorrectness:
    @staticmethod
    def _make_user():
        email = f"dbuser_{uuid.uuid4().hex}@example.com"
        return create_user("DB Test User", email, "pw12345")

    # -- get_summary_stats -------------------------------------------------

    def test_get_summary_stats_no_filter_matches_all_expenses(self):
        user_id = self._make_user()
        insert_expense(user_id, 100.0, "Food", "2024-01-05")
        insert_expense(user_id, 50.0, "Transport", "2024-02-10")
        insert_expense(user_id, 25.0, "Food", "2024-03-15")

        result = get_summary_stats(user_id)

        assert result["total_spent"] == 175.0
        assert result["transaction_count"] == 3

    def test_get_summary_stats_absent_params_match_explicit_none(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-05")
        insert_expense(user_id, 20.0, "Food", "2024-02-05")

        implicit = get_summary_stats(user_id)
        explicit = get_summary_stats(user_id, None, None)

        assert implicit == explicit, (
            "Spec: when date_from/date_to are absent, behaviour must match Step 5 (unfiltered)"
        )

    def test_get_summary_stats_inclusive_on_both_ends(self):
        user_id = self._make_user()
        insert_expense(user_id, 100.0, "Food", "2024-01-01")  # lower bound
        insert_expense(user_id, 50.0, "Food", "2024-01-15")   # mid
        insert_expense(user_id, 75.0, "Food", "2024-01-31")   # upper bound
        insert_expense(user_id, 999.0, "Food", "2023-12-31")  # just before range
        insert_expense(user_id, 888.0, "Food", "2024-02-01")  # just after range

        result = get_summary_stats(user_id, "2024-01-01", "2024-01-31")

        assert result["transaction_count"] == 3, "Both boundary dates must be included (BETWEEN is inclusive)"
        assert result["total_spent"] == 225.0, "Out-of-range expenses must not be summed"

    def test_get_summary_stats_zero_matches_returns_zero_defaults(self):
        user_id = self._make_user()
        insert_expense(user_id, 100.0, "Food", "2024-01-01")

        result = get_summary_stats(user_id, "2030-01-01", "2030-12-31")

        assert result["transaction_count"] == 0
        assert result["total_spent"] == 0

    # -- get_recent_transactions --------------------------------------------

    def test_get_recent_transactions_absent_params_match_explicit_none(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-01")

        implicit = get_recent_transactions(user_id)
        explicit = get_recent_transactions(user_id, date_from=None, date_to=None)

        assert implicit == explicit

    def test_get_recent_transactions_respects_date_range(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-05", "in-range-1")
        insert_expense(user_id, 20.0, "Food", "2024-01-15", "in-range-2")
        insert_expense(user_id, 30.0, "Food", "2024-02-01", "out-of-range")

        results = get_recent_transactions(user_id, date_from="2024-01-01", date_to="2024-01-31")
        descriptions = [r["description"] for r in results]

        assert "in-range-1" in descriptions
        assert "in-range-2" in descriptions
        assert "out-of-range" not in descriptions

    def test_get_recent_transactions_inclusive_on_both_ends(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-06-01", "lower-bound")
        insert_expense(user_id, 20.0, "Food", "2024-06-30", "upper-bound")

        results = get_recent_transactions(user_id, date_from="2024-06-01", date_to="2024-06-30")
        descriptions = [r["description"] for r in results]

        assert "lower-bound" in descriptions
        assert "upper-bound" in descriptions

    def test_get_recent_transactions_ordering_and_limit_unchanged_when_filtered(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-01", "oldest")
        insert_expense(user_id, 20.0, "Food", "2024-01-10", "middle")
        insert_expense(user_id, 30.0, "Food", "2024-01-20", "newest")

        results = get_recent_transactions(user_id, limit=2, date_from="2024-01-01", date_to="2024-01-31")

        assert len(results) == 2, "Spec: limit must still apply within a filtered range"
        assert [r["description"] for r in results] == ["newest", "middle"], (
            "Spec: ordering must remain unchanged (most recent date first) when filtered"
        )

    def test_get_recent_transactions_zero_matches_returns_empty_list(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-01")

        results = get_recent_transactions(user_id, date_from="2030-01-01", date_to="2030-12-31")

        assert results == []

    # -- get_category_breakdown ----------------------------------------------

    def test_get_category_breakdown_absent_params_match_explicit_none(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-01")

        implicit = get_category_breakdown(user_id)
        explicit = get_category_breakdown(user_id, date_from=None, date_to=None)

        assert implicit == explicit

    def test_get_category_breakdown_respects_date_range(self):
        user_id = self._make_user()
        insert_expense(user_id, 100.0, "Food", "2024-01-05")
        insert_expense(user_id, 50.0, "Transport", "2024-01-10")
        insert_expense(user_id, 999.0, "Shopping", "2024-03-01")  # outside range

        breakdown = get_category_breakdown(user_id, date_from="2024-01-01", date_to="2024-01-31")
        categories = {c["name"] for c in breakdown}

        assert categories == {"Food", "Transport"}
        assert "Shopping" not in categories

    def test_get_category_breakdown_inclusive_on_both_ends(self):
        user_id = self._make_user()
        insert_expense(user_id, 40.0, "Food", "2024-04-01")
        insert_expense(user_id, 60.0, "Food", "2024-04-30")

        breakdown = get_category_breakdown(user_id, date_from="2024-04-01", date_to="2024-04-30")
        food = next(c for c in breakdown if c["name"] == "Food")

        assert food["amount"] == 100.0

    def test_get_category_breakdown_percentages_recalculated_within_range(self):
        user_id = self._make_user()
        insert_expense(user_id, 30.0, "Food", "2024-05-01")
        insert_expense(user_id, 70.0, "Transport", "2024-05-02")
        insert_expense(user_id, 5000.0, "Shopping", "2024-08-01")  # outside range, must not skew %

        breakdown = get_category_breakdown(user_id, date_from="2024-05-01", date_to="2024-05-31")

        assert sum(c["pct"] for c in breakdown) == 100, (
            "Spec: percentage recalculation logic must still apply within the filtered set"
        )

    def test_get_category_breakdown_zero_matches_returns_empty_list(self):
        user_id = self._make_user()
        insert_expense(user_id, 10.0, "Food", "2024-01-01")

        breakdown = get_category_breakdown(user_id, date_from="2030-01-01", date_to="2030-12-31")

        assert breakdown == []
