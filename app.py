# app.py
from flask import Flask, render_template
import config

app = Flask(__name__)

@app.route('/')
def index():
    try:
        conn = config.get_db_connection()
        # query to make sure connection + database work
        cur = conn.cursor()
        cur.execute("SELECT DATABASE();")
        current_db = cur.fetchone()[0]
        cur.close()
        conn.close()
        return render_template('index.html', ok=True, message=f"Connected to database: {current_db}")
    except Exception as e:
        # show a helpful error — you can remove or log in production
        return render_template('index.html', ok=False, message=str(e))

if __name__ == '__main__':
    
    app.run(debug=True, host='127.0.0.1', port=5000)
