import os
import sqlite3
import datetime as dt
from io import BytesIO
from uuid import uuid4
from PIL import Image, UnidentifiedImageError
from flask import Flask, render_template, request, redirect, url_for, flash, abort


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "lostfound.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Create table with the target schema if missing
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            date_found TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'available',
            image_filename TEXT
        )
        """
    )
    # Best-effort lightweight migration for older schemas
    cur.execute("PRAGMA table_info(items)")
    cols = {row[1] for row in cur.fetchall()}  # row[1] is column name
    if "date_found" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN date_found TEXT")
    if "location" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN location TEXT")
    if "status" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN status TEXT")
        cur.execute("UPDATE items SET status='available' WHERE status IS NULL OR status='' ")
    if "image_filename" not in cols:
        cur.execute("ALTER TABLE items ADD COLUMN image_filename TEXT")
    # If an older column 'date' exists and date_found is null, copy it over
    if "date" in cols and "date_found" in cols:
        cur.execute("UPDATE items SET date_found = COALESCE(date_found, date) WHERE date_found IS NULL")
    conn.commit()
    conn.close()


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))

# Ensure the database and table exist at startup (Flask 3 removed before_first_request)
init_db()
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


@app.route("/")
def index():
    conn = get_db_connection()
    items = conn.execute(
        """
        SELECT id, name, description, date_found, location, status, image_filename
        FROM items
        WHERE status = ? OR status IS NULL OR status = ''
        ORDER BY date_found DESC, id DESC
        """,
        ("available",),
    ).fetchall()
    conn.close()
    return render_template("index.html", items=items)


@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        date_found = (request.form.get("date_found") or "").strip()
        location = (request.form.get("location") or "").strip()
        image_file = request.files.get("image")

        if not name:
            flash("Item name is required.", "error")
            return redirect(url_for("report"))
        
        if not image_file or not image_file.filename:
            flash("Image file is required.", "error")
            return redirect(url_for("report"))

        if not date_found:
            date_found = dt.date.today().isoformat()

        image_filename = None
        if image_file and image_file.filename:
            # Validate and save image
            file_bytes = image_file.read()
            try:
                image = Image.open(BytesIO(file_bytes))
                image_format = (image.format or "").upper()
                image.verify()
                image.close()
            except (UnidentifiedImageError, OSError, ValueError):
                flash("Unsupported image type. Please upload PNG, JPG, GIF, or WEBP.", "error")
                return redirect(url_for("report"))

            if image_format not in ALLOWED_IMAGE_FORMATS:
                flash("Unsupported image type. Please upload PNG, JPG, GIF, or WEBP.", "error")
                return redirect(url_for("report"))

            ext_map = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}
            unique_name = uuid4().hex + ext_map.get(image_format, "")
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
            try:
                with open(save_path, "wb") as fout:
                    fout.write(file_bytes)
                image_filename = unique_name
            except Exception:
                flash("Failed to save image.", "error")
                return redirect(url_for("report"))

        conn = get_db_connection()
        # If legacy column 'date' exists and is NOT NULL, include it in insert
        cur = conn.execute("PRAGMA table_info(items)")
        cols = {row[1] for row in cur.fetchall()}
        if "date" in cols:
            conn.execute(
                "INSERT INTO items (name, description, date_found, location, status, image_filename, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, description, date_found, location, "available", image_filename, date_found),
            )
        else:
            conn.execute(
                "INSERT INTO items (name, description, date_found, location, status, image_filename) VALUES (?, ?, ?, ?, ?, ?)",
                (name, description, date_found, location, "available", image_filename),
            )
        conn.commit()
        conn.close()

        flash("Item reported.", "success")
        return redirect(url_for("index"))

    # GET
    today = dt.date.today().isoformat()
    return render_template("report.html", today=today)


@app.route("/items/<int:item_id>")
def item_detail(item_id: int):
    conn = get_db_connection()
    item = conn.execute(
        "SELECT id, name, description, date_found, location, status, image_filename FROM items WHERE id = ?",
        (item_id,),
    ).fetchone()
    conn.close()
    if not item:
        abort(404)
    return render_template("item_detail.html", item=item)


@app.route("/claim/<int:item_id>", methods=["POST"])
def claim_item(item_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE items SET status = 'claimed' WHERE id = ?", (item_id,))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if changed:
        flash("Item marked as claimed.", "success")
    else:
        flash("Item not found.", "error")
    return redirect(url_for("item_detail", item_id=item_id))


@app.errorhandler(413)
def too_large(e):
    flash("Image too large. Max 5MB.", "error")
    return redirect(url_for("report"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
