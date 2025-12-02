# app.py
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
import hashlib
import config

app = Flask(__name__)

app.secret_key = config.SECRET_KEY

def verify_password(stored_password: str, provided_password: str) -> bool:

    if not stored_password:
        return False

    stored = stored_password.strip()

    if len(stored) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored):
        provided_hash = hashlib.sha256(provided_password.encode('utf-8')).hexdigest()
        return provided_hash.lower() == stored.lower()
    

def get_user_by_email(email):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)

        # check for admin
        cur.execute("SELECT adminID AS id, first_name, last_name, email, password FROM Admin WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            row['type'] = 'admin'
            return row

        # check for instructor
        cur.execute("SELECT instructorID AS id, first_name, last_name, email, password FROM Instructor WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            row['type'] = 'instructor'
            return row

        # check for student
        cur.execute("SELECT studentID AS id, first_name, last_name, email, password FROM Student WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            row['type'] = 'student'
            return row

        return None
    finally:
        cur.close()
        conn.close()


def get_student_profile(student_id):
    """Return student profile dictionary for the given student_id or None, including advisor info."""
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
              s.studentID AS id, s.first_name, s.last_name, s.email, s.birth_date,
              s.year, s.term, s.standing, s.major,
              a.advisorID, a.first_name AS advisor_first, a.last_name AS advisor_last,
              a.email AS advisor_email, a.phone AS advisor_phone
            FROM Student s
            LEFT JOIN Advisor a ON s.advisorID = a.advisorID
            WHERE s.studentID = %s
        """, (student_id,))
        # give the student info with advisor info if any
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()



@app.route('/', methods=['GET'])
def index():
    
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if not email or not password:
        return render_template('index.html', error="Please enter both email and password.")

    user = get_user_by_email(email)
    if not user:
        return render_template('index.html', error="No account found with that email.")

    if not verify_password(user['password'], password):
        return render_template('index.html', error="Incorrect password.")

    # if success store user info in session
    session.clear()
    session['user_id'] = user['id']
    session['user_type'] = user['type']
    session['user_name'] = f"{user.get('first_name','')} {user.get('last_name','')}".strip()
    session['user_email'] = user.get('email')

    return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index', error="Please sign in to continue."))

    # dashboard page
    # If student, fetch profile to template
    student_profile = None
    if session.get('user_type') == 'student':
        try:
            student_profile = get_student_profile(session.get('user_id')) # get the user profile from their ID
        except Exception:
            student_profile = None

    return render_template(
        'dashboard.html',
        user_name=session.get('user_name'),
        user_email=session.get('user_email'),
        user_type=session.get('user_type'),
        student_profile=student_profile,
    )


# --- Student helper: get all enrollments with useful joins ---
def get_student_enrollments(student_id):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT
              e.enrollmentID, e.grade, e.status,
              s.sectionID, s.semester, s.year,
              c.courseID, c.course_name, c.course_number, c.credits,
              i.instructorID, i.first_name AS instr_first, i.last_name AS instr_last,
              t.day_of_week, TIME_FORMAT(t.start_time, '%%H:%%i') AS start_time,
              TIME_FORMAT(t.end_time, '%%H:%%i') AS end_time,
              cl.room_number, b.building_name
            FROM Enrollment e
            JOIN Section s ON e.sectionID = s.sectionID
            JOIN Course c ON s.courseID = c.courseID
            LEFT JOIN Instructor i ON s.instructorID = i.instructorID
            LEFT JOIN Timeslot t ON s.timeslotID = t.timeslotID
            LEFT JOIN Classroom cl ON s.classroomID = cl.classroomID
            LEFT JOIN Building b ON cl.buildingID = b.buildingID
            WHERE e.studentID = %s
            ORDER BY s.year DESC, s.semester DESC, c.course_number
        """, (student_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# --- Grades page route ---
@app.route('/student/grades')
def student_grades():
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index', error="Please sign in as a student."))

    # fetch enrollments (keep existing DB helper)
    student_id = session['user_id']
    enrollments = get_student_enrollments(student_id)  # your helper

    final = [e for e in enrollments if e['status'] == 'completed']
    current = [e for e in enrollments if e['status'] != 'completed']

    # **Note:** template path matches file: templates/student/view_grades.html
    return render_template(
        'student/view_grades.html',
        final=final,
        current=current,
        user_name=session.get('user_name')
    )



# --------------------------
# Helpers for sections & registration
# --------------------------
def get_sections(semester=None, year=None, course_filter=None):
    """
    Return a list of sections with joined course/instructor/room/time info and current enrolled count.
    Optionally filter by semester, year, and course number/name fragment.
    """
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT
              s.sectionID, s.semester, s.year, s.capacity,
              c.courseID, c.course_name, c.course_number, c.credits,
              i.instructorID, i.first_name AS instr_first, i.last_name AS instr_last,
              t.day_of_week, TIME_FORMAT(t.start_time, '%%H:%%i') AS start_time,
              TIME_FORMAT(t.end_time, '%%H:%%i') AS end_time,
              cl.room_number, b.building_name,
              (SELECT COUNT(*) FROM Enrollment e WHERE e.sectionID = s.sectionID AND e.status='enrolled') AS enrolled_count
            FROM Section s
            JOIN Course c ON s.courseID = c.courseID
            LEFT JOIN Instructor i ON s.instructorID = i.instructorID
            LEFT JOIN Timeslot t ON s.timeslotID = t.timeslotID
            LEFT JOIN Classroom cl ON s.classroomID = cl.classroomID
            LEFT JOIN Building b ON cl.buildingID = b.buildingID
            WHERE 1=1
        """
        params = []
        if semester:
            sql += " AND s.semester = %s"
            params.append(semester)
        if year:
            sql += " AND s.year = %s"
            params.append(year)
        if course_filter:
            sql += " AND (c.course_number LIKE %s OR c.course_name LIKE %s)"
            like = f"%{course_filter}%"
            params.extend([like, like])
        sql += " ORDER BY s.year DESC, s.semester DESC, c.course_number"
        cur.execute(sql, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

@app.route('/student/courses', methods=['GET'])
def student_courses():
    """Manage Courses page: show current enrollments and allow dropping."""
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index'))

    student_id = session['user_id']
    # reuse enrollments helper
    enrollments = get_student_enrollments(student_id)
    # show only current (not completed) for management; keep completed separately if you wish
    current_enrolled = [e for e in enrollments if e['status'] == 'enrolled' or e['status'] == 'TBD']

    return render_template(
        'student/manage_courses.html',
        enrollments=current_enrolled,
        user_name=session.get('user_name')
    )


@app.route('/student/drop', methods=['POST'])
def student_drop():
    """Drop (mark dropped) an enrollment."""
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index'))

    student_id = session['user_id']
    enrollment_id = request.form.get('enrollment_id')
    if not enrollment_id:
        return redirect(url_for('student_courses'))

    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        # verify ownership and status
        cur.execute("SELECT status FROM Enrollment WHERE enrollmentID=%s AND studentID=%s", (enrollment_id, student_id))
        row = cur.fetchone()
        if not row:
            # nothing to drop
            cur.close()
            conn.close()
            return redirect(url_for('student_courses'))
        # perform logical drop
        cur.execute("UPDATE Enrollment SET status='dropped' WHERE enrollmentID=%s AND studentID=%s", (enrollment_id, student_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('student_courses'))


@app.route('/student/course-info', methods=['GET'])
def student_course_info():
    """
    Course Info page: show sections by semester/year or search by course number/name.
    Query params: semester, year, q (query for course)
    """
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index'))

    semester = request.args.get('semester') or 'Fall'
    year = request.args.get('year') or 2025
    q = request.args.get('q') or None

    sections = get_sections(semester=semester, year=year, course_filter=q)

    return render_template(
        'student/course_info.html',
        sections=sections,
        semester=semester,
        year=year,
        q=q,
        user_name=session.get('user_name')
    )


@app.route('/student/register', methods=['POST'])
def student_register():
    """
    Register the student in a section (POST).
    Expects form field 'section_id'.
    """
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index'))

    student_id = session['user_id']
    section_id = request.form.get('section_id')
    if not section_id:
        return redirect(url_for('student_course_info'))

    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)

        # 1) Check already enrolled in the section
        cur.execute("SELECT 1 AS found FROM Enrollment WHERE studentID=%s AND sectionID=%s AND status='enrolled'", (student_id, section_id))
        if cur.fetchone():
            cur.close()
            conn.close()
            # Already enrolled - redirect back with a simple flash message later; for now just redirect
            return redirect(url_for('student_course_info'))

        # 2) Check capacity
        cur.execute("SELECT capacity FROM Section WHERE sectionID=%s", (section_id,))
        row = cur.fetchone()
        capacity = row['capacity'] if row else None

        cur.execute("SELECT COUNT(*) AS cnt FROM Enrollment WHERE sectionID=%s AND status='enrolled'", (section_id,))
        cnt_row = cur.fetchone()
        enrolled_count = cnt_row['cnt'] if cnt_row else 0

        if capacity is not None and enrolled_count >= capacity:
            cur.close()
            conn.close()
            # Section full
            return redirect(url_for('student_course_info'))

        # 3) Insert enrollment
        cur.execute("INSERT INTO Enrollment (studentID, sectionID, grade, status) VALUES (%s,%s,'TBD','enrolled')", (student_id, section_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('student_courses'))



@app.route('/student/edit', methods=['GET', 'POST'])
def student_edit():
    if 'user_id' not in session or session.get('user_type') != 'student':
        return redirect(url_for('index'))

    student_id = session['user_id']

    if request.method == 'GET':
        profile = get_student_profile(student_id)
        return render_template('student/edit_profile.html', student=profile, user_name=session.get('user_name'))

    # POST -> only allow first_name, last_name, birth_date, password
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    birth_date = request.form.get('birth_date') or None
    new_password = request.form.get('password', '').strip()

    # basic validation
    if not first_name or not last_name:
        profile = get_student_profile(student_id)
        return render_template('student/edit_profile.html', student=profile,
                               error="First and last name are required.")

    conn = config.get_db_connection()
    try:
        cur = conn.cursor()

        # Build SQL dynamically to include password only if provided
        sql_parts = ["first_name = %s", "last_name = %s", "birth_date = %s"]
        params = [first_name, last_name, birth_date]

        if new_password:
            hashed = hashlib.sha256(new_password.encode('utf-8')).hexdigest()
            sql_parts.append("password = %s")
            params.append(hashed)

        params.append(student_id)
        sql = f"UPDATE Student SET {', '.join(sql_parts)} WHERE studentID = %s"
        cur.execute(sql, tuple(params))
        conn.commit()

        # update session user_name
        session['user_name'] = f"{first_name} {last_name}".strip()
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)