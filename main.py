import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "campus_reports.db"
CATEGORIES = (
    "Electrical",
    "Lighting",
    "Plumbing",
    "Pathway or road",
    "Building",
    "Safety",
    "Other",
)
ROLES = ("Student", "Faculty member")
STATUSES = ("Open", "In progress", "Resolved")
STAFF_ACCOUNTS = {
    "Admin": {"admin": "admin1"},
    "Maintenance worker": {
        "dave": "maintenance1",
        "minami": "maintenance1",
        "jeanne": "maintenance1",
    },
}
LOGIN_ROLES = {
    "admin": "Admin",
    "maintenance": "Maintenance worker",
}


def configured_coordinate(name):
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        coordinate = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a valid number.") from error
    if not math.isfinite(coordinate):
        raise ValueError(f"{name} must be a finite number.")
    return coordinate


campus_latitude = configured_coordinate("CAMPUS_LAT")
campus_longitude = configured_coordinate("CAMPUS_LNG")
if (campus_latitude is None) != (campus_longitude is None):
    raise ValueError("Set both CAMPUS_LAT and CAMPUS_LNG, or leave both unset.")
if campus_latitude is not None and not -90 <= campus_latitude <= 90:
    raise ValueError("CAMPUS_LAT must be between -90 and 90.")
if campus_longitude is not None and not -180 <= campus_longitude <= 180:
    raise ValueError("CAMPUS_LNG must be between -180 and 180.")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@contextmanager
def connect_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with connect_database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                reporter_name TEXT NOT NULL,
                reporter_role TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TEXT NOT NULL,
                assigned_to TEXT
            )
            """
        )
        columns = {
            column["name"]
            for column in connection.execute("PRAGMA table_info(reports)").fetchall()
        }
        if "assigned_to" not in columns:
            connection.execute("ALTER TABLE reports ADD COLUMN assigned_to TEXT")


def csrf_protected(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        submitted_token = request.form.get("csrf_token", "")
        session_token = session.get("csrf_token", "")
        if not session_token or not secrets.compare_digest(
            submitted_token, session_token
        ):
            flash("Your form session expired. Please try again.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped_view


def staff_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if (
            session.get("staff_role") not in STAFF_ACCOUNTS
            or session.get("staff_user")
            not in STAFF_ACCOUNTS.get(session.get("staff_role"), {})
        ):
            flash("Sign in as an admin or maintenance worker to update reports.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if (
            session.get("staff_role") != "Admin"
            or session.get("staff_user") not in STAFF_ACCOUNTS["Admin"]
        ):
            flash("Sign in as an admin to assign reports.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


@app.context_processor
def inject_template_settings():
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    campus_center = None
    if campus_latitude is not None and campus_longitude is not None:
        campus_center = {"lat": campus_latitude, "lng": campus_longitude}
    return {
        "csrf_token": token,
        "campus_center": campus_center,
        "staff_user": session.get("staff_user"),
        "staff_role": session.get("staff_role"),
        "is_admin": session.get("staff_role") == "Admin",
        "is_maintenance_worker": session.get("staff_role") == "Maintenance worker",
        "can_manage_reports": (
            session.get("staff_role") in STAFF_ACCOUNTS
            and session.get("staff_user")
            in STAFF_ACCOUNTS.get(session.get("staff_role"), {})
        ),
    }


@app.get("/")
def index():
    staff_role = session.get("staff_role")
    staff_user = session.get("staff_user")
    can_manage_reports = (
        staff_role in STAFF_ACCOUNTS
        and staff_user in STAFF_ACCOUNTS.get(staff_role, {})
    )
    with connect_database() as connection:
        if can_manage_reports and staff_role == "Admin":
            reports = connection.execute(
                "SELECT * FROM reports ORDER BY created_at DESC, id DESC"
            ).fetchall()
        elif can_manage_reports and staff_role == "Maintenance worker":
            reports = connection.execute(
                """
                SELECT * FROM reports
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        else:
            reports = connection.execute(
                """
                SELECT * FROM reports
                WHERE status IN (?, ?)
                ORDER BY created_at DESC, id DESC
                """,
                ("In progress", "Resolved"),
            ).fetchall()
    return render_template(
        "index.html",
        reports=reports,
        maintenance_workers={
            username: username.title()
            for username in STAFF_ACCOUNTS["Maintenance worker"]
        },
        categories=CATEGORIES,
        roles=ROLES,
        statuses=STATUSES if can_manage_reports and staff_role == "Admin" else STATUSES[1:],
        status_filter_options=STATUSES,
    )


@app.get("/login")
def login():
    if (
        session.get("staff_role") in STAFF_ACCOUNTS
        and session.get("staff_user")
        in STAFF_ACCOUNTS.get(session.get("staff_role"), {})
    ):
        return redirect(url_for("index"))
    return render_template("login.html", login_role=None)


@app.get("/login/<role_key>")
def role_login(role_key):
    role = LOGIN_ROLES.get(role_key)
    if role is None:
        return redirect(url_for("login"))
    if (
        session.get("staff_role") in STAFF_ACCOUNTS
        and session.get("staff_user")
        in STAFF_ACCOUNTS.get(session.get("staff_role"), {})
    ):
        return redirect(url_for("index"))
    return render_template("login.html", login_role=role, role_key=role_key)


@app.post("/login/<role_key>")
@csrf_protected
def login_submit(role_key):
    role = LOGIN_ROLES.get(role_key)
    if role is None:
        flash("Choose a valid staff sign-in.", "error")
        return redirect(url_for("login"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Enter your username and password.", "error")
        return redirect(url_for("role_login", role_key=role_key))

    expected_password = STAFF_ACCOUNTS[role].get(username)
    if expected_password is None or not secrets.compare_digest(
        password.encode("utf-8"), expected_password.encode("utf-8")
    ):
        flash("The username or password is incorrect.", "error")
        return redirect(url_for("role_login", role_key=role_key))

    session.clear()
    session["staff_user"] = username
    session["staff_role"] = role
    flash("You are now signed in.", "success")
    return redirect(url_for("index"))


@app.post("/logout")
@csrf_protected
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.post("/reports")
@csrf_protected
def create_report():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "")
    description = request.form.get("description", "").strip()
    reporter_name = request.form.get("reporter_name", "").strip()
    reporter_role = request.form.get("reporter_role", "")

    if not title or len(title) > 100:
        flash("Add a title of no more than 100 characters.", "error")
        return redirect(url_for("index"))
    if category not in CATEGORIES:
        flash("Choose a valid problem category.", "error")
        return redirect(url_for("index"))
    if not description or len(description) > 2000:
        flash("Add a description of no more than 2,000 characters.", "error")
        return redirect(url_for("index"))
    if not reporter_name or len(reporter_name) > 80:
        flash("Add your name (up to 80 characters).", "error")
        return redirect(url_for("index"))
    if reporter_role not in ROLES:
        flash("Choose a valid campus role.", "error")
        return redirect(url_for("index"))

    try:
        latitude = float(request.form.get("latitude", ""))
        longitude = float(request.form.get("longitude", ""))
    except ValueError:
        flash("Select a location on the map before submitting.", "error")
        return redirect(url_for("index"))
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        flash("The selected map coordinates are invalid.", "error")
        return redirect(url_for("index"))

    created_at = datetime.now(timezone.utc).isoformat(timespec="minutes")
    with connect_database() as connection:
        connection.execute(
            """
            INSERT INTO reports (
                title, category, description, reporter_name, reporter_role,
                latitude, longitude, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                category,
                description,
                reporter_name,
                reporter_role,
                latitude,
                longitude,
                created_at,
            ),
        )
    flash("Thanks for helping us improve our campus!", "success")
    return redirect(url_for("index"))


@app.post("/reports/<int:report_id>/status")
@csrf_protected
@staff_required
def update_report_status(report_id):
    status = request.form.get("status", "")
    if status not in STATUSES:
        flash("Choose a valid report status.", "error")
        return redirect(url_for("index"))
    if session.get("staff_role") != "Admin" and status not in STATUSES[1:]:
        flash("Maintenance workers can set reports to In progress or Resolved.", "error")
        return redirect(url_for("index"))
    with connect_database() as connection:
        result = connection.execute(
            "UPDATE reports SET status = ? WHERE id = ?", (status, report_id)
        )
    if result.rowcount == 0:
        flash("That report could not be found.", "error")
    else:
        flash("Report status updated.", "success")
    return redirect(url_for("index"))


@app.post("/reports/<int:report_id>/assign")
@csrf_protected
@admin_required
def assign_report(report_id):
    assigned_to = request.form.get("assigned_to", "")
    if assigned_to and assigned_to not in STAFF_ACCOUNTS["Maintenance worker"]:
        flash("Choose a valid maintenance worker.", "error")
        return redirect(url_for("index"))

    with connect_database() as connection:
        result = connection.execute(
            "UPDATE reports SET assigned_to = ? WHERE id = ?",
            (assigned_to or None, report_id),
        )
    if result.rowcount == 0:
        flash("That report could not be found.", "error")
    elif assigned_to:
        flash("Report assigned to the maintenance worker.", "success")
    else:
        flash("Report assignment removed.", "success")
    return redirect(url_for("index"))


@app.errorhandler(413)
def request_too_large(error):
    return f"Request too large: {error.description}", 413


initialize_database()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
