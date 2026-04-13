import sqlite3
import hashlib
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "attendance.db")

conn = sqlite3.connect(DATABASE)
cursor = conn.cursor()

# ================= USERS TABLE =================
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    department TEXT DEFAULT '',
    profile_image TEXT DEFAULT '',
    training_status TEXT DEFAULT 'untrained' CHECK(training_status IN ('trained', 'untrained', 'pending')),
    created_at TEXT DEFAULT (datetime('now'))
)
""")

# ================= ATTENDANCE TABLE =================
cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    check_in TEXT,
    check_out TEXT,
    status TEXT DEFAULT 'present' CHECK(status IN ('present', 'absent', 'late')),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
""")

# ================= PASSWORD RESET TOKENS TABLE =================
cursor.execute("""
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
)
""")

cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id)"
)
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at)"
)

# ================= MIGRATE: old employees table =================
# Check if old employees table exists and migrate data
try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='employees'")
    if cursor.fetchone():
        cursor.execute("SELECT id, name FROM employees")
        old_employees = cursor.fetchall()
        for emp_id, emp_name in old_employees:
            safe_email = emp_name.lower().replace(" ", ".") + "@facetrack.local"
            dummy_pw = hashlib.sha256("changeme123".encode()).hexdigest()
            cursor.execute("""
                INSERT OR IGNORE INTO users (name, email, password_hash, role, department, training_status)
                VALUES (?, ?, ?, 'user', 'General', 'trained')
            """, (emp_name, safe_email, dummy_pw))

        # Migrate attendance records
        cursor.execute("""
            SELECT a.employee_id, a.date, a.check_in, a.check_out
            FROM attendance a
            WHERE EXISTS (SELECT 1 FROM employees e WHERE e.id = a.employee_id)
        """)
        # We skip migrating old attendance to avoid conflicts since schema changed
        print(f"Migrated {len(old_employees)} employees to users table")
except Exception as e:
    print(f"Migration note: {e}")

# ================= SEED ADMIN =================
admin_pw = hashlib.sha256("admin123".encode()).hexdigest()
cursor.execute("""
    INSERT OR IGNORE INTO users (name, email, password_hash, role, department, training_status)
    VALUES ('Admin', 'admin@facetrack.com', ?, 'admin', 'Administration', 'trained')
""", (admin_pw,))

# ================= SEED DEMO USER =================
demo_pw = hashlib.sha256("user123".encode()).hexdigest()
cursor.execute("""
    INSERT OR IGNORE INTO users (name, email, password_hash, role, department, training_status)
    VALUES ('Demo User', 'user@facetrack.com', ?, 'user', 'Engineering', 'untrained')
""", (demo_pw,))

conn.commit()
conn.close()

print("=" * 50)
print("Database setup complete!")
print("=" * 50)
print("Admin login:  admin@facetrack.com / admin123")
print("User login:   user@facetrack.com  / user123")
print("=" * 50)

