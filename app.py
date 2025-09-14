import os
import sqlite3
import datetime as dt
from flask import Flask, render_template, request, redirect, url_for, flash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "lostfound.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            date TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

# Ensure the database and table exist at startup (Flask 3 removed before_first_request)
init_db()


@app.route("/")
def index():
    conn = get_db_connection()
    items = conn.execute(
        "SELECT id, name, description, date FROM items ORDER BY date DESC, id DESC"
    ).fetchall()
    conn.close()
    return render_template("index.html", items=items)


@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        date_val = (request.form.get("date") or "").strip()

        if not name:
            flash("Item name is required.", "error")
            return redirect(url_for("report"))

        if not date_val:
            date_val = dt.date.today().isoformat()

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO items (name, description, date) VALUES (?, ?, ?)",
            (name, description, date_val),
        )
        conn.commit()
        conn.close()

        flash("Report submitted.", "success")
        return redirect(url_for("index"))

    # GET
    today = dt.date.today().isoformat()
    return render_template("report.html", today=today)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
