University Manager
==================

A small Flask-based web application for managing courses, sections, classrooms, instructors, students and enrollments. The app demonstrates role-based access (Admin / Instructor / Student) and implements common database operations (CRUD, enrollments, grade entry, reports/analytics) against a MySQL database.

**Repository**
- `app.py` : Main Flask application (routes, DB helpers, role logic).
- `templates/` : Jinja2 HTML templates (dashboard, instructor, student, admin views).
- `static/css/style.css` : Styling for the UI.
- `queries/schema-ddl.sql` : DDL to create the `project` schema and tables.
- `queries/academics-dml.sql` : Sample data (buildings, departments, users, courses, sections, enrollments).
- `config.py`, `config.env` : Application configuration (DB connection and `SECRET_KEY`) — keep secrets out of source.

**Quick overview**
- Roles: `admin`, `instructor`, `student`.
- Authentication: Login via email/password. Passwords in sample data use `SHA2(...,256)` (hex SHA-256). `app.py` supports both hex SHA-256 and werkzeug salted hashes.
- Key features:
  - Admin: CRUD for courses, sections, classrooms, departments, timeslots, users. View/submit grades and manage assignments.
  - Instructor: View assigned sections, roster, submit grades, manage prerequisites, view reports.
  - Student: Register / drop classes, view grades, edit personal info.

**Setup (local development)**
1. Install Python packages (Flask + MySQL connector). If you don't have a `requirements.txt`, install at least:

```powershell
python -m pip install Flask mysql-connector-python
```

2. Create the database and load schema/sample data (MySQL):

```sql
-- run the two files in order inside your MySQL client
SOURCE path/to/queries/schema-ddl.sql;
SOURCE path/to/queries/academics-dml.sql;
```

3. Configure database access and secret key in `config.py` or via `config.env`. Example values (not included for security):
- `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME` (should be `project` per provided SQL).
- `SECRET_KEY` for Flask sessions.

4. Run the app (PowerShell):

```powershell
python .\app.py
```

Open `http://127.0.0.1:5000/` in a browser.

**Sample credentials (from `queries/academics-dml.sql`)**
- Admin: email `jsmith.@ADMIN.university.edu` password `adminpass1` (stored as SHA2 in sample data)
- Instructors: many entries like `asmith@instructor.university.edu` / `instrpass1`
- Students: e.g. `noah.adams@student.university.edu` / `studpass1`

Note: sample SQL stores passwords using `SHA2('password',256)` which produces a 64-character hex digest. The app's `verify_password` accepts that format or werkzeug hashed strings.

**Important files to check or modify**
- `app.py` : contains most route logic. Modify if you want to add/adjust behavior.
- `templates/admin/` : admin UIs (some scaffolding added). If you add features in `app.py`, create matching templates.
- `queries/` : schema and sample data. Re-run these scripts if you want a fresh database.

**Routes of interest**
- `GET /` : Login page (`templates/index.html`).
- `POST /login` : Login endpoint.
- `GET /dashboard` : Role-based dashboard.
- Student: `/student/courses`, `/student/course-info`, `/student/grades`, `/student/edit`.
- Instructor: `/instructor/sections`, `/instructor/section/<id>/roster`, `/instructor/prereqs`, `/instructor/reports`, `/instructor/edit`.
- Admin: `/admin`, `/admin/departments`, `/admin/classrooms`, `/admin/sections`, `/admin/courses`, `/admin/users`.

**Security notes**
- Secrets: keep `SECRET_KEY` and DB credentials out of source (use environment variables or a `.env` file).
- Password hashing: prefer `werkzeug.security.generate_password_hash()` for new accounts (the code will accept those), and avoid storing raw SHA in production.
- Production: run behind a production server (uWSGI/gunicorn + reverse proxy), enable TLS, and use secure session cookies.


**Licensing**
See `LICENSE` in repository root.

