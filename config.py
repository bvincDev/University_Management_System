# config.py

import os
from dotenv import load_dotenv
load_dotenv()

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'bob')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'bobbobbody')
DB_NAME = os.getenv('DB_NAME', 'testdb')

def get_db_connection():
    """Return a mysql.connector connection connected to DB_NAME."""
    import mysql.connector
    
    # includes database name so it will fail if DB doesn't exist
    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8'
    )
    return conn
