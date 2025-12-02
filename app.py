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
    # If stored password is not a plain hex sha256, try werkzeug's check for salted hashes
    try:
        return bool(check_password_hash(stored, provided_password))
    except Exception:
        return False
    

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

    user_type = session.get('user_type')
    student_profile = None
    instructor_sections = None

    # student: load profile
    if user_type == 'student':
        try:
            student_profile = get_student_profile(session.get('user_id'))
        except Exception:
            student_profile = None

    # instructor: load sections taught (most recent first)
    if user_type == 'instructor':
        try:
            instructor_sections = get_instructor_sections(session.get('user_id'))
        except Exception:
            instructor_sections = []

    return render_template(
        'dashboard.html',
        user_name=session.get('user_name'),
        user_email=session.get('user_email'),
        user_type=user_type,
        student_profile=student_profile,
        my_sections=instructor_sections
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


# --- Instructor helpers ---
def get_instructor_sections(instr_id, semester=None, year=None):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sql = """
            SELECT
              s.sectionID, s.semester, s.year, s.capacity,
              c.courseID, c.course_name, c.course_number, c.credits,
              (SELECT COUNT(*) FROM Enrollment e WHERE e.sectionID = s.sectionID AND e.status='enrolled') AS enrolled_count,
              t.day_of_week, TIME_FORMAT(t.start_time, '%%H:%%i') AS start_time,
              TIME_FORMAT(t.end_time, '%%H:%%i') AS end_time,
              cl.room_number, b.building_name
            FROM Section s
            JOIN Course c ON s.courseID = c.courseID
            LEFT JOIN Timeslot t ON s.timeslotID = t.timeslotID
            LEFT JOIN Classroom cl ON s.classroomID = cl.classroomID
            LEFT JOIN Building b ON cl.buildingID = b.buildingID
            WHERE s.instructorID = %s
        """
        params = [instr_id]
        if semester:
            sql += " AND s.semester = %s"
            params.append(semester)
        if year:
            sql += " AND s.year = %s"
            params.append(year)
        sql += " ORDER BY s.year DESC, s.semester DESC, c.course_number"
        cur.execute(sql, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def get_section_roster(section_id):
    """Return roster for a section with enrollment info."""
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT e.enrollmentID, e.grade, e.status,
                   s.sectionID, s.semester, s.year,
                   st.studentID, st.first_name, st.last_name, st.email
            FROM Enrollment e
            JOIN Student st ON e.studentID = st.studentID
            JOIN Section s ON e.sectionID = s.sectionID
            WHERE e.sectionID = %s
            ORDER BY st.last_name, st.first_name
        """, (section_id,))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


# --- Instructor routes ---
# Grade mapping used in SQL CASE (update to your institution mapping if needed)
GRADE_CASE_SQL = """
  CASE
    WHEN e.grade = 'A' THEN 4.0
    WHEN e.grade = 'A-' THEN 3.7
    WHEN e.grade = 'B+' THEN 3.3
    WHEN e.grade = 'B' THEN 3.0
    WHEN e.grade = 'B-' THEN 2.7
    WHEN e.grade = 'C+' THEN 2.3
    WHEN e.grade = 'C' THEN 2.0
    WHEN e.grade = 'C-' THEN 1.7
    WHEN e.grade = 'D+' THEN 1.3
    WHEN e.grade = 'D' THEN 1.0
    WHEN e.grade = 'F' THEN 0.0
    ELSE NULL
  END
"""

def set_enrollment_grade(enrollment_id, grade):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE Enrollment SET grade = %s WHERE enrollmentID = %s", (grade, enrollment_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def remove_student_from_enrollment(enrollment_id):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        # You may choose to delete or mark dropped. We'll set status='dropped' for safety
        cur.execute("UPDATE Enrollment SET status = 'dropped' WHERE enrollmentID = %s", (enrollment_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def assign_advisor_to_student(student_id, advisor_id):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE Student SET advisorID = %s WHERE studentID = %s", (advisor_id, student_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def add_course_prereq(course_id, prereq_id):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT IGNORE INTO CoursePrerequisite (courseID, prereqCourseID) VALUES (%s, %s)", (course_id, prereq_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def remove_course_prereq(course_id, prereq_id):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM CoursePrerequisite WHERE courseID=%s AND prereqCourseID=%s", (course_id, prereq_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def get_all_courses():
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT courseID, course_number, course_name FROM Course ORDER BY course_number")
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def get_all_departments():
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT departmentID, department_name FROM Department ORDER BY department_name")
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def get_course_prereqs():
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
          SELECT cp.courseID, cp.prereqCourseID,
                 c.course_number, c.course_name,
                 p.course_number AS prereq_number, p.course_name AS prereq_name
          FROM CoursePrerequisite cp
          JOIN Course c ON cp.courseID = c.courseID
          JOIN Course p ON cp.prereqCourseID = p.courseID
          ORDER BY c.course_number
        """)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

# Reports / analytics helpers

def avg_grade_by_department(dept_id=None):
    """
    Return list of departments with average numeric GPA (based on enrollments for courses in that dept).
    If dept_id provided, filter to that department.
    """
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sql = f"""
          SELECT d.departmentID, d.department_name,
                 AVG({GRADE_CASE_SQL}) AS avg_gpa
          FROM Enrollment e
          JOIN Section s ON e.sectionID = s.sectionID
          JOIN Course c ON s.courseID = c.courseID
          JOIN Department d ON c.departmentID = d.departmentID
          WHERE e.grade IS NOT NULL AND e.grade NOT IN ('TBD', '')
        """
        params = []
        if dept_id:
            sql += " AND d.departmentID = %s"
            params.append(dept_id)
        sql += " GROUP BY d.departmentID, d.department_name ORDER BY d.department_name"
        cur.execute(sql, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def avg_grade_for_course_range(course_id, from_sem=None, from_year=None, to_sem=None, to_year=None):
    """
    Compute average numeric GPA for a course across a range. Semesters are strings like 'Fall'.
    Range filtering: we compare (year, semester) lexicographically — convert semester to ordering index.
    We'll use CASE to convert semester to a number (Spring=1, Summer=2, Fall=3).
    """
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sem_order_case = """
          CASE WHEN s.semester='Spring' THEN 1 WHEN s.semester='Summer' THEN 2 WHEN s.semester='Fall' THEN 3 ELSE 4 END
        """
        # build WHERE for course
        sql = f"""
          SELECT AVG({GRADE_CASE_SQL}) AS avg_gpa
          FROM Enrollment e
          JOIN Section s ON e.sectionID = s.sectionID
          WHERE s.courseID = %s
            AND e.grade IS NOT NULL AND e.grade NOT IN ('TBD','')
        """
        params = [course_id]
        # If from/to range provided, add composite comparisons
        # We'll translate (year, sem_order) to numbers: year * 10 + sem_order
        if from_year or to_year or from_sem or to_sem:
            def comp_value(year_field, sem_field):
                return f"(s.year * 10 + {sem_order_case})"
            # build low bound
            if from_year:
                from_sem_ord = {"Spring":1,"Summer":2,"Fall":3}.get(from_sem,1)
                low = int(from_year) * 10 + int(from_sem_ord)
                sql += f" AND ({comp_value('s.year','s.semester')}) >= %s"
                params.append(low)
            if to_year:
                to_sem_ord = {"Spring":1,"Summer":2,"Fall":3}.get(to_sem,3)
                high = int(to_year) * 10 + int(to_sem_ord)
                sql += f" AND ({comp_value('s.year','s.semester')}) <= %s"
                params.append(high)
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        return row
    finally:
        cur.close()
        conn.close()

def best_and_worst_classes(semester, year, top_n=5):
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sql = f"""
          SELECT c.courseID, c.course_number, c.course_name, AVG({GRADE_CASE_SQL}) AS avg_gpa
          FROM Enrollment e
          JOIN Section s ON e.sectionID = s.sectionID
          JOIN Course c ON s.courseID = c.courseID
          WHERE s.semester = %s AND s.year = %s AND e.grade IS NOT NULL AND e.grade NOT IN ('TBD','')
          GROUP BY c.courseID, c.course_number, c.course_name
          HAVING COUNT(e.enrollmentID) > 0
          ORDER BY avg_gpa DESC
          LIMIT %s
        """
        cur.execute(sql, (semester, year, top_n))
        top = cur.fetchall()

        sql_low = f"""
          SELECT c.courseID, c.course_number, c.course_name, AVG({GRADE_CASE_SQL}) AS avg_gpa
          FROM Enrollment e
          JOIN Section s ON e.sectionID = s.sectionID
          JOIN Course c ON s.courseID = c.courseID
          WHERE s.semester = %s AND s.year = %s AND e.grade IS NOT NULL AND e.grade NOT IN ('TBD','')
          GROUP BY c.courseID, c.course_number, c.course_name
          HAVING COUNT(e.enrollmentID) > 0
          ORDER BY avg_gpa ASC
          LIMIT %s
        """
        cur.execute(sql_low, (semester, year, top_n))
        bottom = cur.fetchall()

        return {"top": top, "bottom": bottom}
    finally:
        cur.close()
        conn.close()

def student_counts_by_department():
    """
    Returns list of departments with:
      - total_students: distinct students who have EVER enrolled in any course in that department
      - current_students: distinct students currently enrolled in enrolled status in that department
    """
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        sql = """
          SELECT d.departmentID, d.department_name,
            (SELECT COUNT(DISTINCT e2.studentID)
             FROM Enrollment e2
             JOIN Section s2 ON e2.sectionID = s2.sectionID
             JOIN Course c2 ON s2.courseID = c2.courseID
             WHERE c2.departmentID = d.departmentID) AS total_students,
            (SELECT COUNT(DISTINCT e3.studentID)
             FROM Enrollment e3
             JOIN Section s3 ON e3.sectionID = s3.sectionID
             JOIN Course c3 ON s3.courseID = c3.courseID
             WHERE c3.departmentID = d.departmentID AND e3.status = 'enrolled') AS current_students
          FROM Department d
          ORDER BY d.department_name
        """
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

# --- Instructor routes ---

@app.route('/instructor/sections')
def instructor_sections():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    semester = request.args.get('semester') or None
    year = request.args.get('year') or None
    q = request.args.get('q') or None

    instr_id = session['user_id']
    sections = get_instructor_sections(instr_id, semester=semester, year=year)
    return render_template('instructor/sections.html', sections=sections, user_name=session.get('user_name'),
                           semester=semester, year=year, q=q)

@app.route('/instructor/section/<int:section_id>/roster', methods=['GET'])
def instructor_section_roster(section_id):
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    # load section basic info
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
          SELECT s.sectionID, s.semester, s.year, s.capacity, c.courseID, c.course_number, c.course_name
          FROM Section s JOIN Course c ON s.courseID = c.courseID
          WHERE s.sectionID = %s AND s.instructorID = %s
        """, (section_id, session['user_id']))
        section = cur.fetchone()
        if not section:
            cur.close()
            conn.close()
            return redirect(url_for('instructor_sections'))

        roster = get_section_roster(section_id)
    finally:
        cur.close()
        conn.close()

    return render_template('instructor/section_roster.html', section=section, roster=roster, user_name=session.get('user_name'))

@app.route('/instructor/section/<int:section_id>/grades', methods=['POST'])
def instructor_bulk_update_grades(section_id):
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    # iterate posted fields; update grade_<enrollmentID>
    for key, value in request.form.items():
        if key.startswith('grade_'):
            enrollment_id = key.split('_', 1)[1]
            grade = value.strip()
            if grade:
                try:
                    set_enrollment_grade(enrollment_id, grade)
                except Exception:
                    # ignore single failures for now
                    pass

    return redirect(url_for('instructor_section_roster', section_id=section_id))

@app.route('/instructor/remove-student', methods=['POST'])
def instructor_remove_student():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    enrollment_id = request.form.get('enrollment_id')
    if enrollment_id:
        try:
            remove_student_from_enrollment(enrollment_id)
        except Exception:
            pass
    # redirect back - best-effort we don't have section id here, so send back to sections
    return redirect(url_for('instructor_sections'))

@app.route('/instructor/assign-advisor', methods=['POST'])
def instructor_assign_advisor():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    student_id = request.form.get('student_id')
    advisor_id = request.form.get('advisor_id')
    if student_id and advisor_id:
        try:
            assign_advisor_to_student(student_id, advisor_id)
        except Exception:
            pass
    return redirect(url_for('instructor_sections'))

@app.route('/instructor/prereqs', methods=['GET', 'POST'])
def instructor_prereqs():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action')
        course_id = request.form.get('course_id')
        prereq_id = request.form.get('prereq_id')
        try:
            if action == 'add':
                add_course_prereq(course_id, prereq_id)
            elif action == 'remove':
                remove_course_prereq(course_id, prereq_id)
        except Exception:
            pass
        return redirect(url_for('instructor_prereqs'))

    courses = get_all_courses()
    prereqs = get_course_prereqs()
    return render_template('instructor/prereqs.html', courses=courses, prereqs=prereqs, user_name=session.get('user_name'))


@app.route('/instructor/edit', methods=['GET', 'POST'])
def instructor_edit():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    instr_id = session['user_id']
    conn = config.get_db_connection()
    try:
        cur = conn.cursor(dictionary=True)

        if request.method == 'GET':
            cur.execute(
                "SELECT instructorID, first_name, last_name, email, birth_date, departmentID "
                "FROM Instructor WHERE instructorID=%s", (instr_id,)
            )
            instr = cur.fetchone()
            return render_template('instructor/edit_profile.html', instr=instr, user_name=session.get('user_name'))

        # --- POST: fetch current values from DB so we don't overwrite NOT NULL columns with None ---
        cur.execute(
            "SELECT instructorID, first_name, last_name, email, birth_date, departmentID "
            "FROM Instructor WHERE instructorID=%s", (instr_id,)
        )
        current = cur.fetchone()
        if not current:
            # something's wrong — instructor not found; redirect safely
            cur.close()
            conn.close()
            return redirect(url_for('dashboard'))

        # get posted values; if missing/empty, keep current DB value
        first = request.form.get('first_name', '').strip() or current['first_name']
        last  = request.form.get('last_name', '').strip()  or current['last_name']
        email = request.form.get('email', '').strip()      or current['email']

        # birth_date in DB is NOT NULL: if form leaves it blank, keep existing date
        birth_post = request.form.get('birth_date')
        birth = birth_post if birth_post and birth_post.strip() else current['birth_date']

        # departmentID in DB is NOT NULL: prefer posted value if provided else keep current
        dept_post = request.form.get('departmentID')
        # If dept_post is not empty string use it; else keep current value
        dept = int(dept_post) if dept_post and dept_post.strip() else current['departmentID']

        pwd = request.form.get('password', '').strip()

        # Basic validation (ensure minimum required fields are present)
        if not first or not last or not email:
            # render same page with error and current values (do not close cursor/conn here)
            return render_template('instructor/edit_profile.html',
                                   instr={
                                       "instructorID": current['instructorID'],
                                       "first_name": first,
                                       "last_name": last,
                                       "email": email,
                                       "birth_date": birth,
                                       "departmentID": dept
                                   },
                                   error="First, last and email required.",
                                   user_name=session.get('user_name'))

        # Build update query dynamically and parameters
        sql_parts = ["first_name=%s", "last_name=%s", "email=%s", "birth_date=%s", "departmentID=%s"]
        params = [first, last, email, birth, dept]

        if pwd:
            hashed = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            sql_parts.append("password=%s")
            params.append(hashed)

        params.append(instr_id)  # for WHERE clause
        sql = f"UPDATE Instructor SET {', '.join(sql_parts)} WHERE instructorID=%s"
        cur.execute(sql, tuple(params))
        conn.commit()

        # update session user_name
        session['user_name'] = f"{first} {last}".strip()

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/instructor/reports', methods=['GET'])
def instructor_reports():
    if 'user_id' not in session or session.get('user_type') != 'instructor':
        return redirect(url_for('index'))

    # common supporting data
    departments = get_all_departments()
    courses = get_all_courses()

    # possibly controlled by query params
    department_id = request.args.get('department_id')
    report = request.args.get('report')
    context = dict(departments=departments, courses=courses, user_name=session.get('user_name'),
                   department_id=int(department_id) if department_id else None)

    # Average by department (default)
    if request.args.get('department_id') or not report:
        dept_filter = int(department_id) if department_id else None
        context['avg_by_dept'] = avg_grade_by_department(dept_filter)

    # Course across range
    if request.args.get('report') == 'course_range':
        course_id = request.args.get('course_id')
        from_sem = request.args.get('from_semester')
        from_year = request.args.get('from_year')
        to_sem = request.args.get('to_semester')
        to_year = request.args.get('to_year')
        context['course_id'] = int(course_id) if course_id else None
        context['from_semester'] = from_sem
        context['from_year'] = from_year
        context['to_semester'] = to_sem
        context['to_year'] = to_year
        if course_id:
            context['avg_course_range'] = avg_grade_for_course_range(int(course_id), from_sem, from_year, to_sem, to_year)

    # Best & worst for semester
    if request.args.get('report') == 'best_worst':
        sem = request.args.get('semester')
        yr = request.args.get('year')
        if sem and yr:
            context['best_worst'] = best_and_worst_classes(sem, int(yr), top_n=5)
            context['year'] = int(yr)

    # Counts by department
    if request.args.get('report') == 'counts':
        context['counts'] = student_counts_by_department()

    return render_template('instructor/reports.html', **context)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)