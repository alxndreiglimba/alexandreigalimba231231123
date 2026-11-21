from datetime import datetime
from functools import wraps
from pathlib import Path
import re
from zipfile import BadZipFile

import mysql.connector
from mysql.connector import Error
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OWNER_USERNAME = "alexandrei"
DEFAULT_OWNER_PASSWORD = "galimba@123"

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-secret-key-before-sharing-publicly"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# MySQL Database Configuration for Laragon
DB_HOST = "127.0.0.1"
DB_USER = "root"
DB_PASSWORD = "1234"
DB_NAME = "ssg_db"

def init_database():
    """ Automatically creates the ssg_db database if it doesn't exist """
    try:
        conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        cursor.close()
        conn.close()
    except Error as e:
        print(f"Error creating database: {e}")

# Initialize database creation on startup
init_database()

def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        g.cursor = g.db.cursor(dictionary=True)
    return g.db, g.cursor


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    cursor = g.pop("cursor", None)
    if cursor is not None:
        cursor.close()
    if db is not None:
        db.close()


def init_db():
    db, cursor = get_db()
    
    # Unified users table for both admins and students
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255) NOT NULL DEFAULT '',
            course VARCHAR(255) NOT NULL DEFAULT '',
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL CHECK(role IN ('admin', 'student')) DEFAULT 'student',
            created_at VARCHAR(255) NOT NULL
        )
        """
    )
    
    # Keep compatibility table mapping students if needed for attendance foreign keys
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_id VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            course VARCHAR(255) NOT NULL DEFAULT '',
            created_at VARCHAR(255) NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            event_date VARCHAR(255) NOT NULL,
            location TEXT NOT NULL,
            notes TEXT NOT NULL,
            attendance_starts_at VARCHAR(255),
            attendance_cutoff_at VARCHAR(255),
            created_at VARCHAR(255) NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_id INT NOT NULL,
            student_id INT NOT NULL,
            status VARCHAR(50) NOT NULL CHECK(status IN ('present', 'absent')),
            marked_at VARCHAR(255) NOT NULL,
            UNIQUE(event_id, student_id),
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sanctions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            attendance_id INT UNIQUE NOT NULL,
            amount FLOAT NOT NULL DEFAULT 0,
            status VARCHAR(50) NOT NULL CHECK(status IN ('pending', 'set', 'paid')) DEFAULT 'pending',
            owner_note TEXT NOT NULL,
            updated_at VARCHAR(255) NOT NULL,
            FOREIGN KEY(attendance_id) REFERENCES attendance(id) ON DELETE CASCADE
        )
        """
    )

    # Check and add columns safely if missing
    cursor.execute("SHOW COLUMNS FROM events LIKE 'attendance_starts_at'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE events ADD COLUMN attendance_starts_at VARCHAR(255)")
        
    cursor.execute("SHOW COLUMNS FROM events LIKE 'attendance_cutoff_at'")
    if not cursor.fetchone():
        cursor.execute("ALTER TABLE events ADD COLUMN attendance_cutoff_at VARCHAR(255)")

    # Ensure default admin account exists in users table
    cursor.execute("SELECT id FROM users WHERE username = %s", (DEFAULT_OWNER_USERNAME,))
    if cursor.fetchone() is None:
        cursor.execute(
            """
            INSERT INTO users (username, full_name, password_hash, role, created_at) 
            VALUES (%s, %s, %s, 'admin', %s)
            """,
            (
                DEFAULT_OWNER_USERNAME,
                "System Administrator",
                generate_password_hash(DEFAULT_OWNER_PASSWORD),
                now_iso(),
            ),
        )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def parse_local_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return parsed


def normalized_name(value):
    return " ".join(value.split()).casefold()


def excel_cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_student_workbook(file_storage):
    workbook = load_workbook(file_storage, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        header_aliases = {
            "id": "student_id",
            "studentid": "student_id",
            "studentnumber": "student_id",
            "studentno": "student_id",
            "fullname": "full_name",
            "name": "full_name",
            "studentname": "full_name",
            "course": "course",
            "program": "course",
        }
        columns = {}
        for index, value in enumerate(next(worksheet.iter_rows(values_only=True), ())):
            normalized_header = re.sub(r"[^a-z0-9]+", "", excel_cell_text(value).casefold())
            field = header_aliases.get(normalized_header)
            if field:
                if field in columns:
                    raise ValueError(f"The spreadsheet has more than one column for {field.replace('_', ' ')}.")
                columns[field] = index

        missing_fields = {"student_id", "full_name"} - columns.keys()
        if missing_fields:
            missing = " and ".join(field.replace("_", " ") for field in sorted(missing_fields))
            raise ValueError(f"Required column(s) not found: {missing}.")

        students = []
        seen_ids = set()
        for row_number, values in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
            if row_number > 10001:
                raise ValueError("The spreadsheet may contain at most 10,000 student rows.")
            if not any(excel_cell_text(value) for value in values):
                continue

            student_id = excel_cell_text(values[columns["student_id"]] if columns["student_id"] < len(values) else None)
            full_name = excel_cell_text(values[columns["full_name"]] if columns["full_name"] < len(values) else None)
            course = excel_cell_text(values[columns["course"]] if "course" in columns and columns["course"] < len(values) else None)
            if not student_id or not full_name:
                raise ValueError(f"Row {row_number} must include both a student ID and full name.")

            normalized_id = student_id.casefold()
            if normalized_id in seen_ids:
                raise ValueError(f"Student ID {student_id} appears more than once in the spreadsheet (row {row_number}).")
            seen_ids.add(normalized_id)
            students.append((student_id, full_name, course))

        if not students:
            raise ValueError("The spreadsheet contains no student rows.")
        return students
    finally:
        workbook.close()


@app.before_request
def ensure_db():
    init_db()


@app.errorhandler(413)
def request_entity_too_large(_error):
    return jsonify({"error": "Excel workbook must be 10 MB or smaller."}), 413


@app.route("/")
def home():
    if session.get("role") == "admin":
        return redirect(url_for("dashboard"))
    if session.get("role") == "student":
        return redirect(url_for("student_lookup_page"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("role") == "admin":
        return redirect(url_for("dashboard"))
    if session.get("role") == "student":
        return redirect(url_for("student_lookup_page"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db, cursor = get_db()
        
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            
            if user["role"] == "admin":
                return redirect(url_for("dashboard"))
            else:
                return redirect(url_for("student_lookup_page"))
                
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("role") == "admin":
        return redirect(url_for("dashboard"))
    if session.get("role") == "student":
        return redirect(url_for("student_lookup_page"))

    error = None
    if request.method == "POST":
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        db, cursor = get_db()

        if len(password) < 8:
            error = "Password must be at least 8 characters."
        elif role not in ("admin", "student"):
            error = "Choose whether this account is for an admin or student."
        else:
            username = request.form.get("username" if role == "admin" else "student_id", "").strip()
            full_name = request.form.get("full_name", "").strip() if role == "student" else "Administrator"
            course = request.form.get("course", "").strip() if role == "student" else ""

            if not username or (role == "student" and not full_name):
                error = "Required account details are missing."
            else:
                cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    error = "That username or student ID is already in use."
                else:
                    try:
                        cursor.execute(
                            """
                            INSERT INTO users (username, full_name, course, password_hash, role, created_at) 
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (username, full_name, course, generate_password_hash(password), role, now_iso()),
                        )
                        
                        # Sync students table for roster/attendance support if registered as student
                        if role == "student":
                            cursor.execute(
                                """
                                INSERT INTO students (student_id, full_name, course, created_at)
                                VALUES (%s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE full_name = VALUES(full_name), course = VALUES(course)
                                """,
                                (username, full_name, course, now_iso())
                            )
                            
                        db.commit()
                        return redirect(url_for("login"))
                    except mysql.connector.Error:
                        db.rollback()
                        error = "An error occurred while creating the account."

    return render_template("register.html", error=error)


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
    student_id = request.args.get("student_id", "").strip()
    db, cursor = get_db()
    if session.get("role") == "student":
        cursor.execute(
            "SELECT username FROM users WHERE id = %s",
            (session["user_id"],),
        )
        user = cursor.fetchone()
        if user is None:
            session.clear()
            return redirect(url_for("login"))
        student_id = user["username"]
    return render_template("student_lookup.html", student_id=student_id)


@app.get("/api/accounts")
@login_required
def list_accounts():
    db, cursor = get_db()
    cursor.execute("SELECT id, username, full_name, course, role, created_at FROM users ORDER BY full_name ASC")
    rows = cursor.fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/accounts/<int:user_id>/role")
@login_required
def update_user_role(user_id):
    data = request.get_json(force=True)
    new_role = data.get("role")
    if new_role not in ("admin", "student"):
        return jsonify({"error": "Invalid role specified."}), 400
        
    db, cursor = get_db()
    cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/stats")
@login_required
def stats():
    db, cursor = get_db()
    cursor.execute("SELECT COUNT(*) AS n FROM students")
    students_count = cursor.fetchone()["n"]
    
    cursor.execute("SELECT COUNT(*) AS n FROM events")
    events_count = cursor.fetchone()["n"]
    
    cursor.execute("SELECT COUNT(*) AS n FROM sanctions WHERE status != 'paid'")
    unpaid_count = cursor.fetchone()["n"]
    
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS n FROM sanctions WHERE status != 'paid'")
    unpaid_total = cursor.fetchone()["n"]
    
    return jsonify(
        {
            "students": students_count,
            "events": events_count,
            "unpaid": unpaid_count,
            "unpaid_total": unpaid_total,
        }
    )


@app.get("/api/students")
@login_required
def list_students():
    db, cursor = get_db()
    cursor.execute(
        "SELECT * FROM students ORDER BY full_name ASC"
    )
    rows = cursor.fetchall()
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
    db, cursor = get_db()
    try:
        cursor.execute(
            "INSERT INTO students (student_id, full_name, course, created_at) VALUES (%s, %s, %s, %s)",
            (student_id, full_name, course, now_iso()),
        )
        last_id = cursor.lastrowid
        db.commit()
    except mysql.connector.Error:
        return jsonify({"error": "That student ID already exists."}), 400
    cursor.execute("SELECT * FROM students WHERE id = %s", (last_id,))
    row = cursor.fetchone()
    return jsonify(dict(row)), 201


@app.post("/api/students/import")
@login_required
def import_students():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose an Excel .xlsx file to import."}), 400
    if not upload.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "Use an Excel workbook in .xlsx format."}), 400
    selected_course = request.form.get("course", "").strip()
    if selected_course not in ("BSIT", "BSOA", "CRIMINOLOGY"):
        return jsonify({"error": "Choose BSIT, BSOA, or CRIMINOLOGY for this student list."}), 400

    try:
        students = parse_student_workbook(upload)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        return jsonify({"error": f"Could not import spreadsheet: {error}"}), 400
    students = [(student_id, full_name, selected_course) for student_id, full_name, _ in students]

    db, cursor = get_db()
    try:
        existing_ids = set()
        for start in range(0, len(students), 500):
            batch_ids = [student[0] for student in students[start:start + 500]]
            placeholders = ", ".join(["%s"] * len(batch_ids))
            cursor.execute(
                f"SELECT student_id FROM students WHERE student_id IN ({placeholders})",
                tuple(batch_ids),
            )
            existing_ids.update(row["student_id"].casefold() for row in cursor.fetchall())

        cursor.executemany(
            """
            INSERT INTO students (student_id, full_name, course, created_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE full_name = VALUES(full_name), course = VALUES(course)
            """,
            [(student_id, full_name, course, now_iso()) for student_id, full_name, course in students],
        )
        db.commit()
    except mysql.connector.Error:
        db.rollback()
        app.logger.exception("Failed to import student roster.")
        return jsonify({"error": "A database error prevented the roster import. No changes were saved."}), 500

    updated = sum(student_id.casefold() in existing_ids for student_id, _, _ in students)
    return jsonify({"imported": len(students), "added": len(students) - updated, "updated": updated})


@app.delete("/api/students/<int:student_pk>")
@login_required
def delete_student(student_pk):
    db, cursor = get_db()
    cursor.execute("DELETE FROM students WHERE id = %s", (student_pk,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/events")
@login_required
def list_events():
    db, cursor = get_db()
    cursor.execute(
        """
        SELECT e.*,
               (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id AND a.status = 'present') AS present_count,
               (SELECT COUNT(*) FROM attendance a WHERE a.event_id = e.id AND a.status = 'absent') AS absent_count
        FROM events e
        ORDER BY e.event_date DESC, e.id DESC
        """
    )
    rows = cursor.fetchall()
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
    starts_value = data.get("attendance_starts_at") or ""
    cutoff_value = data.get("attendance_cutoff_at") or ""
    if bool(starts_value) != bool(cutoff_value):
        return jsonify({"error": "Set both the attendance opening and cutoff times."}), 400
    starts_at = parse_local_datetime(starts_value) if starts_value else None
    cutoff_at = parse_local_datetime(cutoff_value) if cutoff_value else None
    if starts_value and (starts_at is None or cutoff_at is None):
        return jsonify({"error": "Enter valid local opening and cutoff date-times."}), 400
    if starts_at and cutoff_at and cutoff_at <= starts_at:
        return jsonify({"error": "The cutoff must be after the attendance opening time."}), 400
    
    db, cursor = get_db()
    cursor.execute(
        """
        INSERT INTO events (
            title, event_date, location, notes, created_at,
            attendance_starts_at, attendance_cutoff_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            title,
            event_date,
            location,
            notes,
            now_iso(),
            starts_at.strftime("%Y-%m-%dT%H:%M") if starts_at else None,
            cutoff_at.strftime("%Y-%m-%dT%H:%M") if cutoff_at else None,
        ),
    )
    last_id = cursor.lastrowid
    db.commit()
    cursor.execute("SELECT * FROM events WHERE id = %s", (last_id,))
    row = cursor.fetchone()
    return jsonify(dict(row)), 201


@app.delete("/api/events/<int:event_id>")
@login_required
def delete_event(event_id):
    db, cursor = get_db()
    cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/events/<int:event_id>/check-in")
def event_check_in_page(event_id):
    db, cursor = get_db()
    cursor.execute(
        "SELECT * FROM events WHERE id = %s", (event_id,)
    )
    event = cursor.fetchone()
    if event is None:
        return "Event not found.", 404
    event = dict(event)
    starts_at = parse_local_datetime(event["attendance_starts_at"])
    cutoff_at = parse_local_datetime(event["attendance_cutoff_at"])
    now = datetime.now()
    if starts_at is None or cutoff_at is None:
        attendance_message = "Student check-in has not been scheduled for this event."
    elif now < starts_at:
        attendance_message = f"Check-in opens at {event['attendance_starts_at'].replace('T', ' ')}."
    elif now >= cutoff_at:
        attendance_message = "The attendance check-in cutoff has passed."
    else:
        attendance_message = "Attendance is open. Enter your details to check in."
    return render_template(
        "event_checkin.html",
        event=event,
        attendance_message=attendance_message,
    )


@app.get("/events/<int:event_id>/student-lookup")
def event_student_lookup_page(event_id):
    db, cursor = get_db()
    cursor.execute(
        "SELECT id, title, event_date, location FROM events WHERE id = %s",
        (event_id,),
    )
    event = cursor.fetchone()
    if event is None:
        return "Event not found.", 404
    return render_template("event_student_lookup.html", event=dict(event))


@app.get("/api/events/<int:event_id>/student-lookup")
def event_student_lookup(event_id):
    db, cursor = get_db()
    cursor.execute(
        "SELECT id FROM events WHERE id = %s", (event_id,)
    )
    event = cursor.fetchone()
    if event is None:
        return jsonify({"error": "Event not found."}), 404

    query = request.args.get("q", "").strip()
    if not query or len(query) > 100:
        return jsonify({"error": "Enter a student ID or first name (up to 100 characters)."}), 400

    cursor.execute(
        """
        SELECT s.student_id, s.full_name,
               a.status AS attendance_status, a.marked_at
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id AND a.event_id = %s
        WHERE s.student_id = %s
           OR LOWER(SUBSTRING_INDEX(s.full_name, ' ', 1)) = LOWER(%s)
        ORDER BY s.full_name ASC
        """,
        (event_id, query, query),
    )
    rows = cursor.fetchall()
    if not rows:
        return jsonify({"error": "No roster student matched that student ID or first name."}), 404
    return jsonify({"students": [dict(row) for row in rows]})


@app.post("/api/events/<int:event_id>/check-in")
def student_check_in(event_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A student ID and full name are required."}), 400

    student_id = data.get("student_id")
    full_name = data.get("full_name")
    if not isinstance(student_id, str) or not isinstance(full_name, str):
        return jsonify({"error": "A student ID and full name are required."}), 400
    student_id = student_id.strip()
    full_name = full_name.strip()
    if not student_id or not full_name:
        return jsonify({"error": "A student ID and full name are required."}), 400

    db, cursor = get_db()
    cursor.execute(
        "SELECT id, attendance_starts_at, attendance_cutoff_at FROM events WHERE id = %s",
        (event_id,),
    )
    event = cursor.fetchone()
    if event is None:
        return jsonify({"error": "Event not found."}), 404

    starts_at = parse_local_datetime(event["attendance_starts_at"])
    cutoff_at = parse_local_datetime(event["attendance_cutoff_at"])
    if starts_at is None or cutoff_at is None:
        return jsonify({"error": "Attendance check-in is not scheduled for this event."}), 409

    now = datetime.now()
    if now < starts_at:
        return jsonify({"error": "Attendance check-in has not opened yet."}), 409
    if now >= cutoff_at:
        return jsonify({"error": "The attendance check-in cutoff has passed."}), 409

    cursor.execute(
        "SELECT id, student_id, full_name FROM students WHERE student_id = %s",
        (student_id,),
    )
    student = cursor.fetchone()
    if student is None:
        cursor.execute(
            """
            INSERT INTO students (student_id, full_name, course, created_at)
            VALUES (%s, %s, '', %s)
            ON DUPLICATE KEY UPDATE full_name = VALUES(full_name)
            """,
            (student_id, full_name, now_iso()),
        )
        db.commit()
        cursor.execute(
            "SELECT id, student_id, full_name FROM students WHERE student_id = %s",
            (student_id,),
        )
        student = cursor.fetchone()

    if normalized_name(full_name) != normalized_name(student["full_name"]):
        return jsonify({"error": "Student ID and full name did not match the roster."}), 404

    cursor.execute(
        "SELECT id FROM attendance WHERE event_id = %s AND student_id = %s",
        (event_id, student["id"]),
    )
    attendance = cursor.fetchone()
    marked_at = now.strftime("%Y-%m-%d %H:%M")
    if attendance:
        attendance_id = attendance["id"]
        cursor.execute(
            "UPDATE attendance SET status = 'present', marked_at = %s WHERE id = %s",
            (marked_at, attendance_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO attendance (event_id, student_id, status, marked_at)
            VALUES (%s, %s, 'present', %s)
            """,
            (event_id, student["id"], marked_at),
        )
        attendance_id = cursor.lastrowid

    cursor.execute(
        "SELECT id, status FROM sanctions WHERE attendance_id = %s", (attendance_id,)
    )
    sanction = cursor.fetchone()
    if sanction and sanction["status"] != "paid":
        cursor.execute("DELETE FROM sanctions WHERE id = %s", (sanction["id"],))
    db.commit()
    return jsonify(
        {
            "ok": True,
            "student_id": student["student_id"],
            "full_name": student["full_name"],
            "marked_at": marked_at,
        }
    )


@app.get("/api/events/<int:event_id>/attendance")
@login_required
def event_attendance(event_id):
    db, cursor = get_db()
    cursor.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    if event is None:
        return jsonify({"error": "Event not found."}), 404
        
    cursor.execute(
        """
        SELECT s.id, s.student_id, s.full_name, s.course,
               a.status AS attendance_status,
               a.marked_at,
               san.id AS sanction_id,
               san.amount,
               san.status AS sanction_status
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id AND a.event_id = %s
        LEFT JOIN sanctions san ON san.attendance_id = a.id
        ORDER BY s.full_name ASC
        """,
        (event_id,),
    )
    students = cursor.fetchall()
    return jsonify({"event": dict(event), "students": [dict(row) for row in students]})


@app.post("/api/events/<int:event_id>/attendance")
@login_required
def mark_attendance(event_id):
    data = request.get_json(force=True)
    student_pk = data.get("student_pk")
    status = data.get("status")
    if status not in ("present", "absent"):
        return jsonify({"error": "Status must be present or absent."}), 400
        
    db, cursor = get_db()
    cursor.execute("SELECT id FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    cursor.execute("SELECT id FROM students WHERE id = %s", (student_pk,))
    student = cursor.fetchone()
    if not event or not student:
        return jsonify({"error": "Event or student not found."}), 404

    cursor.execute(
        "SELECT id FROM attendance WHERE event_id = %s AND student_id = %s",
        (event_id, student_pk),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            "UPDATE attendance SET status = %s, marked_at = %s WHERE id = %s",
            (status, now_iso(), existing["id"]),
        )
        attendance_id = existing["id"]
    else:
        cursor.execute(
            "INSERT INTO attendance (event_id, student_id, status, marked_at) VALUES (%s, %s, %s, %s)",
            (event_id, student_pk, status, now_iso()),
        )
        attendance_id = cursor.lastrowid

    cursor.execute(
        "SELECT id FROM sanctions WHERE attendance_id = %s", (attendance_id,)
    )
    sanction = cursor.fetchone()
    if status == "absent":
        if sanction is None:
            cursor.execute(
                "INSERT INTO sanctions (attendance_id, amount, status, owner_note, updated_at) VALUES (%s, 0, 'pending', '', %s)",
                (attendance_id, now_iso()),
            )
    else:
        if sanction:
            cursor.execute(
                "SELECT status FROM sanctions WHERE id = %s", (sanction["id"],)
            )
            paid = cursor.fetchone()
            if paid and paid["status"] != "paid":
                cursor.execute("DELETE FROM sanctions WHERE id = %s", (sanction["id"],))

    db.commit()
    return jsonify({"ok": True})


@app.get("/api/sanctions")
@login_required
def list_sanctions():
    db, cursor = get_db()
    cursor.execute(
        """
        SELECT san.id, san.amount, san.status, san.owner_note, san.updated_at,
               e.title AS event_title, e.event_date,
               s.student_id, s.full_name, s.course
        FROM sanctions san
        JOIN attendance a ON a.id = san.attendance_id
        JOIN events e ON e.id = a.event_id
        JOIN students s ON s.id = a.student_id
        ORDER BY CASE san.status WHEN 'pending' THEN 0 WHEN 'set' THEN 1 ELSE 2 END,
                 e.event_date DESC, s.full_name ASC
        """
    )
    rows = cursor.fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/sanctions/<int:sanction_id>")
@login_required
def update_sanction(sanction_id):
    data = request.get_json(force=True)
    db, cursor = get_db()
    cursor.execute("SELECT * FROM sanctions WHERE id = %s", (sanction_id,))
    row = cursor.fetchone()
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
    cursor.execute(
        "UPDATE sanctions SET amount = %s, status = %s, owner_note = %s, updated_at = %s WHERE id = %s",
        (amount, status, note, now_iso(), sanction_id),
    )
    db.commit()
    cursor.execute("SELECT * FROM sanctions WHERE id = %s", (sanction_id,))
    updated = cursor.fetchone()
    return jsonify(dict(updated))


@app.get("/api/lookup/<student_id>")
def public_lookup(student_id):
    db, cursor = get_db()
    cursor.execute(
        "SELECT id, student_id, full_name, course FROM students WHERE student_id = %s",
        (student_id.strip(),),
    )
    student = cursor.fetchone()
    if student is None:
        return jsonify({"error": "No student found with that ID."}), 404
    cursor.execute(
        """
        SELECT e.title, e.event_date, a.status AS attendance_status,
               san.amount, san.status AS sanction_status, san.owner_note
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        LEFT JOIN sanctions san ON san.attendance_id = a.id
        WHERE a.student_id = %s
        ORDER BY e.event_date DESC
        """,
        (student["id"],),
    )
    records = cursor.fetchall()
    return jsonify({"student": dict(student), "records": [dict(row) for row in records]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)