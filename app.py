import sqlite3

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import create_user, get_db, get_user_by_email, init_db, seed_db

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
            create_user(name, email, password)
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
            return render_template("register.html")

        flash("Account created. Please sign in.", "success")
        return redirect(url_for("login"))

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
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "initials": "DU",
        "member_since": "January 2025",
    }

    summary = {
        "total_spent_display": "₹5,599.50",
        "transaction_count": 8,
        "top_category": "Shopping",
    }

    transactions = [
        {"date": "2026-08-22", "description": "Restaurant", "category": "Food", "amount": 180.00},
        {"date": "2026-08-19", "description": "Miscellaneous", "category": "Other", "amount": 250.00},
        {"date": "2026-08-16", "description": "Clothing", "category": "Shopping", "amount": 2200.00},
        {"date": "2026-08-13", "description": "Movie tickets", "category": "Entertainment", "amount": 599.00},
        {"date": "2026-08-10", "description": "Pharmacy", "category": "Health", "amount": 300.00},
        {"date": "2026-08-07", "description": "Electricity bill", "category": "Bills", "amount": 1500.00},
        {"date": "2026-08-04", "description": "Cab fare", "category": "Transport", "amount": 120.50},
        {"date": "2026-08-01", "description": "Groceries", "category": "Food", "amount": 450.00},
    ]

    category_breakdown = [
        {"category": "Shopping", "amount": 2200.00, "percent": 40, "slug": "shopping"},
        {"category": "Bills", "amount": 1500.00, "percent": 25, "slug": "bills"},
        {"category": "Food", "amount": 630.00, "percent": 10, "slug": "food"},
        {"category": "Entertainment", "amount": 599.00, "percent": 10, "slug": "entertainment"},
        {"category": "Health", "amount": 300.00, "percent": 5, "slug": "health"},
        {"category": "Other", "amount": 250.00, "percent": 5, "slug": "other"},
        {"category": "Transport", "amount": 120.50, "percent": 5, "slug": "transport"},
    ]

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        transactions=transactions,
        category_breakdown=category_breakdown,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
