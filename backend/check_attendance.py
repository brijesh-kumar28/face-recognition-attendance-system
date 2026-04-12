import sqlite3

conn = sqlite3.connect("attendance.db")
cursor = conn.cursor()

cursor.execute("SELECT * FROM attendance")
rows = cursor.fetchall()

if not rows:
    print("No attendance records found.")
else:
    for row in rows:
        print(f"ID: {row[0]}")
        print(f"Name: {row[1]}")
        print(f"Date: {row[2]}")
        print(f"Time: {row[3]}")
        print("-" * 30)

conn.close()
