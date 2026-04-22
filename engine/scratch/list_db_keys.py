import sqlite3
import os

db_path = os.path.expandvars(r"%APPDATA%\Cursor\User\globalStorage\state.vscdb")
if not os.path.exists(db_path):
    print(f"File not found: {db_path}")
else:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT key FROM ItemTable").fetchall()
        for row in rows:
            if 'agent' in row[0].lower() or 'auth' in row[0].lower() or 'google' in row[0].lower():
                print(row[0])
    finally:
        conn.close()
