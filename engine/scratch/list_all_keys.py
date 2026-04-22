import sqlite3
import os

db_paths = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Trae\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Code - Insiders\User\globalStorage\state.vscdb"),
    os.path.expandvars(r"%APPDATA%\Code\User\globalStorage\state.vscdb"),
]

for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    print(f"--- DB: {db_path} ---")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT key FROM ItemTable").fetchall()
        for row in rows:
            k = row[0]
            if any(x in k.lower() for x in ['agent', 'auth', 'google', 'gemini', 'cloud', 'jetski']):
                print(k)
    finally:
        conn.close()
