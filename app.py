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

    # basic dashboard page
    return render_template('dashboard.html', user_name=session.get('user_name'), user_email=session.get('user_email'), user_type=session.get('user_type'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)