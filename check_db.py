import sqlite3

conn = sqlite3.connect("chat.db")
cur = conn.cursor()

cur.execute("SELECT * FROM messages")

rows = cur.fetchall()

for row in rows:
    print(row)

conn.close()