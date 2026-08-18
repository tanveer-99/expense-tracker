import calendar
import sqlite3
from datetime import date, datetime

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import CATEGORIES, create_user, get_db, get_user_by_email, init_db, seed_db
from database.queries import (
    delete_expense,
    get_category_breakdown,
    get_expense_by_id,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
    insert_expense,
    update_expense,
)

app = Flask(__name__)
app.secret_key = "dev-secret-key"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        try:
            user_id = create_user(name, email, password)
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return render_template("register.html")

        session["user_id"] = user_id
        session["user_name"] = name
        flash("Account created. Welcome to Spendly!", "success")
        return redirect(url_for("landing"))

    abort(405)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("login.html")

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("landing"))

    abort(405)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


# ------------------------------------------------------------------ #
# Date filter helpers                                                 #
# ------------------------------------------------------------------ #

def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_before(d, months):
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _compute_presets():
    today = date.today()
    return {
        "this_month": {
            "date_from": today.replace(day=1).isoformat(),
            "date_to": today.isoformat(),
        },
        "last_3_months": {
            "date_from": _months_before(today, 3).isoformat(),
            "date_to": today.isoformat(),
        },
        "last_6_months": {
            "date_from": _months_before(today, 6).isoformat(),
            "date_to": today.isoformat(),
        },
    }


def _resolve_date_filter(args, presets):
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = None
        date_to = None

    date_from_str = date_from.isoformat() if date_from else None
    date_to_str = date_to.isoformat() if date_to else None

    active_filter = "all_time"
    if date_from_str and date_to_str:
        active_filter = "custom"
        for name, rng in presets.items():
            if rng["date_from"] == date_from_str and rng["date_to"] == date_to_str:
                active_filter = name
                break

    return date_from_str, date_to_str, active_filter


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    user_row = get_user_by_id(user_id)
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))

    initials = "".join(part[0] for part in user_row["name"].split()[:2]).upper()
    user = {**user_row, "initials": initials}

    presets = _compute_presets()
    date_from_str, date_to_str, active_filter = _resolve_date_filter(request.args, presets)

    stats = get_summary_stats(user_id, date_from_str, date_to_str)
    summary = {
        "total_spent_display": f"₹{stats['total_spent']:,.2f}",
        "transaction_count": stats["transaction_count"],
        "top_category": stats["top_category"],
    }

    transactions = get_recent_transactions(user_id, date_from=date_from_str, date_to=date_to_str)

    category_breakdown = [
        {
            "category": c["name"],
            "amount": c["amount"],
            "percent": c["pct"],
            "slug": c["name"].lower(),
        }
        for c in get_category_breakdown(user_id, date_from=date_from_str, date_to=date_to_str)
    ]

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        transactions=transactions,
        category_breakdown=category_breakdown,
        presets=presets,
        active_filter=active_filter,
        date_from_value=date_from_str or "",
        date_to_value=date_to_str or "",
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            categories=CATEGORIES,
            amount="",
            category="",
            date=date.today().isoformat(),
            description="",
        )

    if request.method == "POST":
        user_id = session["user_id"]
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_raw = request.form.get("date", "").strip()
        description_raw = request.form.get("description", "").strip()

        def _render_error(message):
            flash(message, "error")
            return render_template(
                "add_expense.html",
                categories=CATEGORIES,
                amount=amount_raw,
                category=category,
                date=date_raw,
                description=description_raw,
            )

        try:
            amount = float(amount_raw)
        except ValueError:
            return _render_error("Enter a valid amount.")

        if amount <= 0:
            return _render_error("Amount must be greater than 0.")

        if category not in CATEGORIES:
            return _render_error("Select a valid category.")

        try:
            datetime.strptime(date_raw, "%Y-%m-%d")
        except ValueError:
            return _render_error("Enter a valid date.")

        if len(description_raw) > 200:
            return _render_error("Description must be 200 characters or fewer.")

        description = description_raw if description_raw else None

        insert_expense(user_id, amount, category, date_raw, description)
        return redirect(url_for("profile"))

    abort(405)


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    expense = get_expense_by_id(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            categories=CATEGORIES,
            expense=expense,
            amount=expense["amount"],
            category=expense["category"],
            date=expense["date"],
            description=expense["description"] or "",
        )

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_raw = request.form.get("date", "").strip()
        description_raw = request.form.get("description", "").strip()

        def _render_error(message):
            flash(message, "error")
            return render_template(
                "edit_expense.html",
                categories=CATEGORIES,
                expense=expense,
                amount=amount_raw,
                category=category,
                date=date_raw,
                description=description_raw,
            )

        try:
            amount = float(amount_raw)
        except ValueError:
            return _render_error("Enter a valid amount.")

        if amount <= 0:
            return _render_error("Amount must be greater than 0.")

        if category not in CATEGORIES:
            return _render_error("Select a valid category.")

        try:
            datetime.strptime(date_raw, "%Y-%m-%d")
        except ValueError:
            return _render_error("Enter a valid date.")

        if len(description_raw) > 200:
            return _render_error("Description must be 200 characters or fewer.")

        description = description_raw if description_raw else None

        update_expense(id, user_id, amount, category, date_raw, description)
        return redirect(url_for("profile"))

    abort(405)


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense_route(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    expense = get_expense_by_id(id, user_id)
    if expense is None:
        abort(404)

    delete_expense(id, user_id)
    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
