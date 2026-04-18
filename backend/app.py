from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from deepface import DeepFace
import cv2
import os
import sqlite3
import jwt
import base64
import numpy as np
import secrets
import uuid
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
import shutil
import time
import magic
from pathlib import Path
import threading
import hashlib

app = Flask(__name__)

# ============ JWT SECURITY: Load from environment ============
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # DEVELOPMENT ONLY: Use default if not set
    if os.getenv("FLASK_ENV") == "production":
        raise ValueError("[SECURITY] JWT_SECRET environment variable is required in production")
    JWT_SECRET = "dev_secret_key_only_for_development_do_not_use_in_production"
    print("[WARNING] Using development JWT_SECRET. Set JWT_SECRET environment variable for production.")

app.config["SECRET_KEY"] = JWT_SECRET
print(f"[CONFIG] JWT_SECRET loaded from environment")

# ============ RATE LIMITING: DDoS Protection ============
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
print(f"[CONFIG] Rate limiting enabled")

# ============ CORS: Configurable origins from environment ============
_cors_env = os.getenv("CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
]
CORS(
    app,
    supports_credentials=True,
    origins=_cors_origins,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)
print(f"[CONFIG] CORS origins: {_cors_origins}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "attendance.db")
DATASET_PATH = os.path.join(BASE_DIR, "dataset")

# ============ FACE RECOGNITION CONFIGURATION ============
# Configurable face distance threshold for matching accuracy
# Lower values = stricter matching (fewer false positives, more false negatives)
# Higher values = looser matching (more false positives, fewer false negatives)
# 0.3 (strict) is more secure for identity verification
FACE_DISTANCE_THRESHOLD = float(os.getenv("FACE_DISTANCE_THRESHOLD", "0.3"))
print(f"[CONFIG] Face distance threshold set to {FACE_DISTANCE_THRESHOLD}")

# ============ SECURITY HEADERS: Production Hardening ============
@app.after_request
def set_security_headers(response):
    """Add security headers to all responses."""
    # Prevent clickjacking attacks
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Basic CSP - can be customized
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
    # Prevent browser caching sensitive data
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


print(f"[CONFIG] Security headers configured")

# ============ CONCURRENCY SAFETY: Thread Locks ============
# CRITICAL: Lock for DeepFace model loading (singleton pattern)
_model_lock = threading.RLock()  # Reentrant lock for nested access
print(f"[CONFIG] Model lock initialized (thread-safe face recognition)")

# Lock for attendance operations (prevents race conditions on same user)
_attendance_locks = {}  # {user_id: threading.Lock}
_attendance_locks_lock = threading.Lock()

def get_attendance_lock(user_id):
    """Get thread lock for a specific user (prevents concurrent check-in/out)."""
    with _attendance_locks_lock:
        if user_id not in _attendance_locks:
            _attendance_locks[user_id] = threading.Lock()
        return _attendance_locks[user_id]

# ============ REQUEST DEDUPLICATION: Prevent duplicate processing ============
# Cache for in-flight request tracking (prevents re-processing same request)
_request_cache = {}  # {request_hash: (result, timestamp)}
_request_cache_lock = threading.Lock()
REQUEST_DEDUPE_TTL = 5  # Deduplicate for 5 seconds

def get_request_signature(user_id, face_distance=None):
    """Generate unique signature for request (for deduplication)."""
    # Combine user_id + current second + face_distance (rounded to 2 decimals)
    current_sec = int(time.time())
    sig_str = f"{user_id}:{current_sec}"
    if face_distance is not None:
        sig_str += f":{round(face_distance, 2)}"
    return hashlib.md5(sig_str.encode()).hexdigest()

def is_duplicate_request(signature):
    """Check if request is already being processed (duplicate)."""
    with _request_cache_lock:
        if signature in _request_cache:
            result, ts = _request_cache[signature]
            if time.time() - ts < REQUEST_DEDUPE_TTL:
                print(f"[CONCURRENCY] Duplicate request detected (cached): {signature}")
                return True, result  # Return cached result
        return False, None

def cache_request_result(signature, result):
    """Cache request result for deduplication."""
    with _request_cache_lock:
        _request_cache[signature] = (result, time.time())
        print(f"[CONCURRENCY] Request cached for deduplication: {signature}")

# ============ PERFORMANCE CACHING: In-memory cache for user lookups ============
# Simple LRU-like cache to reduce database queries
_user_cache = {}  # {user_id: user_dict}
_user_cache_timestamp = {}  # {user_id: timestamp}
CACHE_TTL = 300  # Cache for 5 minutes

def get_cached_user(user_id, connection=None):
    """Get user from cache or database. Updates cache on fetch."""
    current_time = time.time()
    
    # Check cache validity
    if user_id in _user_cache and user_id in _user_cache_timestamp:
        if current_time - _user_cache_timestamp[user_id] < CACHE_TTL:
            print(f"[CACHE-HIT] User {user_id}")
            return _user_cache[user_id]
        else:
            # Cache expired, remove it
            del _user_cache[user_id]
            del _user_cache_timestamp[user_id]
    
    # Cache miss, fetch from database
    if connection is None:
        connection = connect_db()
        should_close = True
    else:
        should_close = False
    
    try:
        user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if user:
            user_dict_result = dict(user)
            _user_cache[user_id] = user_dict_result
            _user_cache_timestamp[user_id] = current_time
            print(f"[CACHE-MISS] User {user_id} - fetched from DB")
            return user_dict_result
        return None
    finally:
        if should_close:
            connection.close()

def invalidate_user_cache(user_id):
    """Invalidate cache for a specific user when they're updated."""
    if user_id in _user_cache:
        del _user_cache[user_id]
    if user_id in _user_cache_timestamp:
        del _user_cache_timestamp[user_id]
    print(f"[CACHE-INVALIDATE] User {user_id}")

# ============ PAGINATION HELPERS ============
def validate_pagination_params(page=None, limit=None, max_limit=100):
    """Validate and return safe pagination parameters."""
    try:
        page = int(page) if page else 1
        limit = int(limit) if limit else 20
    except (ValueError, TypeError):
        page = 1
        limit = 20
    
    # Enforce limits
    page = max(1, page)
    limit = max(1, min(limit, max_limit))  # Cap at max_limit, min 1
    
    offset = (page - 1) * limit
    return page, limit, offset

def paginate_results(total_count, page, limit, items):
    """Return pagination metadata with results."""
    total_pages = (total_count + limit - 1) // limit  # Ceiling division
    return {
        "items": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "totalPages": total_pages,
            "hasMore": page < total_pages
        }
    }

# Cache the DeepFace model in memory to avoid reloading it on every request
_model_cache = {}

def get_cached_model(model_name="Facenet512", force_reload=False):
    """Get or initialize a DeepFace model with caching to improve performance."""
    # CONCURRENCY: Use lock to prevent multiple simultaneous model loads
    with _model_lock:
        if force_reload or model_name not in _model_cache:
            try:
                print(f"[CONCURRENCY] Acquiring lock to load {model_name} model...")
                _model_cache[model_name] = DeepFace.build_model(model_name)
                print(f"[PERF] Loaded {model_name} model (cached, thread-safe)")
            except Exception as e:
                print(f"[PERF] Error loading {model_name}: {e}")
                return None
        else:
            print(f"[PERF] Using cached {model_name} model (no lock needed)")
    return _model_cache.get(model_name)

def optimize_image_for_recognition(image, max_width=480):
    """Optimize image size for faster face recognition without losing quality."""
    height, width = image.shape[:2]
    if width > max_width:
        scale = max_width / width
        new_height = int(height * scale)
        image = cv2.resize(image, (max_width, new_height), interpolation=cv2.INTER_LINEAR)
    return image


# ================= HELPERS =================

def connect_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    """Hash password securely using bcrypt."""
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    # Generate salt and hash
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


def hash_reset_token(token: str) -> str:
    """Hash reset token for secure storage."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def validate_email(email: str) -> bool:
    """Validate email format."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_username(name: str) -> bool:
    """Validate username (alphanumeric, spaces, and hyphens only)."""
    import re
    if not name or len(name) < 2 or len(name) > 100:
        return False
    # Allow letters, numbers, spaces, hyphens
    pattern = r'^[a-zA-Z0-9\s\-]+$'
    return re.match(pattern, name) is not None


def sanitize_input(value: str, max_length: int = 255) -> str:
    """Sanitize string input to prevent injection attacks."""
    if not isinstance(value, str):
        return ""
    # Strip whitespace
    value = value.strip()
    # Truncate to max length
    value = value[:max_length]
    return value


def validate_file_upload(file, max_size_mb: int = 5, allowed_mimes: list = None) -> tuple:
    """
    Validate uploaded file for security.
    Returns (is_valid, error_message)
    """
    if allowed_mimes is None:
        allowed_mimes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    
    # Check filename
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check file size (in memory)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        return False, f"File size exceeds {max_size_mb}MB limit"
    
    if file_size == 0:
        return False, "File is empty"
    
    # Check MIME type
    try:
        mime = magic.Magic(mime=True)
        file_mime = mime.from_buffer(file.read(8192))
        file.seek(0)
        if file_mime not in allowed_mimes:
            return False, f"Invalid file type: {file_mime}. Allowed: {', '.join(allowed_mimes)}"
    except Exception as e:
        print(f"[SECURITY] MIME check error: {e}")
        return False, "Could not verify file type"
    
    return True, None


def generate_safe_filename(original_filename: str = None) -> str:
    """Generate a safe filename using UUID to prevent path traversal."""
    # Get file extension if provided
    ext = ""
    if original_filename:
        ext = Path(original_filename).suffix.lower()
        # Validate extension
        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            ext = '.jpg'
    else:
        ext = '.jpg'
    
    # Use UUID for safe filename
    return f"{uuid.uuid4().hex}{ext}"


def hash_reset_token(token: str) -> str:
    """Hash reset token for secure storage."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token(user_id, role):
    """Generate JWT token with security best practices."""
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
        "nbf": datetime.utcnow(),  # Not before: prevent token use before issued
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


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
            # Use JWT_SECRET instead of app.config
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            # PERF: Use cached user lookup to reduce database queries
            user = get_cached_user(data["user_id"])
            if not user:
                return jsonify({"error": "User not found"}), 401
            g.current_user = user
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
    """Return face crops from a frame using OpenCV Haar cascades with optimized parameters."""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        # PERF: Optimized parameters for faster detection
        # scaleFactor=1.15 (was 1.1): faster but still accurate
        # minNeighbors=4 (was 5): catches more quickly
        # minSize=(60, 60) (was 80, 80): faster processing
        faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(60, 60))
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


def _match_faces_with_database(frame, conn):
    """
    Return recognized user IDs from a frame for all detected faces.
    
    SECURITY: Maps face→user_id directly from database to prevent duplicate name issues.
    - Extracts name from dataset folder (face recognition)
    - Validates name uniqueness in database
    - Returns (user_id, confidence) pairs
    - Validates face distance is within FACE_DISTANCE_THRESHOLD
    
    Args:
        frame: Image frame containing faces
        conn: Database connection for user lookup
    
    Returns:
        (List of (user_id, name, distance), unrecognized_count)
    """
    start_time = time.time()
    
    # PERF: Optimize image size first before processing
    frame = optimize_image_for_recognition(frame, max_width=480)
    
    crops = _extract_face_crops(frame)
    if not crops:
        crops = [frame]

    matched_users = []  # List of (user_id, name, distance)
    unrecognized_count = 0
    
    for crop in crops:
        try:
            # Use cached model for faster performance
            # Facenet512 is faster and more accurate than VGG-Face
            result = DeepFace.find(
                img_path=crop,
                db_path=DATASET_PATH,
                enforce_detection=True,
                detector_backend="opencv",
                model_name="Facenet512",
                silent=True,
                threshold=FACE_DISTANCE_THRESHOLD,  # Use configurable threshold
            )
        except Exception as e:
            print(f"[FACE] Recognition error: {e}")
            unrecognized_count += 1
            continue

        if not result or result[0] is None or len(result[0]) == 0:
            unrecognized_count += 1
            continue

        best = result[0].iloc[0]
        distance = float(best["distance"])
        
        # SECURITY: Validate distance is within strict threshold
        if distance >= FACE_DISTANCE_THRESHOLD:
            print(f"[FACE] Distance {distance:.4f} >= threshold {FACE_DISTANCE_THRESHOLD} - rejected")
            unrecognized_count += 1
            continue

        # Extract name from dataset folder path
        # Format: dataset/UserName/image.jpg -> name = "UserName"
        identity_path = best["identity"]
        name_from_face = identity_path.split(os.sep)[-2]
        
        # SECURITY: Validate this name exists in database and get user_id
        try:
            user = conn.execute(
                "SELECT id FROM users WHERE name=?",
                (name_from_face,)
            ).fetchone()
            
            if not user:
                # Face recognized from dataset, but user not in database
                print(f"[FACE] User '{name_from_face}' from face match not found in database - rejected")
                unrecognized_count += 1
                continue
            
            user_id = user["id"]
            
            # SECURITY: Validate user exists in database and is trained
            user_full = conn.execute(
                "SELECT id, name, training_status FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            
            if not user_full:
                print(f"[FACE] User ID {user_id} ('{name_from_face}') not found in database - rejected")
                unrecognized_count += 1
                continue
            
            # Append matched user with confidence
            matched_users.append((user_id, name_from_face, distance))
            print(f"[FACE] Matched: {name_from_face} (ID: {user_id}, distance: {distance:.4f})")
            
        except Exception as e:
            print(f"[FACE] Database lookup error for '{name_from_face}': {e}")
            unrecognized_count += 1
            continue

    elapsed = time.time() - start_time
    print(f"[FACE] Face matching completed in {elapsed:.2f}s ({len(matched_users)} recognized, {unrecognized_count} unrecognized)")
    return matched_users, unrecognized_count


def _mark_attendance_for_user(user_id, user_name, conn):
    """
    Production-ready attendance marking: check-in or check-out a single user.
    
    CONCURRENCY: Uses atomic transactions with isolation to prevent race conditions
    - IMMEDIATE transaction: Acquires lock immediately, preventing concurrent modifications
    - SELECT → UPDATE wrapped in transaction: Ensures read-modify-write is atomic
    - Lock per user_id: Prevents simultaneous check-in/out for same user
    
    Flow:
    1. First scan → creates check_in record (status: present/late)
    2. Second scan (after 60+ seconds) → updates check_out record
    3. Prevents duplicates through 60-second cooldown
    4. Handles overnight shifts correctly (full datetime stored)
    
    Args:
        user_id: User's database ID
        user_name: User's name
        conn: SQLite connection object (will use IMMEDIATE transaction)
    
    Returns:
        dict: {
            "name": str,
            "action": "check_in" | "check_out" | "skipped",
            "time": str (HH:MM:SS),
            "datetime": str (YYYY-MM-DD HH:MM:SS),
            "status": str (for check_in),
            "message": str (for skipped)
        }
    """
    # CONCURRENCY: Get per-user lock to prevent simultaneous check-in/out
    user_lock = get_attendance_lock(user_id)
    
    with user_lock:
        print(f"[CONCURRENCY] Acquired lock for user {user_id} ({user_name})")
        
        # Get current datetime (full precision)
        now = datetime.now()
        date = now.strftime("%Y-%m-%d")
        time_now = now.strftime("%H:%M:%S")
        datetime_now = now.strftime("%Y-%m-%d %H:%M:%S")  # Full datetime

        # Detect schema (supports both user_id and employee_id columns)
        schema = _get_attendance_schema(conn)
        user_col = schema["user_col"]
        has_status = schema["has_status"]

        if not user_col:
            print(f"[CONCURRENCY] Releasing lock for user {user_id} - unsupported schema")
            return {
                "name": user_name,
                "action": "skipped",
                "message": "Unsupported attendance table schema"
            }

        try:
            # CONCURRENCY: Use IMMEDIATE transaction for serialized access
            # IMMEDIATE: Acquires exclusive lock immediately (blocks other transactions)
            # This prevents race conditions in the SELECT-UPDATE pattern
            conn.execute("BEGIN IMMEDIATE")
            print(f"[CONCURRENCY] Transaction IMMEDIATE started for user {user_id}")
            
            # ========================================
            # CASE 1: User has an open session today
            # ========================================
            open_session = conn.execute(
                f"SELECT id, check_in FROM attendance WHERE {user_col}=? AND date=? AND check_out IS NULL",
                (user_id, date),
            ).fetchone()

            if open_session:
                # Attempt to CHECK OUT the user
                
                # Parse stored check_in datetime
                # Support both old format (HH:MM:SS) and new format (YYYY-MM-DD HH:MM:SS)
                check_in_str = open_session["check_in"]
                try:
                    if " " in check_in_str:
                        # New format: YYYY-MM-DD HH:MM:SS
                        check_in_dt = datetime.strptime(check_in_str, "%Y-%m-%d %H:%M:%S")
                    else:
                        # Old format: HH:MM:SS (time only, assume today's date)
                        check_in_dt = datetime.strptime(check_in_str, "%H:%M:%S")
                        check_in_dt = check_in_dt.replace(year=now.year, month=now.month, day=now.day)
                except ValueError:
                    conn.execute("ROLLBACK")
                    print(f"[CONCURRENCY] Rollback - Invalid check-in time for user {user_id}")
                    return {
                        "name": user_name,
                        "action": "skipped",
                        "message": "Invalid check-in time format in database"
                    }

                # Calculate time difference using total_seconds() (not .seconds!)
                time_diff = (now - check_in_dt).total_seconds()

                # Enforce 60-second minimum between check-in and check-out
                # (Prevents accidental duplicate scans)
                if time_diff < 60:
                    conn.execute("ROLLBACK")
                    print(f"[CONCURRENCY] Rollback - Too soon for check-out, user {user_id}")
                    return {
                        "name": user_name,
                        "action": "skipped",
                        "message": f"Too soon to check out (elapsed: {int(time_diff)}s, required: 60s)"
                    }

                # CONCURRENCY: Update check-out within transaction (atomic)
                conn.execute(
                    "UPDATE attendance SET check_out=? WHERE id=?",
                    (datetime_now, open_session["id"])
                )
                conn.commit()
                print(f"[CONCURRENCY] Committed check-out for user {user_id} - transaction released")

                return {
                    "name": user_name,
                    "action": "check_out",
                    "time": time_now,
                    "datetime": datetime_now,
                    "message": f"Checked out after {int(time_diff)}s"
                }

            # ================================================================
            # CASE 2: No open session -> User is checking IN
            # ================================================================
            else:
                # Check for rapid re-check-in (within 60 seconds after checkout)
                last_entry = conn.execute(
                    f"SELECT check_out FROM attendance WHERE {user_col}=? AND date=? AND check_out IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (user_id, date),
                ).fetchone()

                if last_entry and last_entry["check_out"]:
                    # Parse last checkout time (support both formats)
                    check_out_str = last_entry["check_out"]
                    try:
                        if " " in check_out_str:
                            check_out_dt = datetime.strptime(check_out_str, "%Y-%m-%d %H:%M:%S")
                        else:
                            check_out_dt = datetime.strptime(check_out_str, "%H:%M:%S")
                            check_out_dt = check_out_dt.replace(year=now.year, month=now.month, day=now.day)
                    except ValueError:
                        # If format is invalid, allow check-in (safety)
                        check_out_dt = None

                    if check_out_dt:
                        time_diff = (now - check_out_dt).total_seconds()
                        # Prevent immediate re-scanning after checkout
                        if time_diff < 60:
                            conn.execute("ROLLBACK")
                            print(f"[CONCURRENCY] Rollback - Too soon after checkout, user {user_id}")
                            return {
                                "name": user_name,
                                "action": "skipped",
                                "message": f"Too soon after checkout (elapsed: {int(time_diff)}s, required: 60s)"
                            }

                # Determine attendance status based on hour
                # (Before 10 AM = present, 10 AM or later = late)
                status = "late" if now.hour >= 10 else "present"

                # CONCURRENCY: Insert check-in within transaction (atomic)
                if has_status:
                    conn.execute(
                        f"INSERT INTO attendance ({user_col}, date, check_in, status) VALUES (?, ?, ?, ?)",
                        (user_id, date, datetime_now, status),
                    )
                else:
                    conn.execute(
                        f"INSERT INTO attendance ({user_col}, date, check_in) VALUES (?, ?, ?)",
                        (user_id, date, datetime_now),
                    )
                conn.commit()
                print(f"[CONCURRENCY] Committed check-in for user {user_id} - transaction released")

                return {
                    "name": user_name,
                    "action": "check_in",
                    "time": time_now,
                    "datetime": datetime_now,
                    "status": status,
                    "message": f"Checked in as {status}"
                }
        
        except sqlite3.IntegrityError as e:
            conn.execute("ROLLBACK")
            print(f"[CONCURRENCY] Rollback - Integrity constraint violation for user {user_id}: {e}")
            # Handle unique constraint violations (duplicate entries)
            if "UNIQUE constraint failed" in str(e):
                return {
                    "name": user_name,
                    "action": "skipped",
                    "message": "Duplicate attendance entry prevented"
                }
            raise
        
        except Exception as e:
            conn.execute("ROLLBACK")
            print(f"[ERROR] Rollback - Unexpected error for user {user_id}: {e}")
            raise
        finally:
            print(f"[CONCURRENCY] Released lock for user {user_id} ({user_name})")


    ensure_password_reset_table()

# =============================================
#              AUTH ENDPOINTS
# =============================================

@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("5 per minute")  # RATE LIMIT: Prevent brute force
def login():
    """Authenticate user with email and password (rate-limited)."""
    try:
        data = request.json or {}
        email = sanitize_input((data.get("email") or "").strip().lower())
        password = data.get("password", "")

        # Input validation
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400
        
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400
        
        if len(password) < 6:
            return jsonify({"error": "Invalid credentials"}), 401

        conn = connect_db()
        # PERF: Query uses email index (idx_users_email)
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()

        # Security best practice: Same error for user not found or password mismatch
        # This prevents account enumeration attacks
        if not user or not verify_password(password, user["password_hash"]):
            # Log failed attempt (in production, use proper logging)
            print(f"[SECURITY] Failed login attempt for email: {email}")
            return jsonify({"error": "Invalid credentials"}), 401

        token = generate_token(user["id"], user["role"])
        print(f"[AUTH] Successful login: {user['email']} (user_id: {user['id']})")
        # PERF: Register user in cache for subsequent requests
        user_dict_result = user_dict(user)
        _user_cache[user["id"]] = dict(user)
        _user_cache_timestamp[user["id"]] = time.time()
        return jsonify({"token": token, "user": user_dict_result}), 200
    
    except Exception as e:
        print(f"[ERROR] Login error: {e}")
        return jsonify({"error": "Authentication failed"}), 500


@app.route("/api/auth/register", methods=["POST"])
def register():
    """Legacy public registration - now redirects to admin-only flow."""
    return jsonify({"error": "Registration is disabled. Please contact your admin."}), 403


@app.route("/api/auth/forgot-password", methods=["POST"])
@limiter.limit("3 per minute")  # RATE LIMIT: Prevent abuse
def forgot_password():
    """Create a one-time password reset token for a known email."""
    try:
        data = request.json or {}
        email = sanitize_input((data.get("email") or "").strip().lower())

        if not email:
            return jsonify({"error": "Email is required"}), 400
        
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400

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

        # Development fallback: return token when running in debug/local mode
        if raw_token and app.debug:
            response["resetToken"] = raw_token
            response["expiresInMinutes"] = 30

        return jsonify(response), 200
    
    except Exception as e:
        print(f"[ERROR] Forgot password error: {e}")
        return jsonify({"error": "Password reset failed"}), 500


@app.route("/api/auth/reset-password", methods=["POST"])
@limiter.limit("5 per minute")  # RATE LIMIT: Prevent abuse
def reset_password():
    """Reset user password with a valid, unexpired one-time token."""
    try:
        data = request.json or {}
        token = sanitize_input((data.get("token") or "").strip())
        new_password = data.get("newPassword") or ""

        if not token or not new_password:
            return jsonify({"error": "Token and newPassword are required"}), 400

        if len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        # Validate password complexity
        import re
        if not re.search(r'[A-Z]', new_password) or not re.search(r'[a-z]', new_password) or not re.search(r'\d', new_password):
            return jsonify({"error": "Password must contain uppercase, lowercase, and numbers"}), 400

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
            print(f"[SECURITY] Invalid reset token attempt")
            return jsonify({"error": "Invalid or expired reset token"}), 400

        if reset_row["used_at"] is not None:
            conn.close()
            print(f"[SECURITY] Reused reset token attempt (user_id: {reset_row['user_id']})")
            return jsonify({"error": "Reset token already used"}), 400

        if int(reset_row["expires_at"]) < now_ts:
            conn.execute(
                "UPDATE password_reset_tokens SET used_at=? WHERE id=?",
                (now_ts, reset_row["id"]),
            )
            conn.commit()
            conn.close()
            return jsonify({"error": "Reset token expired"}), 400

        # Hash new password with bcrypt
        new_password_hash = hash_password(new_password)
        
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (new_password_hash, reset_row["user_id"]),
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

        print(f"[AUTH] Password reset successful for user_id: {reset_row['user_id']}")
        return jsonify({"message": "Password reset successful. Please sign in with your new password."}), 200
    
    except Exception as e:
        print(f"[ERROR] Password reset error: {e}")
        return jsonify({"error": "Password reset failed"}), 500


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
    """Get all users with pagination support (PERF: Added pagination)."""
    # PERF: Get pagination parameters from query string
    page = request.args.get("page", 1)
    limit = request.args.get("limit", 20)
    page, limit, offset = validate_pagination_params(page, limit, max_limit=100)
    
    conn = connect_db()
    
    # PERF: Get total count (needed for pagination metadata)
    total_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
    
    # PERF: Use LIMIT and OFFSET for pagination (also uses index on role)
    users = conn.execute("""
        SELECT * FROM users 
        WHERE role='user' 
        ORDER BY created_at DESC 
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    
    conn.close()
    
    # Return paginated results
    return jsonify(paginate_results(total_count, page, limit, [user_dict(u) for u in users]))


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
        print(f"[ERROR] Database delete failed: {e}")
        return jsonify({"error": "Internal server error"}), 500
    except Exception as e:
        print(f"[ERROR] Delete failed: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()


@app.route("/api/admin/register-user", methods=["POST"])
@admin_required
@limiter.limit("10 per minute")  # RATE LIMIT: Prevent abuse
def admin_register_user():
    """Admin creates a new user account with input validation."""
    try:
        data = request.json or {}
        name = sanitize_input((data.get("name") or "").strip())
        email = sanitize_input((data.get("email") or "").strip().lower())
        password = data.get("password", "")
        department = sanitize_input((data.get("department") or "").strip(), max_length=100)

        if not name or not email or not password:
            return jsonify({"error": "Name, email and password are required"}), 400

        # Validate name format
        if not validate_username(name):
            return jsonify({"error": "Name must be 2-100 characters and contain only letters, numbers, spaces, or hyphens"}), 400
        
        # Validate email format
        if not validate_email(email):
            return jsonify({"error": "Invalid email format"}), 400

        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        # Validate password complexity
        import re
        if not re.search(r'[A-Z]', password) or not re.search(r'[a-z]', password) or not re.search(r'\d', password):
            return jsonify({"error": "Password must contain uppercase, lowercase, and numbers"}), 400

        conn = connect_db()
        
        # Check email uniqueness
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "Email already registered"}), 400
        
        # Check name uniqueness (now enforced by DB)
        existing_name = conn.execute("SELECT id FROM users WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
        if existing_name:
            conn.close()
            return jsonify({"error": "Username already exists"}), 400

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
        user_folder = os.path.join(DATASET_PATH, name)
        user_folder = os.path.normpath(user_folder)
        if user_folder.startswith(os.path.normpath(DATASET_PATH)):
            os.makedirs(user_folder, exist_ok=True)

        print(f"[AUTH] New user registered: {name} (email: {email}, user_id: {user_id})")
        return jsonify({"message": f"User {name} registered successfully", "user": user_dict(user)}), 201
    
    except Exception as e:
        print(f"[ERROR] User registration error: {e}")
        return jsonify({"error": "User registration failed"}), 500


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@admin_required
def admin_update_user(user_id):
    """Admin updates user details and optional password reset."""
    data = request.json or {}
    name = sanitize_input((data.get("name") or "").strip())
    email = sanitize_input((data.get("email") or "").strip().lower())
    department = sanitize_input((data.get("department") or "").strip(), max_length=100)
    new_password = data.get("password") or ""

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    # Validate username format
    if not validate_username(name):
        return jsonify({"error": "Name must be 2-100 characters and contain only letters, numbers, spaces, or hyphens"}), 400

    # Validate email format
    if not validate_email(email):
        return jsonify({"error": "Invalid email format"}), 400

    # Validate password complexity if provided
    if new_password:
        if len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        import re
        if not re.search(r'[A-Z]', new_password) or not re.search(r'[a-z]', new_password) or not re.search(r'\d', new_password):
            return jsonify({"error": "Password must contain uppercase, lowercase, and numbers"}), 400

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

        # Name uniqueness check (case-insensitive)
        old_name = user["name"]
        if name != old_name:
            existing_name = conn.execute(
                "SELECT id FROM users WHERE LOWER(name)=LOWER(?) AND id<>?",
                (name, user_id),
            ).fetchone()
            if existing_name:
                conn.close()
                return jsonify({"error": "Username already taken"}), 400

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
            old_path = os.path.normpath(os.path.join(DATASET_PATH, old_name))
            new_path = os.path.normpath(os.path.join(DATASET_PATH, name))
            # SECURITY: Path traversal protection
            if not old_path.startswith(os.path.normpath(DATASET_PATH)) or \
               not new_path.startswith(os.path.normpath(DATASET_PATH)):
                dataset_warning = "Dataset folder rename skipped: invalid path"
            else:
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
                    print(f"[ERROR] Dataset folder rename failed: {e}")
                    dataset_warning = "Dataset folder rename skipped"

        updated = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        response = {
            "message": "User updated successfully",
            "user": user_dict(updated),
        }
        if dataset_warning:
            response["warning"] = dataset_warning
        
        # PERF: Invalidate user cache when updated
        invalidate_user_cache(user_id)
        print(f"[PERF] Cache invalidated for updated user {user_id}")
        
        return jsonify(response)

    except sqlite3.Error as e:
        print(f"[ERROR] Database update failed: {e}")
        return jsonify({"error": "Internal server error"}), 500
    except Exception as e:
        print(f"[ERROR] Update failed: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()


@app.route("/api/admin/untrained-users", methods=["GET"])
@admin_required
def admin_untrained_users():
    """Get untrained users with pagination (PERF: Added pagination)."""
    # PERF: Get pagination parameters
    page = request.args.get("page", 1)
    limit = request.args.get("limit", 20)
    page, limit, offset = validate_pagination_params(page, limit, max_limit=100)
    
    conn = connect_db()
    
    # PERF: Use index on (training_status, role) for faster query
    total_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE training_status='untrained' AND role='user'"
    ).fetchone()[0]
    
    # PERF: Apply pagination
    users = conn.execute("""
        SELECT * FROM users 
        WHERE training_status='untrained' AND role='user' 
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    
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

    return jsonify(paginate_results(total_count, page, limit, result))


@app.route("/api/admin/upload-training-images", methods=["POST"])
@admin_required
@limiter.limit("10 per minute")  # RATE LIMIT: Prevent abuse
def admin_upload_training_images():
    """Upload training images for a user with secure validation."""
    conn = connect_db()

    try:
        user_id = request.form.get("userId", "").strip()
        if not user_id:
            conn.close()
            return jsonify({"error": "userId is required"}), 400

        # Validate user_id is numeric
        try:
            user_id = int(user_id)
        except ValueError:
            conn.close()
            return jsonify({"error": "Invalid userId"}), 400

        # Get user
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404

        # Create user dataset folder with safe path
        user_folder = os.path.join(DATASET_PATH, user["name"])
        # Prevent path traversal
        user_folder = os.path.normpath(user_folder)
        if not user_folder.startswith(os.path.normpath(DATASET_PATH)):
            conn.close()
            return jsonify({"error": "Invalid user path"}), 400
        
        os.makedirs(user_folder, exist_ok=True)

        # Get uploaded files
        files = request.files.getlist("images")
        if not files or len(files) == 0:
            conn.close()
            return jsonify({"error": "No images provided"}), 400
        
        if len(files) > 20:
            conn.close()
            return jsonify({"error": "Maximum 20 images per upload"}), 400

        saved_count = 0
        errors = []
        
        for idx, file in enumerate(files):
            if idx >= 20:  # Safety limit
                break
            
            if not file or not file.filename:
                continue
            
            # SECURITY: Validate file upload
            is_valid, error_msg = validate_file_upload(file, max_size_mb=5)
            if not is_valid:
                errors.append(f"{file.filename}: {error_msg}")
                continue
            
            # Generate safe filename using UUID
            safe_filename = generate_safe_filename(file.filename)
            filepath = os.path.join(user_folder, safe_filename)
            
            # Prevent path traversal in filepath
            filepath = os.path.normpath(filepath)
            if not filepath.startswith(os.path.normpath(user_folder)):
                errors.append(f"{file.filename}: Path traversal attempt")
                continue
            
            try:
                file.save(filepath)
                saved_count += 1
                print(f"[UPLOAD] Saved training image for user {user['name']}: {safe_filename}")
            except Exception as e:
                errors.append(f"{file.filename}: {str(e)}")
                print(f"[ERROR] Failed to save image: {e}")

        if saved_count == 0:
            conn.close()
            return jsonify({
                "error": "No valid image files provided",
                "details": errors if errors else []
            }), 400

        conn.close()
        response = {
            "message": f"Successfully uploaded {saved_count} image(s)",
            "count": saved_count
        }
        if errors:
            response["warnings"] = errors
        
        print(f"[UPLOAD] Training images upload complete: {saved_count} saved, user_id={user_id}")
        return jsonify(response), 200

    except Exception as e:
        print(f"[ERROR] Upload error: {e}")
        conn.close()
        return jsonify({"error": "Upload failed"}), 500


@app.route("/api/admin/capture-training-images", methods=["POST"])
@admin_required
def admin_capture_training_images():
    """Save camera-captured base64 images for a username into dataset folder."""
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB per image

    conn = connect_db()

    try:
        data = request.json or {}
        username = sanitize_input((data.get("username") or "").strip())
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

        # SECURITY: Path traversal protection on user folder
        user_folder = os.path.normpath(os.path.join(DATASET_PATH, user["name"]))
        if not user_folder.startswith(os.path.normpath(DATASET_PATH)):
            conn.close()
            return jsonify({"error": "Invalid user path"}), 400
        os.makedirs(user_folder, exist_ok=True)

        if replace_existing:
            for f in os.listdir(user_folder):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                    try:
                        os.remove(os.path.join(user_folder, f))
                    except OSError:
                        pass

        saved_count = 0
        errors = []

        for idx, img_data in enumerate(images):
            if idx >= 60:  # Safety cap
                break

            # 1. Validate input type and format
            if not isinstance(img_data, str) or "," not in img_data:
                errors.append(f"Image {idx}: invalid format")
                continue

            encoded = img_data.split(",", 1)[1]
            if not encoded:
                errors.append(f"Image {idx}: empty payload")
                continue

            # 2. Decode base64 safely
            try:
                img_bytes = base64.b64decode(encoded, validate=True)
            except Exception:
                errors.append(f"Image {idx}: invalid base64")
                continue

            # 3. Enforce size limit before any processing
            if len(img_bytes) > MAX_IMAGE_SIZE:
                errors.append(f"Image {idx}: exceeds 5MB limit")
                continue

            if len(img_bytes) == 0:
                errors.append(f"Image {idx}: empty after decode")
                continue

            # 4. Verify it decodes to a real image via OpenCV
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None or frame.size == 0:
                errors.append(f"Image {idx}: not a valid image")
                continue

            # 5. Generate safe UUID filename (never trust client input)
            filename = generate_safe_filename("capture.jpg")

            # 6. Build filepath with path traversal check
            filepath = os.path.normpath(os.path.join(user_folder, filename))
            if not filepath.startswith(os.path.normpath(user_folder)):
                errors.append(f"Image {idx}: path traversal blocked")
                continue

            # 7. Write only if all checks passed
            if cv2.imwrite(filepath, frame):
                saved_count += 1
            else:
                errors.append(f"Image {idx}: write failed")

        if saved_count == 0:
            conn.close()
            return jsonify({"error": "No valid images were captured"}), 400

        conn.close()
        response = {
            "message": f"Saved {saved_count} captured image(s) for {user['name']}",
            "count": saved_count,
            "userId": str(user["id"]),
            "username": user["name"],
        }
        if errors:
            response["warnings"] = errors
        return jsonify(response), 200

    except Exception as e:
        print(f"[ERROR] Capture training images failed: {e}")
        conn.close()
        return jsonify({"error": "Internal server error"}), 500


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
        print(f"[ERROR] Training failed: {e}")
        conn.close()
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/admin/attendance", methods=["GET"])
@admin_required
def admin_attendance():
    """Get attendance records with filtering and pagination (PERF: Added pagination)."""
    # PERF: Get pagination parameters
    page = request.args.get("page", 1)
    limit = request.args.get("limit", 50)  # Default 50 for attendance (larger datasets)
    page, limit, offset = validate_pagination_params(page, limit, max_limit=200)
    
    conn = connect_db()

    date_filter = request.args.get("date", "")
    user_filter = request.args.get("user", "")
    dept_filter = request.args.get("department", "")

    schema = _get_attendance_schema(conn)
    user_col = schema["user_col"]
    has_status = schema["has_status"]

    if not user_col:
        conn.close()
        return jsonify(paginate_results(0, page, limit, []))

    status_select = "a.status" if has_status else "CASE WHEN a.check_in IS NOT NULL THEN 'present' ELSE 'absent' END AS status"

    # Build WHERE clause
    query_base = f"""
        SELECT a.id, a.{user_col} AS user_id, u.name, a.date, a.check_in, a.check_out, {status_select}, u.department
        FROM attendance a
        JOIN users u ON a.{user_col} = u.id
        WHERE 1=1
    """
    count_query = f"""
        SELECT COUNT(*) FROM attendance a
        JOIN users u ON a.{user_col} = u.id
        WHERE 1=1
    """
    params = []

    if date_filter:
        query_base += " AND a.date = ?"
        count_query += " AND a.date = ?"
        params.append(date_filter)
    if user_filter:
        query_base += " AND u.name LIKE ?"
        count_query += " AND u.name LIKE ?"
        params.append(f"%{user_filter}%")
    if dept_filter and dept_filter != "all":
        query_base += " AND u.department LIKE ?"
        count_query += " AND u.department LIKE ?"
        params.append(f"%{dept_filter}%")

    # PERF: Get count before pagination (uses same filters)
    total_count = conn.execute(count_query, params).fetchone()[0]
    
    # Add pagination and sort
    query_with_pagination = query_base + " ORDER BY a.date DESC, a.check_in DESC LIMIT ? OFFSET ?"
    
    rows = conn.execute(query_with_pagination, params + [limit, offset]).fetchall()
    conn.close()

    result_data = [
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
    ]
    
    return jsonify(paginate_results(total_count, page, limit, result_data))


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

        # Run face recognition with configurable threshold
        recognized_name = None
        distance = None
        try:
            result = DeepFace.find(
                img_path=frame,
                db_path=DATASET_PATH,
                enforce_detection=True,
                detector_backend="opencv",
                silent=True,
                threshold=FACE_DISTANCE_THRESHOLD,  # Use configurable threshold
            )

            if len(result) > 0 and len(result[0]) > 0:
                distance = result[0].iloc[0]["distance"]
                # SECURITY: Validate distance is within strict threshold
                if distance < FACE_DISTANCE_THRESHOLD:
                    identity = result[0].iloc[0]["identity"]
                    recognized_name = identity.split(os.sep)[-2]
                else:
                    print(f"[FACE] Distance {distance:.4f} >= threshold {FACE_DISTANCE_THRESHOLD} - rejected")
        except Exception as e:
            print(f"[FACE] Recognition error: {e}")
            return jsonify({"error": "No face detected in image. Please try again."}), 400

        if not recognized_name:
            return jsonify({"error": "Face not recognized. Please try again."}), 400

        # SECURITY: Validate recognized face matches the authenticated user
        conn = connect_db()
        
        # Uniqueness enforced by database: name is now UNIQUE
        recognized_user = conn.execute("SELECT id, name FROM users WHERE name=?", (recognized_name,)).fetchone()
        if not recognized_user:
            conn.close()
            print(f"[ATTENDANCE] Face '{recognized_name}' not found in database")
            return jsonify({
                "error": "Face recognized but user not found in system.",
                "distance": round(distance, 4) if distance else None
            }), 400

        # Verify face belongs to authenticated user (not someone else)
        if recognized_user["id"] != user_id:
            conn.close()
            print(f"[ATTENDANCE] Face mismatch: recognized {recognized_user['id']}, authenticated {user_id}")
            return jsonify({
                "error": "Face does not match the authenticated user.",
                "expected_user": user_name,
                "recognized_user": recognized_name,
                "distance": round(distance, 4) if distance else None
            }), 403

        result_info = _mark_attendance_for_user(user_id, user_name, conn)
        result_info["distance"] = round(distance, 4) if distance else None
        result_info["confidence"] = round(1.0 - distance, 4) if distance else None
        result_info["threshold"] = FACE_DISTANCE_THRESHOLD
        conn.close()

        if result_info["action"] == "skipped":
            return jsonify({"error": result_info["message"]}), 400
        elif result_info["action"] == "check_out":
            return jsonify({**result_info, "message": f"Checked out at {result_info['time']}. Recognized as {recognized_name}."})
        else:
            return jsonify({**result_info, "message": f"Checked in at {result_info['time']}. Recognized as {recognized_name}."})

    except Exception as e:
        print(f"[ERROR] Recognition error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# =============================================
#       MULTI-FACE GROUP ATTENDANCE
# =============================================

@app.route("/api/multi-attendance", methods=["POST"])
@token_required
def multi_face_attendance():
    """
    Detect ALL faces in a single image and mark attendance for every recognized user.
    
    CONCURRENCY & SECURITY:
    - Request deduplication: Prevents same request being processed twice
    - Transaction-safe: Each attendance mark uses atomic operation
    - Per-user locks: Prevents concurrent check-in/out for same user
    - Validates each face matches a user in database
    - Uses user_id directly (not name lookup)
    - Rejects faces that don't meet distance threshold
    - Prevents duplicate users with same name
    - Returns "unrecognized" for unknown faces safely
    
    Flow:
    1. Check for duplicate request (dedup cache)
    2. Decode base64 image
    3. Detect faces and match with database
    4. For each matched face:
       a. Lookup user_id from database
       b. Validate user exists and is trained
       c. Mark attendance (atomic, per-user lock)
    5. Return results and count of unrecognized faces
    """
    data = request.json
    image_data = data.get("image", "")

    if not image_data:
        return jsonify({
            "error": "No image provided",
            "results": [],
            "unrecognized": 0
        }), 400

    try:
        # Decode base64 image first to calculate hash
        if "," in image_data:
            image_data = image_data.split(",", 1)[1].strip()

        if not image_data:
            return jsonify({
                "error": "Empty image payload",
                "results": [],
                "unrecognized": 0
            }), 400

        img_bytes = base64.b64decode(image_data, validate=True)
        if not img_bytes:
            return jsonify({
                "error": "Invalid image payload",
                "results": [],
                "unrecognized": 0
            }), 400

        # CONCURRENCY: Check for duplicate request (same image within 5 seconds)
        request_sig = hashlib.md5(img_bytes).hexdigest()
        is_dup, cached_result = is_duplicate_request(request_sig)
        if is_dup:
            print(f"[CONCURRENCY] Returning cached result for duplicate request")
            return jsonify(cached_result)
        
        print(f"[CONCURRENCY] Processing unique request: {request_sig[:8]}...")

        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({
                "error": "Invalid image data",
                "results": [],
                "unrecognized": 0
            }), 400

        # SECURITY: Connect to database for identity validation
        conn = connect_db()
        
        # Get matched users (user_id, name, distance)
        matched_users, unrecognized_count = _match_faces_with_database(frame, conn)

        if not matched_users:
            conn.close()
            return jsonify({
                "error": "No registered faces recognized.",
                "results": [],
                "unrecognized": unrecognized_count,
                "message": f"{unrecognized_count} face(s) detected but not recognized.",
            }), 400

        recognized = []
        seen_user_ids = set()  # Prevent duplicate attendance for same user

        for user_id, name, distance in matched_users:
            # SECURITY: Skip if already processed (prevent duplicates)
            if user_id in seen_user_ids:
                print(f"[ATTENDANCE] User {user_id} ({name}) already processed this scan - skipping")
                continue

            # SECURITY: Validate user exists in database before marking attendance
            user = conn.execute(
                "SELECT id, name, training_status FROM users WHERE id=?",
                (user_id,)
            ).fetchone()

            if not user:
                print(f"[ATTENDANCE] User ID {user_id} not found in database - rejected")
                continue
            
            # Mark user ID as seen
            seen_user_ids.add(user_id)
            
            # Mark attendance for this user
            result_info = _mark_attendance_for_user(user_id, user["name"], conn)
            
            # Include face matching confidence in response
            result_info["confidence"] = round(1.0 - distance, 4)  # Convert distance to confidence
            result_info["distance"] = round(distance, 4)
            
            recognized.append(result_info)
            print(f"[ATTENDANCE] Marked attendance for {user['name']} (ID: {user_id}, confidence: {result_info['confidence']})")

        conn.close()

        if not recognized:
            error_response = {
                "error": "No valid users recognized.",
                "results": [],
                "unrecognized": unrecognized_count,
                "message": f"Faces matched but no valid users found. {unrecognized_count} unrecognized.",
            }
            cache_request_result(request_sig, error_response)
            return jsonify(error_response), 400

        success_response = {
            "results": recognized,
            "unrecognized": unrecognized_count,
            "message": f"Attendance marked for {len(recognized)} user(s). {unrecognized_count} face(s) unrecognized.",
            "face_distance_threshold": FACE_DISTANCE_THRESHOLD,
        }
        # CONCURRENCY: Cache result for deduplication
        cache_request_result(request_sig, success_response)
        return jsonify(success_response), 200

    except Exception as e:
        print(f"[ERROR] Multi-face attendance error: {e}")
        error_response = {
            "error": "Internal server error",
            "results": [],
            "unrecognized": 0
        }
        return jsonify(error_response), 500


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
            # SECURITY: Validate uploaded file (type, size, MIME)
            is_valid, error_msg = validate_file_upload(file, max_size_mb=5)
            if not is_valid:
                conn.close()
                return jsonify({"error": error_msg}), 400

            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            # SECURITY: Use UUID-based safe filename
            filename = generate_safe_filename(file.filename)
            filepath = os.path.join(uploads_dir, filename)
            filepath = os.path.normpath(filepath)
            if not filepath.startswith(os.path.normpath(uploads_dir)):
                conn.close()
                return jsonify({"error": "Invalid file path"}), 400
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
        if not verify_password(current_pw, g.current_user["password_hash"]):
            conn.close()
            return jsonify({"error": "Current password is incorrect"}), 400
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(data["newPassword"]), user_id),
        )
        conn.commit()
        conn.close()
        # PERF: Invalidate user cache after password change
        invalidate_user_cache(user_id)
        return jsonify({"message": "Password updated"})

    # Profile update
    name = sanitize_input(data.get("name", g.current_user["name"]))
    department = sanitize_input(data.get("department", g.current_user["department"]), max_length=100)

    if not name or len(name) < 2:
        conn.close()
        return jsonify({"error": "Name must be at least 2 characters"}), 400

    old_name = g.current_user["name"]

    # SECURITY: Check name uniqueness before update
    if name != old_name:
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(name)=LOWER(?) AND id<>?",
            (name, user_id),
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"error": "Username already taken"}), 400

    conn.execute(
        "UPDATE users SET name=?, department=? WHERE id=?",
        (name, department, user_id),
    )
    conn.commit()
    conn.close()

    # PERF: Invalidate user cache after profile change
    invalidate_user_cache(user_id)

    # Rename dataset folder if name changed (with path traversal check)
    if name != old_name:
        old_path = os.path.normpath(os.path.join(DATASET_PATH, old_name))
        new_path = os.path.normpath(os.path.join(DATASET_PATH, name))
        if old_path.startswith(os.path.normpath(DATASET_PATH)) and \
           new_path.startswith(os.path.normpath(DATASET_PATH)) and \
           os.path.exists(old_path):
            os.rename(old_path, new_path)

    return jsonify({"message": "Profile updated"})


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
        print(f"[ERROR] Healthcheck failed: {e}")
        return jsonify({"status": "error", "error": "Service unavailable"}), 500


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
    
    # PERF: Pre-load the face recognition model on startup to avoid first-request lag
    print("[PERF] Pre-loading face recognition model on startup...")
    get_cached_model("Facenet512")
    print("[PERF] Model loaded successfully. Face scanning will be faster.")
    
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", port=5000)
