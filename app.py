from __future__ import annotations

import os
import sqlite3
import datetime as dt
from io import BytesIO
from uuid import uuid4
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener
from flask import Flask, render_template, request, redirect, url_for, flash, abort


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "lostfound.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "HEIC", "HEIF"}

register_heif_opener()
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", 10 * 1024 * 1024))
MAX_SAVED_IMAGE_SIZE = int(os.environ.get("MAX_SAVED_IMAGE_SIZE", 5 * 1024 * 1024))


def shrink_image_to_target(file_bytes: bytes, format_hint: str) -> tuple[bytes | None, str | None]:
    """Best-effort compression to keep images under MAX_SAVED_IMAGE_SIZE."""
    if len(file_bytes) <= MAX_SAVED_IMAGE_SIZE:
        return file_bytes, format_hint
    try:
        with Image.open(BytesIO(file_bytes)) as image:
            image = image.convert("RGB")
            width, height = image.size
            quality = 85
            for _ in range(8):
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                data = buffer.getvalue()
                if len(data) <= MAX_SAVED_IMAGE_SIZE:
                    return data, "JPEG"
                if quality > 60:
                    quality -= 10
                    continue
                new_width = max(int(width * 0.85), 320)
                new_height = max(int(height * 0.85), 320)
                if new_width == width and new_height == height:
                    break
                image = image.resize((new_width, new_height), Image.LANCZOS)
                width, height = image.size
                quality = 85
    except Exception:
        return None, None
    return None, None


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
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE

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
        WHERE status IN ('available', 'claimed') OR status IS NULL OR status = ''
        ORDER BY date_found DESC, id DESC
        """
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
            if not file_bytes:
                flash("Image upload failed. Please choose the photo again.", "error")
                return redirect(url_for("report"))

            try:
                with Image.open(BytesIO(file_bytes)) as image:
                    image_format = (image.format or "").upper()
                    image.verify()
            except (UnidentifiedImageError, OSError, ValueError):
                flash("Unsupported image type. Please upload PNG, JPG, GIF, WEBP, or HEIC.", "error")
                return redirect(url_for("report"))

            if image_format in {"HEIC", "HEIF"}:
                try:
                    with Image.open(BytesIO(file_bytes)) as image:
                        converted = image.convert("RGB")
                        buffer = BytesIO()
                        converted.save(buffer, format="JPEG", quality=90)
                        file_bytes = buffer.getvalue()
                        image_format = "JPEG"
                except Exception:
                    flash("Unable to process HEIC image. Please choose a JPG or PNG.", "error")
                    return redirect(url_for("report"))

            if image_format not in ALLOWED_IMAGE_FORMATS:
                flash("Unsupported image type. Please upload PNG, JPG, GIF, WEBP, or HEIC.", "error")
                return redirect(url_for("report"))

            file_bytes, image_format = shrink_image_to_target(file_bytes, image_format)
            if not file_bytes or not image_format:
                flash("Image is too large even after compression. Please upload a smaller image.", "error")
                return redirect(url_for("report"))

            ext_map = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "HEIC": ".heic", "HEIF": ".heif"}
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


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
    flash(f"Image too large. Please keep uploads under {max_mb}MB.", "error")
    return redirect(url_for("report"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
