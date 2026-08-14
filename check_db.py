# 예전 로컬 SQLite 데이터가 남아 있는지 빠르게 확인하는 보조 스크립트입니다.
# 현재 서비스 데이터는 PostgreSQL이 기준이므로 운영 기능에는 사용하지 않습니다.
import sqlite3

conn = sqlite3.connect("chat.db")
cur = conn.cursor()

cur.execute("SELECT * FROM messages")

rows = cur.fetchall()

for row in rows:
    print(row)

conn.close()
