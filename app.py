from __future__ import annotations

import os
import sqlite3
import datetime as dt
from io import BytesIO
from uuid import uuid4
from functools import wraps
from urllib.parse import urljoin, urlparse
import logging
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "lostfound.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "HEIC", "HEIF"}

register_heif_opener()
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", 6 * 1024 * 1024))
MAX_SAVED_IMAGE_SIZE = int(os.environ.get("MAX_SAVED_IMAGE_SIZE", 3 * 1024 * 1024))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin")
ADMIN_SESSION_KEY = "is_admin"

logger = logging.getLogger(__name__)


class ImageProcessingError(Exception):
    """Raised when an uploaded image cannot be processed."""


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


def process_and_store_image(file_bytes: bytes) -> str:
    """Validate, shrink, and persist the uploaded image. Returns the stored filename."""
    if not file_bytes:
        raise ImageProcessingError("Empty image payload.")

    try:
        with Image.open(BytesIO(file_bytes)) as image:
            image_format = (image.format or "").upper()
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageProcessingError("Unsupported image type.") from exc

    if image_format in {"HEIC", "HEIF"}:
        try:
            with Image.open(BytesIO(file_bytes)) as image:
                converted = image.convert("RGB")
                buffer = BytesIO()
                converted.save(buffer, format="JPEG", quality=90)
                file_bytes = buffer.getvalue()
                image_format = "JPEG"
        except Exception as exc:
            raise ImageProcessingError("Unable to process HEIC image.") from exc

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ImageProcessingError("Unsupported image type.")

    processed_bytes, processed_format = shrink_image_to_target(file_bytes, image_format)
    if not processed_bytes or not processed_format:
        raise ImageProcessingError("Image is too large even after compression.")

    ext_map = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp", "HEIC": ".heic", "HEIF": ".heif"}
    unique_name = uuid4().hex + ext_map.get(processed_format, "")
    save_path = os.path.join(UPLOAD_FOLDER, unique_name)
    try:
        with open(save_path, "wb") as fout:
            fout.write(processed_bytes)
    except Exception as exc:
        raise ImageProcessingError("Failed to save processed image.") from exc

    return unique_name


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_admin(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get(ADMIN_SESSION_KEY):
            flash("Please log in as an administrator to continue.", "error")
            return redirect(url_for("admin_login", next=request.url))
        return view_func(*args, **kwargs)

    return wrapped


def _is_safe_redirect(target: str) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ("http", "https") and host_url.netloc == redirect_url.netloc


def get_admin_redirect_target(default: str = "admin_dashboard") -> str:
    target = request.form.get("next") or request.args.get("next")
    if target and _is_safe_redirect(target):
        return target
    return url_for(default)


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


@app.after_request
def add_no_cache_headers(response):
    endpoint = (request.endpoint or "").split(".")[0]
    if endpoint != "static":
        response.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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

        if image_file.mimetype and not image_file.mimetype.lower().startswith("image/"):
            flash("Unsupported file type. Please upload a photo.", "error")
            return redirect(url_for("report"))

        if not date_found:
            date_found = dt.date.today().isoformat()

        try:
            file_bytes = image_file.read()
        except Exception:
            flash("Image upload failed. Please choose the photo again.", "error")
            return redirect(url_for("report"))

        if not file_bytes:
            flash("Image upload failed. Please choose the photo again.", "error")
            return redirect(url_for("report"))

        try:
            image_filename = process_and_store_image(file_bytes)
        except ImageProcessingError as exc:
            flash(str(exc) or "We couldn't process that photo. Please upload PNG, JPG, GIF, WEBP, or HEIC.", "error")
            return redirect(url_for("report"))
        except Exception:
            logger.exception("Failed to process image for %s", name)
            flash("We couldn't process the photo. Please try again.", "error")
            return redirect(url_for("report"))

        image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)

        conn = get_db_connection()
        try:
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
        except Exception:
            conn.rollback()
            try:
                os.remove(image_path)
            except OSError as exc:
                logger.warning("Failed to remove image %s for failed insert: %s", image_path, exc)
            logger.exception("Failed to save report for %s", name)
            flash("We couldn't save your report. Please try again.", "error")
            return redirect(url_for("report"))
        finally:
            conn.close()

        flash("Item reported.", "success")
        timestamp = int(dt.datetime.utcnow().timestamp())
        return redirect(url_for("index", ts=timestamp), code=303)

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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        if token == ADMIN_TOKEN:
            session[ADMIN_SESSION_KEY] = True
            flash("Admin access granted.", "success")
            return redirect(get_admin_redirect_target())
        flash("Invalid admin token.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@require_admin
def admin_logout():
    session.pop(ADMIN_SESSION_KEY, None)
    flash("Logged out of the admin area.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@require_admin
def admin_dashboard():
    conn = get_db_connection()
    items = conn.execute(
        """
        SELECT id, name, description, date_found, location, status, image_filename
        FROM items
        ORDER BY date_found DESC, id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("admin.html", items=items, upload_folder=UPLOAD_FOLDER)


@app.route("/admin/items/<int:item_id>/delete", methods=["POST"])
@require_admin
def admin_delete_item(item_id: int):
    conn = get_db_connection()
    try:
        item = conn.execute(
            "SELECT image_filename, name FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not item:
            flash("Item not found.", "error")
            return redirect(url_for("admin_dashboard"))

        if item["image_filename"]:
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], item["image_filename"])
            try:
                os.remove(image_path)
            except FileNotFoundError:
                logger.info("Image %s already missing when deleting item %s", image_path, item_id)
            except OSError as exc:
                logger.warning("Failed to remove image %s for item %s: %s", image_path, item_id, exc)

        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()

    logger.info("Admin deleted item %s (%s)", item_id, item["name"])
    flash("Item deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/items/<int:item_id>/mark-available", methods=["POST"])
@require_admin
def admin_mark_available(item_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE items SET status = 'available' WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed:
        logger.info("Admin set item %s to available", item_id)
        flash("Item marked as available.", "success")
    else:
        flash("Item not found or already available.", "error")
    return redirect(url_for("admin_dashboard"))


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
    timestamp = int(dt.datetime.utcnow().timestamp())
    return redirect(url_for("item_detail", item_id=item_id, ts=timestamp), code=303)


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
    flash(f"Image too large. Please keep uploads under {max_mb}MB. We automatically shrink photos to about 3MB.", "error")
    return redirect(url_for("report"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
