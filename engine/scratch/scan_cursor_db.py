import sqlite3
import base64
import re

db_path = r'C:\Users\James\AppData\Roaming\Cursor\User\globalStorage\state.vscdb'
conn = sqlite3.connect(db_path)
try:
    cursor = conn.execute('SELECT key, value FROM ItemTable')
    for key, value in cursor:
        if 'token' in key.lower() or 'auth' in key.lower() or 'state' in key.lower():
            print(f"Key: {key}")
            # Try to see if it's a refresh token
            tokens = re.findall(r"1//[A-Za-z0-9_\-]{40,}", str(value))
            if tokens:
                print(f"  FOUND REFRESH TOKEN: {tokens[0][:10]}...")
finally:
    conn.close()
