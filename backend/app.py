from flask import Flask, request, jsonify, g
from flask_cors import CORS
from deepface import DeepFace
import cv2
import os
import sqlite3
import hashlib
import jwt
import base64
import numpy as np
import secrets
from datetime import datetime, timedelta
from functools import wraps
import shutil

app = Flask(__name__)
app.config["SECRET_KEY"] = "facetrack_jwt_secret_key_2024"

CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "attendance.db")
DATASET_PATH = os.path.join(BASE_DIR, "dataset")


# ================= HELPERS =================

def connect_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def hash_reset_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token(user_id, role):
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({"error": "Token is missing"}), 401

        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            conn = connect_db()
            user = conn.execute("SELECT * FROM users WHERE id=?", (data["user_id"],)).fetchone()
            conn.close()
            if not user:
                return jsonify({"error": "User not found"}), 401
            g.current_user = dict(user)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.current_user["role"] != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def user_dict(row):
    """Convert a user row to a safe dict (no password)."""
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "department": row["department"] or "",
        "profileImage": row["profile_image"] or "",
        "trainingStatus": row["training_status"],
        "createdAt": row["created_at"],
    }


def _get_attendance_schema(conn):
    """Return attendance table compatibility info for old/new schemas."""
    attendance_cols = {
        col["name"] for col in conn.execute("PRAGMA table_info(attendance)").fetchall()
    }
    user_col = "user_id" if "user_id" in attendance_cols else "employee_id" if "employee_id" in attendance_cols else None
    has_status = "status" in attendance_cols
    return {
        "user_col": user_col,
        "has_status": has_status,
    }


def ensure_password_reset_table():
    """Create password reset token table if it does not exist."""
    conn = connect_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at INTEGER NOT NULL,
            used_at INTEGER,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at)"
    )
    conn.commit()
    conn.close()


def _extract_face_crops(frame):
    """Return face crops from a frame using OpenCV Haar cascades."""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
    except Exception:
        faces = []

    crops = []
    for (x, y, w, h) in faces:
        pad = int(max(w, h) * 0.18)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        crop = frame[y1:y2, x1:x2]
        if crop.size > 0:
            crops.append(crop)
    return crops


def _match_faces_with_database(frame):
    """Return recognized identity names from a frame for all detected faces."""
    crops = _extract_face_crops(frame)
    if not crops:
        crops = [frame]

    identities = []
    unrecognized_count = 0
    for crop in crops:
        try:
            result = DeepFace.find(
                img_path=crop,
                db_path=DATASET_PATH,
                enforce_detection=True,
                detector_backend="opencv",
                silent=True,
            )
        except Exception:
            unrecognized_count += 1
            continue

        if not result or result[0] is None or len(result[0]) == 0:
            unrecognized_count += 1
            continue

        best = result[0].iloc[0]
        if best["distance"] >= 0.4:
            unrecognized_count += 1
            continue

        identity_path = best["identity"]
        name = identity_path.split(os.sep)[-2]
        identities.append(name)

    return identities, unrecognized_count


def _mark_attendance_for_user(user_id, user_name, conn):
    """Core helper: check-in or check-out a single user. Returns dict with result info."""
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    time_now = now.strftime("%H:%M:%S")

    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        return {"name": user_name, "action": "skipped", "message": "Unsupported attendance table schema"}

    open_session = conn.execute(
        f"SELECT id, check_in FROM attendance WHERE {user_col}=? AND date=? AND check_out IS NULL",
        (user_id, date),
    ).fetchone()

    if open_session:
        check_in_time = datetime.strptime(open_session["check_in"], "%H:%M:%S")
        diff = (now - now.replace(
            hour=check_in_time.hour,
            minute=check_in_time.minute,
            second=check_in_time.second,
        )).seconds
        if diff < 60:
            return {"name": user_name, "action": "skipped", "message": "Too soon to check out (< 1 min)"}
        conn.execute("UPDATE attendance SET check_out=? WHERE id=?", (time_now, open_session["id"]))
        conn.commit()
        return {"name": user_name, "action": "check_out", "time": time_now}
    else:
        last_entry = conn.execute(
            f"SELECT check_in, check_out FROM attendance WHERE {user_col}=? AND date=? ORDER BY id DESC LIMIT 1",
            (user_id, date),
        ).fetchone()
        if last_entry and last_entry["check_out"] is not None:
            last_check_out = datetime.strptime(last_entry["check_out"], "%H:%M:%S")
            if (now - now.replace(
                hour=last_check_out.hour,
                minute=last_check_out.minute,
                second=last_check_out.second,
            )).seconds < 60:
                return {"name": user_name, "action": "skipped", "message": "Too soon after checkout. Please wait a moment and try again."}

        status = "late" if now.hour >= 10 else "present"
        if has_status:
            conn.execute(
                f"INSERT INTO attendance ({user_col}, date, check_in, status) VALUES (?, ?, ?, ?)",
                (user_id, date, time_now, status),
            )
        else:
            conn.execute(
                f"INSERT INTO attendance ({user_col}, date, check_in) VALUES (?, ?, ?)",
                (user_id, date, time_now),
            )
        conn.commit()
        return {"name": user_name, "action": "check_in", "time": time_now, "status": status}


    ensure_password_reset_table()

# =============================================
#              AUTH ENDPOINTS
# =============================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    conn = connect_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if not user or user["password_hash"] != hash_password(password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = generate_token(user["id"], user["role"])
    return jsonify({"token": token, "user": user_dict(user)})


@app.route("/api/auth/register", methods=["POST"])
def register():
    """Legacy public registration - now redirects to admin-only flow."""
    return jsonify({"error": "Registration is disabled. Please contact your admin."}), 403


@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    """Create a one-time password reset token for a known email."""
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    conn = connect_db()
    now_ts = int(datetime.utcnow().timestamp())
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE expires_at < ? OR used_at IS NOT NULL",
        (now_ts,),
    )

    user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    raw_token = None

    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_reset_token(raw_token)
        expires_at = int((datetime.utcnow() + timedelta(minutes=30)).timestamp())

        conn.execute(
            "DELETE FROM password_reset_tokens WHERE user_id=?",
            (user["id"],),
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], token_hash, expires_at),
        )

    conn.commit()
    conn.close()

    response = {
        "message": "If an account with that email exists, a reset request has been created."
    }

    # Development fallback: return token when running in debug/local mode.
    if raw_token and app.debug:
        response["resetToken"] = raw_token
        response["expiresInMinutes"] = 30

    return jsonify(response)


@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    """Reset user password with a valid, unexpired one-time token."""
    data = request.json or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("newPassword") or ""

    if not token or not new_password:
        return jsonify({"error": "Token and newPassword are required"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    token_hash = hash_reset_token(token)
    now_ts = int(datetime.utcnow().timestamp())

    conn = connect_db()
    reset_row = conn.execute(
        """
        SELECT id, user_id, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash=?
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()

    if not reset_row:
        conn.close()
        return jsonify({"error": "Invalid or expired reset token"}), 400

    if reset_row["used_at"] is not None:
        conn.close()
        return jsonify({"error": "Reset token already used"}), 400

    if int(reset_row["expires_at"]) < now_ts:
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=? WHERE id=?",
            (now_ts, reset_row["id"]),
        )
        conn.commit()
        conn.close()
        return jsonify({"error": "Reset token expired"}), 400

    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hash_password(new_password), reset_row["user_id"]),
    )
    conn.execute(
        "UPDATE password_reset_tokens SET used_at=? WHERE id=?",
        (now_ts, reset_row["id"]),
    )
    conn.execute(
        "DELETE FROM password_reset_tokens WHERE user_id=? AND id<>?",
        (reset_row["user_id"], reset_row["id"]),
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Password reset successful. Please sign in with your new password."})


@app.route("/api/auth/me", methods=["GET"])
@token_required
def get_me():
    return jsonify(user_dict(g.current_user))


# =============================================
#            ADMIN ENDPOINTS
# =============================================

@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    conn = connect_db()
    today = datetime.now().strftime("%Y-%m-%d")

    total_users = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
    trained_users = conn.execute("SELECT COUNT(*) FROM users WHERE training_status='trained' AND role='user'").fetchone()[0]
    total_records = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]

    attendance_cols = {
        col["name"] for col in conn.execute("PRAGMA table_info(attendance)").fetchall()
    }
    attendance_user_col = "user_id" if "user_id" in attendance_cols else "employee_id" if "employee_id" in attendance_cols else None

    if attendance_user_col:
        today_attendance = conn.execute(
            f"SELECT COUNT(DISTINCT {attendance_user_col}) FROM attendance WHERE date=?",
            (today,),
        ).fetchone()[0]
    else:
        today_attendance = 0

    # Weekly trend (last 7 days)
    weekly_trend = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_name = (datetime.now() - timedelta(days=i)).strftime("%a")
        if attendance_user_col:
            count = conn.execute(
                f"SELECT COUNT(DISTINCT {attendance_user_col}) FROM attendance WHERE date=?",
                (d,),
            ).fetchone()[0]
        else:
            count = 0
        weekly_trend.append({"day": day_name, "count": count})

    # User growth (last 6 months)
    user_growth = []
    for i in range(5, -1, -1):
        d = datetime.now() - timedelta(days=i * 30)
        month_name = d.strftime("%b")
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at <= ? AND role='user'",
            (d.strftime("%Y-%m-%d 23:59:59"),),
        ).fetchone()[0]
        user_growth.append({"month": month_name, "users": count})

    conn.close()

    return jsonify({
        "totalUsers": total_users,
        "trainedUsers": trained_users,
        "todayAttendance": today_attendance,
        "totalRecords": total_records,
        "weeklyTrend": weekly_trend,
        "userGrowth": user_growth,
    })


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def admin_get_users():
    conn = connect_db()
    users = conn.execute("SELECT * FROM users WHERE role='user' ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([user_dict(u) for u in users])


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@admin_required
def admin_delete_user(user_id):
    conn = connect_db()
    dataset_cleanup_warning = None

    try:
        user = conn.execute("SELECT * FROM users WHERE id=? AND role='user'", (user_id,)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Best-effort dataset cleanup; do not block DB deletion on filesystem issues.
        user_dataset = os.path.join(DATASET_PATH, user["name"])
        if os.path.exists(user_dataset):
            try:
                shutil.rmtree(user_dataset)
            except Exception as e:
                dataset_cleanup_warning = f"Dataset folder cleanup skipped: {str(e)}"

        # Support both legacy and new attendance schemas.
        attendance_cols = {
            col["name"] for col in conn.execute("PRAGMA table_info(attendance)").fetchall()
        }
        if "user_id" in attendance_cols:
            conn.execute("DELETE FROM attendance WHERE user_id=?", (user_id,))
        elif "employee_id" in attendance_cols:
            conn.execute("DELETE FROM attendance WHERE employee_id=?", (user_id,))

        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()

        response = {"message": "User deleted successfully"}
        if dataset_cleanup_warning:
            response["warning"] = dataset_cleanup_warning
        return jsonify(response)

    except sqlite3.Error as e:
        return jsonify({"error": f"Database delete failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Delete failed: {str(e)}"}), 500
    finally:
        conn.close()


@app.route("/api/admin/register-user", methods=["POST"])
@admin_required
def admin_register_user():
    """Admin creates a new user account."""
    data = request.json
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    department = data.get("department", "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    conn = connect_db()
    existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Email already registered"}), 400

    pw_hash = hash_password(password)
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, department) VALUES (?, ?, ?, 'user', ?)",
        (name, email, pw_hash, department),
    )
    conn.commit()
    user_id = cursor.lastrowid

    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()

    # Create dataset directory for future face training
    os.makedirs(f"{DATASET_PATH}/{name}", exist_ok=True)

    return jsonify({"message": f"User {name} registered successfully", "user": user_dict(user)}), 201


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@admin_required
def admin_update_user(user_id):
    """Admin updates user details and optional password reset."""
    data = request.json or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    department = (data.get("department") or "").strip()
    new_password = data.get("password") or ""

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    if new_password and len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    conn = connect_db()
    dataset_warning = None

    try:
        user = conn.execute("SELECT * FROM users WHERE id=? AND role='user'", (user_id,)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        existing = conn.execute(
            "SELECT id FROM users WHERE email=? AND id<>?",
            (email, user_id),
        ).fetchone()
        if existing:
            return jsonify({"error": "Email already registered by another user"}), 400

        old_name = user["name"]

        conn.execute(
            "UPDATE users SET name=?, email=?, department=? WHERE id=?",
            (name, email, department, user_id),
        )

        if new_password:
            conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(new_password), user_id),
            )

        conn.commit()

        # Rename (or merge) dataset folder when user name changes.
        if name != old_name:
            old_path = os.path.join(DATASET_PATH, old_name)
            new_path = os.path.join(DATASET_PATH, name)
            try:
                if os.path.exists(old_path):
                    if not os.path.exists(new_path):
                        os.rename(old_path, new_path)
                    else:
                        for fname in os.listdir(old_path):
                            src = os.path.join(old_path, fname)
                            dst = os.path.join(new_path, fname)
                            if os.path.isfile(src) and not os.path.exists(dst):
                                shutil.move(src, dst)
                        shutil.rmtree(old_path, ignore_errors=True)
            except Exception as e:
                dataset_warning = f"Dataset folder rename skipped: {str(e)}"

        updated = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        response = {
            "message": "User updated successfully",
            "user": user_dict(updated),
        }
        if dataset_warning:
            response["warning"] = dataset_warning
        return jsonify(response)

    except sqlite3.Error as e:
        return jsonify({"error": f"Database update failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Update failed: {str(e)}"}), 500
    finally:
        conn.close()


@app.route("/api/admin/untrained-users", methods=["GET"])
@admin_required
def admin_untrained_users():
    conn = connect_db()
    users = conn.execute(
        "SELECT * FROM users WHERE training_status='untrained' AND role='user' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    result = []
    for u in users:
        user_folder = os.path.join(DATASET_PATH, u["name"])
        image_count = len(os.listdir(user_folder)) if os.path.exists(user_folder) else 0
        result.append({
            "id": str(u["id"]),
            "name": u["name"],
            "email": u["email"],
            "department": u["department"] or "",
            "images": image_count,
        })

    return jsonify(result)


@app.route("/api/admin/upload-training-images", methods=["POST"])
@admin_required
def admin_upload_training_images():
    """Upload training images for a user."""
    conn = connect_db()

    try:
        user_id = request.form.get("userId")
        if not user_id:
            conn.close()
            return jsonify({"error": "userId is required"}), 400

        # Get user
        user = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404

        # Create user dataset folder
        user_folder = os.path.join(DATASET_PATH, user["name"])
        os.makedirs(user_folder, exist_ok=True)

        # Get uploaded files
        files = request.files.getlist("images")
        if not files or len(files) == 0:
            conn.close()
            return jsonify({"error": "No images provided"}), 400

        saved_count = 0
        for file in files:
            if file and file.filename and file.filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                # Use timestamp to make filenames unique
                import time
                safe_name = os.path.basename(file.filename)
                filename = f"{int(time.time())}_{len(os.listdir(user_folder))}_{safe_name}"
                filepath = os.path.join(user_folder, filename)
                file.save(filepath)
                saved_count += 1

        if saved_count == 0:
            conn.close()
            return jsonify({"error": "No valid image files provided"}), 400

        conn.close()
        return jsonify({"message": f"Successfully uploaded {saved_count} image(s)", "count": saved_count}), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/capture-training-images", methods=["POST"])
@admin_required
def admin_capture_training_images():
    """Save camera-captured base64 images for a username into dataset folder."""
    conn = connect_db()

    try:
        data = request.json or {}
        username = (data.get("username") or "").strip()
        images = data.get("images") or []
        replace_existing = bool(data.get("replace", True))

        if not username:
            conn.close()
            return jsonify({"error": "username is required"}), 400

        if not isinstance(images, list) or len(images) == 0:
            conn.close()
            return jsonify({"error": "images array is required"}), 400

        if len(images) > 60:
            conn.close()
            return jsonify({"error": "Too many images in one request"}), 400

        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(name)=LOWER(?) AND role='user' LIMIT 1",
            (username,),
        ).fetchone()

        if not user:
            conn.close()
            return jsonify({"error": "User not found for provided username"}), 404

        user_folder = os.path.join(DATASET_PATH, user["name"])
        os.makedirs(user_folder, exist_ok=True)

        if replace_existing:
            for f in os.listdir(user_folder):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                    try:
                        os.remove(os.path.join(user_folder, f))
                    except OSError:
                        pass

        import time
        saved_count = 0

        for idx, img_data in enumerate(images):
            if not isinstance(img_data, str) or "," not in img_data:
                continue

            try:
                encoded = img_data.split(",", 1)[1]
                img_bytes = base64.b64decode(encoded)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                filename = f"capture_{int(time.time() * 1000)}_{idx}.jpg"
                filepath = os.path.join(user_folder, filename)
                if cv2.imwrite(filepath, frame):
                    saved_count += 1
            except Exception:
                continue

        if saved_count == 0:
            conn.close()
            return jsonify({"error": "No valid images were captured"}), 400

        conn.close()
        return jsonify(
            {
                "message": f"Saved {saved_count} captured image(s) for {user['name']}",
                "count": saved_count,
                "userId": str(user["id"]),
                "username": user["name"],
            }
        ), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/train", methods=["POST"])
@admin_required
def admin_train_model():
    """Train/retrain the face recognition model."""
    conn = connect_db()

    data = request.json or {}
    user_id = data.get("userId")

    try:
        eligible_users = 0
        trained_users = 0

        if user_id:
            # Retrain specific user
            user = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not user:
                conn.close()
                return jsonify({"error": "User not found"}), 404

            user_folder = os.path.join(DATASET_PATH, user["name"])
            if not (os.path.exists(user_folder) and len(os.listdir(user_folder)) > 0):
                conn.close()
                return jsonify({"error": "No training images found for this user"}), 400

            eligible_users = 1
            cursor = conn.execute(
                "UPDATE users SET training_status='trained' WHERE id=?", (int(user_id),)
            )
            trained_users = cursor.rowcount
            conn.commit()
        else:
            # Train all untrained users
            untrained = conn.execute(
                "SELECT * FROM users WHERE training_status='untrained' AND role='user'"
            ).fetchall()

            for u in untrained:
                user_folder = os.path.join(DATASET_PATH, u["name"])
                if os.path.exists(user_folder) and len(os.listdir(user_folder)) > 0:
                    eligible_users += 1
                    cursor = conn.execute(
                        "UPDATE users SET training_status='trained' WHERE id=?", (u["id"],)
                    )
                    trained_users += cursor.rowcount

            conn.commit()

            if eligible_users == 0:
                conn.close()
                return jsonify({"error": "No users have training images. Upload images first."}), 400

        # Force DeepFace to rebuild representations
        # by removing old pkl files
        for root, dirs, files in os.walk(DATASET_PATH):
            for f in files:
                if f.endswith(".pkl"):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        # Ignore locked cache files; model can still work.
                        pass

        conn.close()
        return jsonify({
            "message": "Training completed successfully",
            "eligibleUsers": eligible_users,
            "trainedUsers": trained_users,
        })

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/attendance", methods=["GET"])
@admin_required
def admin_attendance():
    conn = connect_db()

    date_filter = request.args.get("date", "")
    user_filter = request.args.get("user", "")
    dept_filter = request.args.get("department", "")

    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify([])

    status_select = "a.status" if has_status else "CASE WHEN a.check_in IS NOT NULL THEN 'present' ELSE 'absent' END AS status"

    query = f"""
        SELECT a.id, a.{user_col} AS user_id, u.name, a.date, a.check_in, a.check_out, {status_select}, u.department
        FROM attendance a
        JOIN users u ON a.{user_col} = u.id
        WHERE 1=1
    """
    params = []

    if date_filter:
        query += " AND a.date = ?"
        params.append(date_filter)
    if user_filter:
        query += " AND u.name LIKE ?"
        params.append(f"%{user_filter}%")
    if dept_filter and dept_filter != "all":
        query += " AND u.department LIKE ?"
        params.append(f"%{dept_filter}%")

    query += " ORDER BY a.date DESC, a.check_in DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([
        {
            "id": str(r["id"]),
            "userId": str(r["user_id"]),
            "userName": r["name"],
            "date": r["date"],
            "checkIn": r["check_in"],
            "checkOut": r["check_out"],
            "status": r["status"],
            "department": r["department"] or "",
        }
        for r in rows
    ])


@app.route("/api/admin/reports", methods=["GET"])
@admin_required
def admin_reports():
    conn = connect_db()
    period = request.args.get("period", "month")
    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    # Determine date range
    now = datetime.now()
    if period == "week":
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "quarter":
        start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    elif period == "year":
        start_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    else:
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    # Department attendance
    if user_col and has_status:
        dept_rows = conn.execute(f"""
            SELECT u.department,
                SUM(CASE WHEN a.status='present' OR a.status='late' THEN 1 ELSE 0 END) as present,
                SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absent
            FROM attendance a
            JOIN users u ON a.{user_col} = u.id
            WHERE a.date >= ?
            GROUP BY u.department
        """, (start_date,)).fetchall()
    elif user_col:
        dept_rows = conn.execute(f"""
            SELECT u.department,
                COUNT(*) as present,
                0 as absent
            FROM attendance a
            JOIN users u ON a.{user_col} = u.id
            WHERE a.date >= ?
            GROUP BY u.department
        """, (start_date,)).fetchall()
    else:
        dept_rows = []

    department_attendance = [
        {"department": r["department"] or "Unknown", "present": r["present"], "absent": r["absent"]}
        for r in dept_rows
    ]

    # Status distribution
    if has_status:
        status_rows = conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM attendance
            WHERE date >= ?
            GROUP BY status
        """, (start_date,)).fetchall()

        status_distribution = [
            {"name": r["status"].capitalize(), "value": r["cnt"]}
            for r in status_rows
        ]
    else:
        present_count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE date >= ? AND check_in IS NOT NULL",
            (start_date,),
        ).fetchone()[0]
        status_distribution = [{"name": "Present", "value": present_count}] if present_count > 0 else []

    # Monthly trend
    monthly_trend = []
    for i in range(5, -1, -1):
        d = now - timedelta(days=i * 30)
        month_start = d.replace(day=1).strftime("%Y-%m-%d")
        next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE date >= ? AND date < ?",
            (month_start, next_month),
        ).fetchone()[0]
        monthly_trend.append({"month": d.strftime("%b"), "attendance": count})

    conn.close()

    return jsonify({
        "departmentAttendance": department_attendance,
        "statusDistribution": status_distribution,
        "monthlyTrend": monthly_trend,
    })


# =============================================
#             USER ENDPOINTS
# =============================================

@app.route("/api/user/stats", methods=["GET"])
@token_required
def user_stats():
    user_id = g.current_user["id"]
    conn = connect_db()
    today = datetime.now().strftime("%Y-%m-%d")
    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify({
            "todayStatus": "not_marked",
            "totalPresent": 0,
            "totalAbsent": 0,
            "streak": 0,
        })

    # Today's status
    today_record = conn.execute(
        f"SELECT * FROM attendance WHERE {user_col}=? AND date=?", (user_id, today)
    ).fetchone()

    if today_record:
        today_status = today_record["status"] if has_status else "present"
    else:
        today_status = "not_marked"

    # Month stats
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    if has_status:
        present_count = conn.execute(
            f"SELECT COUNT(*) FROM attendance WHERE {user_col}=? AND date>=? AND (status='present' OR status='late')",
            (user_id, month_start),
        ).fetchone()[0]

        absent_count = conn.execute(
            f"SELECT COUNT(*) FROM attendance WHERE {user_col}=? AND date>=? AND status='absent'",
            (user_id, month_start),
        ).fetchone()[0]
    else:
        present_count = conn.execute(
            f"SELECT COUNT(*) FROM attendance WHERE {user_col}=? AND date>=? AND check_in IS NOT NULL",
            (user_id, month_start),
        ).fetchone()[0]
        absent_count = 0

    # Streak calculation
    streak = 0
    check_date = datetime.now()
    for _ in range(365):
        d = check_date.strftime("%Y-%m-%d")
        if has_status:
            has_attendance = conn.execute(
                f"SELECT id FROM attendance WHERE {user_col}=? AND date=? AND (status='present' OR status='late')",
                (user_id, d),
            ).fetchone()
        else:
            has_attendance = conn.execute(
                f"SELECT id FROM attendance WHERE {user_col}=? AND date=? AND check_in IS NOT NULL",
                (user_id, d),
            ).fetchone()
        if has_attendance:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    conn.close()

    return jsonify({
        "todayStatus": today_status,
        "totalPresent": present_count,
        "totalAbsent": absent_count,
        "streak": streak,
    })


@app.route("/api/user/mark-attendance", methods=["POST"])
@token_required
def user_mark_attendance():
    """Mark attendance via face recognition from webcam image."""
    user_id = g.current_user["id"]
    user_name = g.current_user["name"]
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    try:
        # Decode base64 image
        if "," in image_data:
            image_data = image_data.split(",")[1]

        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "Invalid image data"}), 400

        # Run face recognition
        recognized_name = None
        try:
            result = DeepFace.find(
                img_path=frame,
                db_path=DATASET_PATH,
                enforce_detection=True,
                detector_backend="opencv",
                silent=True,
            )

            if len(result) > 0 and len(result[0]) > 0:
                distance = result[0].iloc[0]["distance"]
                if distance < 0.4:
                    identity = result[0].iloc[0]["identity"]
                    recognized_name = identity.split(os.sep)[-2]
        except Exception:
            return jsonify({"error": "No face detected in image. Please try again."}), 400

        if not recognized_name:
            return jsonify({"error": "Face not recognized. Please try again."}), 400

        # Ensure the recognized identity matches the logged-in user (security safeguard).
        conn = connect_db()
        recognized_user = conn.execute("SELECT id, name FROM users WHERE name=?", (recognized_name,)).fetchone()
        if not recognized_user:
            conn.close()
            return jsonify({"error": "Face recognized but user not found in system."}), 400

        if recognized_user["id"] != user_id:
            conn.close()
            return jsonify({"error": "Face does not match the authenticated user."}), 403

        result_info = _mark_attendance_for_user(user_id, user_name, conn)
        conn.close()

        if result_info["action"] == "skipped":
            return jsonify({"error": result_info["message"]}), 400
        elif result_info["action"] == "check_out":
            return jsonify({"message": f"Checked out at {result_info['time']}. Recognized as {recognized_name}."})
        else:
            return jsonify({"message": f"Checked in at {result_info['time']}. Recognized as {recognized_name}."})

    except Exception as e:
        return jsonify({"error": f"Recognition error: {str(e)}"}), 500


# =============================================
#       MULTI-FACE GROUP ATTENDANCE
# =============================================

@app.route("/api/multi-attendance", methods=["POST"])
@token_required
def multi_face_attendance():
    """Detect ALL faces in a single image and mark attendance for every recognised user."""
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    try:
        if "," in image_data:
            image_data = image_data.split(",", 1)[1].strip()

        if not image_data:
            return jsonify({"error": "Empty image payload"}), 400

        img_bytes = base64.b64decode(image_data, validate=True)
        if not img_bytes:
            return jsonify({"error": "Invalid image payload"}), 400

        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "Invalid image data"}), 400

        identities, unrecognized_count = _match_faces_with_database(frame)

        if not identities:
            return jsonify({"error": "No registered faces recognized."}), 400

        conn = connect_db()
        recognized = []
        seen_users = set()

        for name in identities:
            user = conn.execute("SELECT id, name FROM users WHERE name=?", (name,)).fetchone()
            if not user or user["id"] in seen_users:
                if not user:
                    unrecognized_count += 1
                continue

            seen_users.add(user["id"])
            result_info = _mark_attendance_for_user(user["id"], user["name"], conn)
            recognized.append(result_info)

        conn.close()

        if not recognized:
            return jsonify({"error": "No registered faces recognized."}), 400

        return jsonify({
            "results": recognized,
            "unrecognized": unrecognized_count,
            "message": f"Attendance marked for {len(recognized)} user(s).",
        })

    except Exception as e:
        return jsonify({"error": f"Recognition error: {str(e)}"}), 500


@app.route("/api/user/attendance", methods=["GET"])
@token_required
def user_attendance():
    user_id = g.current_user["id"]
    conn = connect_db()
    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify([])

    date_filter = request.args.get("date", "")
    limit = request.args.get("limit", "")

    status_select = "a.status" if has_status else "CASE WHEN a.check_in IS NOT NULL THEN 'present' ELSE 'absent' END AS status"

    query = f"""
        SELECT a.id, a.{user_col} AS user_id, u.name, a.date, a.check_in, a.check_out, {status_select}
        FROM attendance a
        JOIN users u ON a.{user_col} = u.id
        WHERE a.{user_col} = ?
    """
    params = [user_id]

    if date_filter:
        query += " AND a.date = ?"
        params.append(date_filter)

    query += " ORDER BY a.date DESC, a.check_in DESC"

    if limit:
        query += " LIMIT ?"
        params.append(int(limit))

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([
        {
            "id": str(r["id"]),
            "userId": str(r["user_id"]),
            "userName": r["name"],
            "date": r["date"],
            "checkIn": r["check_in"],
            "checkOut": r["check_out"],
            "status": r["status"],
        }
        for r in rows
    ])


@app.route("/api/user/profile", methods=["GET"])
@token_required
def get_user_profile():
    u = g.current_user
    return jsonify({
        "name": u["name"],
        "email": u["email"],
        "department": u["department"] or "",
        "profileImage": u["profile_image"] or "",
    })


@app.route("/api/user/profile", methods=["PUT"])
@token_required
def update_user_profile():
    user_id = g.current_user["id"]
    conn = connect_db()

    # Handle multipart form (image upload)
    if request.content_type and "multipart" in request.content_type:
        file = request.files.get("image")
        if file:
            # Save profile image
            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            filename = f"profile_{user_id}_{int(datetime.now().timestamp())}.jpg"
            filepath = os.path.join(uploads_dir, filename)
            file.save(filepath)
            image_url = f"/static/uploads/{filename}"
            conn.execute("UPDATE users SET profile_image=? WHERE id=?", (image_url, user_id))
            conn.commit()
            conn.close()
            return jsonify({"profileImage": image_url})

    data = request.json or {}

    # Password change
    if data.get("newPassword"):
        current_pw = data.get("currentPassword", "")
        if g.current_user["password_hash"] != hash_password(current_pw):
            conn.close()
            return jsonify({"error": "Current password is incorrect"}), 400
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(data["newPassword"]), user_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "Password updated"})

    # Profile update
    name = data.get("name", g.current_user["name"])
    department = data.get("department", g.current_user["department"])

    old_name = g.current_user["name"]
    conn.execute(
        "UPDATE users SET name=?, department=? WHERE id=?",
        (name, department, user_id),
    )
    conn.commit()
    conn.close()

    # Rename dataset folder if name changed
    if name != old_name:
        old_path = os.path.join(DATASET_PATH, old_name)
        new_path = os.path.join(DATASET_PATH, name)
        if os.path.exists(old_path):
            os.rename(old_path, new_path)

    return jsonify({"message": "Profile updated"})


# =============================================
#        LEGACY ENDPOINTS (backward compat)
# =============================================

# =============================================
#        PUBLIC ATTENDANCE (NO AUTH)
# =============================================

@app.route("/api/public/mark-attendance", methods=["POST"])
def public_mark_attendance():
    """Public endpoint: recognise a single face and mark attendance (no login required)."""
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    try:
        if "," in image_data:
            image_data = image_data.split(",")[1]

        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "Invalid image data"}), 400

        recognized_name = None
        try:
            result = DeepFace.find(
                img_path=frame,
                db_path=DATASET_PATH,
                enforce_detection=True,
                detector_backend="opencv",
                silent=True,
            )
            if len(result) > 0 and len(result[0]) > 0:
                distance = result[0].iloc[0]["distance"]
                if distance < 0.4:
                    identity = result[0].iloc[0]["identity"]
                    recognized_name = identity.split(os.sep)[-2]
        except Exception:
            return jsonify({"error": "No face detected in image. Please try again."}), 400

        if not recognized_name:
            return jsonify({"error": "Face not recognized. Please try again."}), 400

        # Lookup user in DB
        conn = connect_db()
        user = conn.execute("SELECT id, name FROM users WHERE name=?", (recognized_name,)).fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "Face recognized but user not found in system."}), 400

        result_info = _mark_attendance_for_user(user["id"], user["name"], conn)
        conn.close()

        if result_info["action"] == "skipped":
            return jsonify({"error": result_info["message"]}), 400
        elif result_info["action"] == "check_out":
            return jsonify({"message": f"Checked out at {result_info['time']}. Welcome back, {recognized_name}!"})
        else:
            return jsonify({"message": f"Checked in at {result_info['time']}. Welcome, {recognized_name}!"})

    except Exception as e:
        return jsonify({"error": f"Recognition error: {str(e)}"}), 500


@app.route("/api/public/multi-attendance", methods=["POST"])
def public_multi_attendance():
    """Public endpoint: detect ALL faces in a single image and mark attendance (no login required)."""
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({"error": "No image provided"}), 400

    try:
        if "," in image_data:
            image_data = image_data.split(",", 1)[1].strip()

        if not image_data:
            return jsonify({"error": "Empty image payload"}), 400

        img_bytes = base64.b64decode(image_data, validate=True)
        if not img_bytes:
            return jsonify({"error": "Invalid image payload"}), 400

        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "Invalid image data"}), 400

        identities, unrecognized_count = _match_faces_with_database(frame)

        if not identities:
            return jsonify({"error": "No registered faces recognized."}), 400

        conn = connect_db()
        recognized = []
        seen_users = set()

        for name in identities:
            user = conn.execute("SELECT id, name FROM users WHERE name=?", (name,)).fetchone()
            if not user or user["id"] in seen_users:
                if not user:
                    unrecognized_count += 1
                continue

            seen_users.add(user["id"])
            result_info = _mark_attendance_for_user(user["id"], user["name"], conn)
            recognized.append(result_info)

        conn.close()

        if not recognized:
            return jsonify({"error": "No registered faces recognized."}), 400

        return jsonify({
            "results": recognized,
            "unrecognized": unrecognized_count,
            "message": f"Attendance marked for {len(recognized)} user(s).",
        })

    except Exception as e:
        return jsonify({"error": f"Recognition error: {str(e)}"}), 500


# =============================================
#              PUBLIC HEALTH ENDPOINTS
# =============================================

@app.route("/api/public/healthcheck", methods=["GET"])
def public_healthcheck():
    try:
        conn = connect_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return jsonify({
            "status": "ok",
            "message": "Service is up",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "1.0.0",
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/public/latest-attendance", methods=["GET"])
def public_latest_attendance():
    limit = request.args.get("limit", 10)
    try:
        limit = int(limit)
    except ValueError:
        limit = 10

    conn = connect_db()
    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify([])

    rows = conn.execute(
        f"""
            SELECT a.id, a.{user_col} AS user_id, u.name, a.date, a.check_in, a.check_out,
            {"a.status" if has_status else "CASE WHEN a.check_in IS NOT NULL THEN 'present' ELSE 'absent' END AS status"}
            FROM attendance a
            JOIN users u ON a.{user_col} = u.id
            ORDER BY a.id DESC
            LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return jsonify([
        {
            "id": str(r["id"]),
            "userId": str(r["user_id"]),
            "userName": r["name"],
            "date": r["date"],
            "checkIn": r["check_in"],
            "checkOut": r["check_out"],
            "status": r["status"],
        }
        for r in rows
    ])


@app.route("/api/admin/recognition-report", methods=["GET"])
@admin_required
def admin_recognition_report():
    conn = connect_db()
    now = datetime.now()
    thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify({
            "totalAttendance": 0,
            "uniqueUsers": 0,
            "checkIns": 0,
            "checkOuts": 0,
            "lateCount": 0,
            "dailyAverage": 0,
            "statusDistribution": [],
        })

    total = conn.execute(
        f"SELECT COUNT(*) as cnt FROM attendance WHERE date >= ?",
        (thirty_days_ago,),
    ).fetchone()["cnt"]

    unique_users = conn.execute(
        f"SELECT COUNT(DISTINCT {user_col}) as cnt FROM attendance WHERE date >= ?",
        (thirty_days_ago,),
    ).fetchone()["cnt"]

    checkins = conn.execute(
        f"SELECT COUNT(*) as cnt FROM attendance WHERE date >= ? AND check_in IS NOT NULL",
        (thirty_days_ago,),
    ).fetchone()["cnt"]

    checkouts = conn.execute(
        f"SELECT COUNT(*) as cnt FROM attendance WHERE date >= ? AND check_out IS NOT NULL",
        (thirty_days_ago,),
    ).fetchone()["cnt"]

    late_count = 0
    status_distribution = []

    if has_status:
        late_count = conn.execute(
            f"SELECT COUNT(*) as cnt FROM attendance WHERE date >= ? AND status='late'",
            (thirty_days_ago,),
        ).fetchone()["cnt"]

        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM attendance WHERE date >= ? GROUP BY status",
            (thirty_days_ago,),
        ).fetchall()

        status_distribution = [{"status": r["status"], "count": r["cnt"]} for r in status_rows]
    else:
        status_distribution = [{"status": "present", "count": checkins}]

    conn.close()

    daily_average = round(total / 30, 2) if total else 0

    return jsonify({
        "totalAttendance": total,
        "uniqueUsers": unique_users,
        "checkIns": checkins,
        "checkOuts": checkouts,
        "lateCount": late_count,
        "dailyAverage": daily_average,
        "statusDistribution": status_distribution,
    })


# =============================================
#              SERVE STATIC
# =============================================
@app.route("/static/uploads/<path:filename>")
def serve_upload(filename):
    return app.send_static_file(f"uploads/{filename}")


if __name__ == "__main__":
    # Ensure database exists
    if not os.path.exists(DATABASE):
        print("WARNING: Database not found. Run database_setup.py first.")
    app.run(debug=True, port=5000)
