from datetime import datetime

from database.db import get_db


def _date_filter_clause(date_from, date_to):
    if date_from and date_to:
        return " AND date BETWEEN ? AND ?", [date_from, date_to]
    return "", []


def get_user_by_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        member_since = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%B %Y")
        return {"name": row["name"], "email": row["email"], "member_since": member_since}
    finally:
        conn.close()


# --- Subagent 1: implement get_recent_transactions below ---
def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    conn = get_db()
    try:
        clause, extra = _date_filter_clause(date_from, date_to)
        rows = conn.execute(
            "SELECT date, description, category, amount FROM expenses "
            "WHERE user_id = ?" + clause + " ORDER BY date DESC LIMIT ?",
            (user_id, *extra, limit),
        ).fetchall()
        return [
            {
                "date": row["date"],
                "description": row["description"],
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        conn.close()


# --- Subagent 2: implement get_summary_stats below ---
def get_summary_stats(user_id, date_from=None, date_to=None):
    conn = get_db()
    try:
        clause, extra = _date_filter_clause(date_from, date_to)
        totals = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent, COUNT(*) AS transaction_count "
            "FROM expenses WHERE user_id = ?" + clause,
            (user_id, *extra),
        ).fetchone()

        if totals["transaction_count"] == 0:
            return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

        top = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ?" + clause + " "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id, *extra),
        ).fetchone()

        return {
            "total_spent": totals["total_spent"],
            "transaction_count": totals["transaction_count"],
            "top_category": top["category"],
        }
    finally:
        conn.close()


# --- Subagent 3: implement get_category_breakdown below ---
def get_category_breakdown(user_id, date_from=None, date_to=None):
    conn = get_db()
    try:
        clause, extra = _date_filter_clause(date_from, date_to)
        rows = conn.execute(
            "SELECT category, SUM(amount) AS amount FROM expenses "
            "WHERE user_id = ?" + clause + " GROUP BY category ORDER BY amount DESC",
            (user_id, *extra),
        ).fetchall()

        if not rows:
            return []

        total = sum(row["amount"] for row in rows)

        breakdown = []
        for row in rows:
            amount = row["amount"]
            pct = int((amount / total) * 100)
            breakdown.append({"name": row["category"], "amount": amount, "pct": pct})

        remainder = 100 - sum(item["pct"] for item in breakdown)
        breakdown[0]["pct"] += remainder

        return breakdown
    finally:
        conn.close()
