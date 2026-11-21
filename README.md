# Event attendance & sanction system

A small local web app for holding school events, marking student attendance, and letting the **owner** set a payment amount when a student is absent.

## What it does

- Owner signs in and creates events. Students who check in are automatically added to the student roster.
- Anyone can create an account as an admin with a username and password. Students can create an account with a student ID, name, and password; this also adds them to the roster. Admin signup is open, so restrict access before deploying publicly.
- Student accounts sign in with their student ID and can view their attendance record.
- When creating an event, set its attendance opening and cutoff date/time in the server's local time. Share the event's **Open student check-in** link with students; they enter a student ID and full name, and a new student is added to the roster automatically. For an existing student ID, the name must match the roster. Check-in is accepted only during the scheduled window.
- Each event also has a **Student look-up** link. Students can search by exact student ID or exact first name to see whether attendance was recorded for that event.
- In the Student roster, choose an event to see the students with attendance records for that event, including their status and recorded time.
- In the Student roster, select BSIT, BSOA, or CRIMINOLOGY before uploading an `.xlsx` workbook to add or update students in bulk. The first worksheet must have `Student ID` and `Full Name` columns. The selected course is assigned to every student, overriding any course values in the workbook. Store student IDs as text if they contain leading zeros.
- On an event, mark each student **present** or **absent**.
- An absence creates a **sanction**. The owner decides how much the student must pay, can add a note, and mark it **paid** when settled.
- Students must sign in with their student ID to view their own record at `/student-lookup`; admins can search all students.

## Run it

Install Python 3.10 or later and start Laragon's MySQL service. In PowerShell, from the project folder:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:DB_PASSWORD = "your local MySQL password"
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

On a fresh local database, create an admin account from the registration page. Existing databases retain their current accounts.

## Deploy publicly with Railway

GitHub stores the source code; it does not run this Flask application. To make the site available on the internet:

1. Create a Railway project and deploy this GitHub repository as a web service.
2. Add a MySQL service to the same Railway project.
3. In the web service's Variables, configure:
   - `APP_ENV` = `production`
   - `DB_CREATE_DATABASE` = `false`
   - `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, and `MYSQLDATABASE` using the connection values from the Railway MySQL service.
   - `SECRET_KEY` = a new, long random value.
   - `OWNER_USERNAME` and `OWNER_PASSWORD` = the first admin login. Use a unique password with at least 12 characters.
4. Set the web service start command to `gunicorn --bind 0.0.0.0:$PORT app:app` if Railway does not detect the included `Procfile`.
5. In Railway's web service Networking settings, generate a public domain. Share that HTTPS address.

Never put production passwords in GitHub or commit them in source files. Values previously committed remain visible in Git history, so rotate any real credentials that were in the repository. The public deployment starts with a new, empty database; local records are not copied automatically.

Student lookup requires sign-in. Students can only view their own records; admins can search all students.

## Files

| File | Role |
| --- | --- |
| `app.py` | Flask server, login, MySQL database, APIs |
| `templates/` | Login, owner dashboard, student lookup pages |
| `static/style.css` | Layout and colors |
| `static/app.js` | Dashboard actions in the browser |
| MySQL database `ssg_db` | Created automatically on startup |
