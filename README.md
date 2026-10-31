# Event attendance & sanction system

A small local web app for holding school events, marking student attendance, and letting the **owner** set a payment amount when a student is absent.

## What it does

- Owner signs in and adds students plus events.
- On an event, mark each student **present** or **absent**.
- An absence creates a **sanction**. The owner decides how much the student must pay, can add a note, and mark it **paid** when settled.
- Students can check their own record at `/student-lookup` with their student ID (no login).

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

Default owner login:

- Username: `owner`
- Password: `admin123`

Change the password hashing seed and `SECRET_KEY` in `app.py` before putting this on a public server.

## Files

| File | Role |
| --- | --- |
| `app.py` | Flask server, login, SQLite database, APIs |
| `templates/` | Login, owner dashboard, student lookup pages |
| `static/style.css` | Layout and colors |
| `static/app.js` | Dashboard actions in the browser |
| `data/app.db` | Created automatically on first run (not committed) |
