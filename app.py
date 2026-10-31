import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "app.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-before-sharing-publicly"


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            course TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present', 'absent')),
            marked_at TEXT NOT NULL,
            UNIQUE(event_id, student_id),
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sanctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER UNIQUE NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('pending', 'set', 'paid')) DEFAULT 'pending',
            owner_note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(attendance_id) REFERENCES attendance(id) ON DELETE CASCADE
        );
        """
    )
    owner = db.execute("SELECT id FROM owners LIMIT 1").fetchone()
    if owner is None:
        db.execute(
            "INSERT INTO owners (username, password_hash) VALUES (?, ?)",
            ("owner", generate_password_hash("admin123")),
        )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("owner_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@app.before_request
def ensure_db():
    init_db()


@app.route("/")
def home():
    if session.get("owner_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        owner = get_db().execute(
            "SELECT * FROM owners WHERE username = ?", (username,)
        ).fetchone()
        if owner and check_password_hash(owner["password_hash"], password):
            session.clear()
            session["owner_id"] = owner["id"]
            session["username"] = owner["username"]
            return redirect(url_for("dashboard"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", username=session.get("username"))


@app.route("/student-lookup")
def student_lookup_page():
    return render_template("student_lookup.html")


@app.get("/api/stats")
@login_required
def stats():
    db = get_db()
    return jsonify(
        {
            "students": db.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"],
            "events": db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"],
            "unpaid": db.execute(
                "SELECT COUNT(*) AS n FROM sanctions WHERE status != 'paid'"
            ).fetchone()["n"],
            "unpaid_total": db.execute(
                "SELECT COALESCE(SUM(amount), 0) AS n FROM sanctions WHERE status != 'paid'"
            ).fetchone()["n"],
        }
    )


@app.get("/api/students")
@login_required
def list_students():
    rows = get_db().execute(
        "SELECT * FROM students ORDER BY full_name COLLATE NOCASE"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/students")
@login_required
def add_student():
    data = request.get_json(force=True)
    student_id = (data.get("student_id") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    course = (data.get("course") or "").strip()
    if not student_id or not full_name:
        return jsonify({"error": "Student ID and full name are required."}), 400
    try:
        cur = get_db().execute(
            "INSERT INTO students (student_id, full_name, course, created_at) VALUES (?, ?, ?, ?)",
            (student_id, full_name, course, now_iso()),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "That student ID already exists."}), 400
    row = get_db().execute("SELECT * FROM students WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.delete("/api/students/<int:student_pk>")
@login_required
def delete_student(student_pk):
    get_db().execute("DELETE FROM students WHERE id = ?", (student_pk,))
    get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/events")
@login_required
def list_events():
    rows = get_db().execute(
        """
        SELECT e.*,
               (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id AND a.status = 'present') AS present_count,
               (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id AND a.status = 'absent') AS absent_count
        FROM events e
        ORDER BY e.event_date DESC, e.id DESC
        """
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/events")
@login_required
def add_event():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    event_date = (data.get("event_date") or "").strip()
    location = (data.get("location") or "").strip()
    notes = (data.get("notes") or "").strip()
    if not title or not event_date:
        return jsonify({"error": "Event title and date are required."}), 400
    cur = get_db().execute(
        "INSERT INTO events (title, event_date, location, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (title, event_date, location, notes, now_iso()),
    )
    get_db().commit()
    row = get_db().execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.delete("/api/events/<int:event_id>")
@login_required
def delete_event(event_id):
    get_db().execute("DELETE FROM events WHERE id = ?", (event_id,))
    get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/events/<int:event_id>/attendance")
@login_required
def event_attendance(event_id):
    db = get_db()
    event = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        return jsonify({"error": "Event not found."}), 404
    students = db.execute(
        """
        SELECT s.id, s.student_id, s.full_name, s.course,
               a.status AS attendance_status,
               san.id AS sanction_id,
               san.amount,
               san.status AS sanction_status
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id AND a.event_id = ?
        LEFT JOIN sanctions san ON san.attendance_id = a.id
        ORDER BY s.full_name COLLATE NOCASE
        """,
        (event_id,),
    ).fetchall()
    return jsonify({"event": dict(event), "students": [dict(row) for row in students]})


@app.post("/api/events/<int:event_id>/attendance")
@login_required
def mark_attendance(event_id):
    data = request.get_json(force=True)
    student_pk = data.get("student_pk")
    status = data.get("status")
    if status not in ("present", "absent"):
        return jsonify({"error": "Status must be present or absent."}), 400
    db = get_db()
    event = db.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    student = db.execute("SELECT id FROM students WHERE id = ?", (student_pk,)).fetchone()
    if not event or not student:
        return jsonify({"error": "Event or student not found."}), 404

    existing = db.execute(
        "SELECT id FROM attendance WHERE event_id = ? AND student_id = ?",
        (event_id, student_pk),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE attendance SET status = ?, marked_at = ? WHERE id = ?",
            (status, now_iso(), existing["id"]),
        )
        attendance_id = existing["id"]
    else:
        cur = db.execute(
            "INSERT INTO attendance (event_id, student_id, status, marked_at) VALUES (?, ?, ?, ?)",
            (event_id, student_pk, status, now_iso()),
        )
        attendance_id = cur.lastrowid

    sanction = db.execute(
        "SELECT id FROM sanctions WHERE attendance_id = ?", (attendance_id,)
    ).fetchone()
    if status == "absent":
        if sanction is None:
            db.execute(
                "INSERT INTO sanctions (attendance_id, amount, status, owner_note, updated_at) VALUES (?, 0, 'pending', '', ?)",
                (attendance_id, now_iso()),
            )
    else:
        if sanction:
            paid = db.execute(
                "SELECT status FROM sanctions WHERE id = ?", (sanction["id"],)
            ).fetchone()
            if paid and paid["status"] != "paid":
                db.execute("DELETE FROM sanctions WHERE id = ?", (sanction["id"],))

    db.commit()
    return jsonify({"ok": True})


@app.get("/api/sanctions")
@login_required
def list_sanctions():
    rows = get_db().execute(
        """
        SELECT san.id, san.amount, san.status, san.owner_note, san.updated_at,
               e.title AS event_title, e.event_date,
               s.student_id, s.full_name, s.course
        FROM sanctions san
        JOIN attendance a ON a.id = san.attendance_id
        JOIN events e ON e.id = a.event_id
        JOIN students s ON s.id = a.student_id
        ORDER BY CASE san.status WHEN 'pending' THEN 0 WHEN 'set' THEN 1 ELSE 2 END,
                 e.event_date DESC, s.full_name
        """
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/sanctions/<int:sanction_id>")
@login_required
def update_sanction(sanction_id):
    data = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM sanctions WHERE id = ?", (sanction_id,)).fetchone()
    if row is None:
        return jsonify({"error": "Sanction not found."}), 404

    amount = data.get("amount", row["amount"])
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number."}), 400
    if amount < 0:
        return jsonify({"error": "Amount cannot be negative."}), 400

    status = data.get("status", row["status"])
    if status not in ("pending", "set", "paid"):
        return jsonify({"error": "Invalid sanction status."}), 400
    if amount > 0 and status == "pending":
        status = "set"

    note = data.get("owner_note", row["owner_note"])
    db.execute(
        "UPDATE sanctions SET amount = ?, status = ?, owner_note = ?, updated_at = ? WHERE id = ?",
        (amount, status, note, now_iso(), sanction_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM sanctions WHERE id = ?", (sanction_id,)).fetchone()
    return jsonify(dict(updated))


@app.get("/api/lookup/<student_id>")
def public_lookup(student_id):
    db = get_db()
    student = db.execute(
        "SELECT id, student_id, full_name, course FROM students WHERE student_id = ?",
        (student_id.strip(),),
    ).fetchone()
    if student is None:
        return jsonify({"error": "No student found with that ID."}), 404
    records = db.execute(
        """
        SELECT e.title, e.event_date, a.status AS attendance_status,
               san.amount, san.status AS sanction_status, san.owner_note
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        LEFT JOIN sanctions san ON san.attendance_id = a.id
        WHERE a.student_id = ?
        ORDER BY e.event_date DESC
        """,
        (student["id"],),
    ).fetchall()
    return jsonify({"student": dict(student), "records": [dict(row) for row in records]})


if __name__ == "__main__":
    app.run(debug=True)
