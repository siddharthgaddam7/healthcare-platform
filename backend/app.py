"""
Healthcare Test Price Transparency Backend
==========================================
Routes:
  GET  /health         - server alive check
  GET  /mongo-test     - MongoDB connection check
  POST /login          - user/admin/doctor login
  POST /register       - new user registration
  POST /logout         - clear session
  GET  /me             - current user info
  GET  /tests          - list all canonical tests
  POST /search         - fuzzy search tests
  GET  /suggest        - autosuggest (Task 8)
  GET  /cart            - get user cart
  POST /cart/add        - add to cart
  POST /cart/remove     - remove from cart
  POST /cart/clear      - clear cart
  POST /forgot-password - initiate password reset (Task 3)
  POST /verify-reset    - verify security answer (Task 3)
  POST /reset-password  - reset password (Task 3)
  POST /book            - book a test (Task 4)
  GET  /bookings        - user bookings (Task 4)
  POST /bookings/cancel - cancel booking (Task 4)
  GET  /admin/users     - admin: list users
  GET  /doctor/profile  - doctor profile (Task 5)
  POST /doctor/profile  - update doctor profile (Task 5)
  GET  /doctor/appointments - doctor appointments (Task 5)
  POST /mfa/setup       - MFA setup (Task 6)
  POST /mfa/verify      - MFA verify (Task 6)
"""

import os
from dotenv import load_dotenv

# Ensure .env is loaded from the same directory as this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=env_path)

import json
import os
import string
import random
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Tuple

from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from rapidfuzz import fuzz

# ─── bcrypt for password hashing (Task 10) ───────────────────────────────────
import bcrypt
import resend

# ─── Email config (Resend HTTP API) ──────────────────────────────────────────
# Resend replaces Gmail SMTP — no socket/SMTP issues on Render.
RESEND_API_KEY      = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM         = os.environ.get("RESEND_FROM", "ClinixCompare <onboarding@resend.dev>").strip()
# All booking notifications go here (override via env for other deployments).
BOOKING_EMAIL_TO    = os.environ.get("BOOKING_EMAIL_TO", "siddharthgaddam34@gmail.com").strip()

_is_render = os.environ.get("RENDER", "").strip().lower() in ("true", "1", "yes")
_raw_test = os.environ.get("EMAIL_TEST_MODE", "").strip()
if _raw_test:
    EMAIL_TEST_MODE = _raw_test.lower() in ("true", "1", "yes")
else:
    EMAIL_TEST_MODE = not _is_render

_email_log = logging.getLogger("healthcare.email")
if not _email_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    _email_log.addHandler(_h)
_email_log.setLevel(logging.INFO)


def _redact_addr(addr: str) -> str:
    if not addr or "@" not in addr:
        return "(empty)"
    local, _, domain = addr.partition("@")
    if len(local) <= 2:
        return f"***@{domain}"
    return f"{local[:2]}***@{domain}"


def send_html_email(to_addrs: List[str], subject: str, html_body: str, log_label: str) -> Tuple[bool, str]:
    """
    Send HTML email via Resend HTTP API.
    Uses a simple HTTP POST — no SMTP sockets, no TLS negotiation,
    no Gunicorn worker timeout risk.

    Returns (success, client_safe_error_message).
    """
    to_addrs = [a.strip() for a in to_addrs if a and "@" in a.strip()]
    if not to_addrs:
        _email_log.error("%s: no valid recipient addresses", log_label)
        return False, "No recipient address configured."

    if not RESEND_API_KEY:
        _email_log.error("%s: RESEND_API_KEY not set", log_label)
        return False, "Email is not configured (RESEND_API_KEY missing)."

    _email_log.info(
        "%s: Resend API request started — from=%s to=%s subject=%s",
        log_label,
        _redact_addr(RESEND_FROM),
        [_redact_addr(a) for a in to_addrs],
        subject[:60],
    )

    try:
        resend.api_key = RESEND_API_KEY

        params: resend.Emails.SendParams = {
            "from": RESEND_FROM,
            "to": to_addrs,
            "subject": subject,
            "html": html_body,
        }

        response = resend.Emails.send(params)
        _email_log.info("%s: Resend API response: %s", log_label, response)

        # Resend returns {"id": "..."} on success
        if response and response.get("id"):
            _email_log.info("%s: Resend send OK — id=%s", log_label, response["id"])
            return True, ""
        else:
            _email_log.error("%s: Resend returned unexpected response: %s", log_label, response)
            return False, "Email API returned an unexpected response. Check server logs."

    except (SystemExit, KeyboardInterrupt) as e:
        _email_log.error("%s: email aborted by system signal (%s): %s", log_label, type(e).__name__, e)
        return False, "Email could not be sent (worker signal). The server is healthy."
    except BaseException as e:
        _email_log.error("%s: Resend API error: %s", log_label, e, exc_info=True)
        return False, f"Email could not be sent ({type(e).__name__}). Check server logs."


def send_booking_email(
    to_email: str,
    test_name: str,
    lab_name: str,
    patient_name: str,
    patient_email: str,
    patient_phone: str,
    booking_id: str,
):
    """
    Send booking notification via Resend API to BOOKING_EMAIL_TO only.
    ``to_email`` (lab address from DB) is included in the body for reference only.
    Returns (success: bool, error_message_for_client: str).
    """
    lab_record_email = (to_email or "").strip()
    subject = f"New Booking Request — {test_name} at {lab_name}"
    if EMAIL_TEST_MODE:
        subject = f"[TEST MODE] {subject}"

    html_body = f"""
    <h2>New Laboratory Booking Request</h2>
    <hr>
    <p><strong>Reference ID:</strong> {booking_id}</p>
    <p><strong>Test Name:</strong> {test_name}</p>
    <p><strong>Lab Name:</strong> {lab_name}</p>
    <p><strong>Lab email (from record, informational):</strong> {lab_record_email or "—"}</p>
    <hr>
    <h3>Patient Information:</h3>
    <p><strong>Name:</strong> {patient_name}</p>
    <p><strong>Email:</strong> {patient_email or 'Not provided'}</p>
    <p><strong>Phone:</strong> {patient_phone or 'Not provided'}</p>
    <br>
    <p>This message was sent to the configured operations inbox (not directly to the lab).</p>
    """

    return send_html_email(
        to_addrs=[BOOKING_EMAIL_TO],
        subject=subject,
        html_body=html_body,
        log_label=f"booking_id={booking_id}",
    )


# One-line startup summary (no secrets)
_email_log.info(
    "Email bootstrap (Resend API): render=%s email_test_mode=%s resend_key_set=%s from=%s booking_to_set=%s",
    _is_render,
    EMAIL_TEST_MODE,
    bool(RESEND_API_KEY),
    _redact_addr(RESEND_FROM),
    bool(BOOKING_EMAIL_TO),
)

# ─── MongoDB (Atlas) ───────────────────────────────────────────────────────────
# Use the same SRV connection string as before: Atlas → Database → Connect → Drivers.
# Resuming a paused cluster (e.g. Cluster0) does not change the host in that string unless
# Atlas shows a new one. Database name matches the original project: healthcare_platform.
mongo_db = None
try:
    from pymongo import MongoClient
    MONGO_URI = (os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "").strip()
    _db_name = (os.environ.get("MONGO_DB_NAME") or "healthcare_platform").strip()
    if MONGO_URI:
        # Longer timeout helps cold Atlas / TLS handshakes from Render workers.
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=15000)
        _client.admin.command("ping")
        mongo_db = _client[_db_name]
        print("[OK] MongoDB Atlas connected →", _db_name)
    else:
        print("[WARN] No MONGO_URI set — MongoDB disabled")
except Exception as e:
    print(f"[WARN] MongoDB connection failed: {e}")
    mongo_db = None

# ─── Fallback: pandas (only used if MongoDB is unavailable) ──────────────────
df = None
unique_tests = []
metadata = {}
norm_test_map = {}

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR  = os.path.join(BASE_DIR, "..", "frontend")
DATA_PATH     = os.path.join(BASE_DIR, "enriched_with_canonical_updated.xlsx")
METADATA_PATH = os.path.join(BASE_DIR, "test_metadata.json")

if mongo_db is None:
    # Fallback to pandas + Excel
    try:
        import pandas as pd
        print("[INFO] Loading Excel dataset as fallback:", DATA_PATH)
        df = pd.read_excel(DATA_PATH)
        df.columns = df.columns.str.strip().str.lower()
        df = df.dropna(subset=["price"])
        df["test name"]      = df["test name"].astype(str)
        df["canonical_name"] = df["canonical_name"].astype(str)
        unique_tests = df["test name"].unique()

        def normalize(text):
            if not isinstance(text, str): return ""
            text = text.lower().translate(str.maketrans("", "", string.punctuation))
            return text.replace(" ", "")
        norm_test_map = {normalize(t): t for t in unique_tests}

        # Load metadata
        try:
            with open(METADATA_PATH, "r") as f:
                raw = json.load(f)
            for k, v in raw.items():
                metadata[k] = {
                    "description":      v.get("short_description", ""),
                    "why_done":         v.get("why_it_is_done", ""),
                    "parameters":       v.get("parameters_measured", []),
                    "normal_range":     v.get("normal_range_summary", ""),
                    "fasting_required": v.get("fasting_required", ""),
                    "sample_type":      v.get("sample_type", ""),
                    "turnaround_time":  v.get("report_time", ""),
                    "preparation":      v.get("preparation_instructions", ""),
                }
            print(f"[OK] Metadata loaded: {len(metadata)} tests")
        except Exception as e:
            print(f"[WARN] Metadata load failed: {e}")
    except Exception as e:
        print(f"[WARN] Excel fallback failed: {e}")
else:
    print("[INFO] Using MongoDB for all data — Excel/pandas not needed")

# ─── Flask app ───────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "hyd_health_secret_2026")

# Cross-site session cookies: Vercel (HTTPS) calling Render (HTTPS) needs SameSite=None; Secure.
if os.environ.get("RENDER"):
    app.config["SESSION_COOKIE_SAMESITE"] = "None"
    app.config["SESSION_COOKIE_SECURE"] = True
else:
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False

def _normalize_cors_origin(origin: str) -> str:
    """Browser Origin has no path; strip accidental trailing slashes from env."""
    o = (origin or "").strip()
    return o.rstrip("/") if o else ""


_default_cors = [
    "http://localhost:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://127.0.0.1:10000",
    "http://localhost:10000",
    # ClinixCompare / Hyderabad Health — production + preview Vercel hostnames
    "https://healthcare-platform-gamma.vercel.app",
    "https://healthcare-platform-an0jzakti.vercel.app",
    "https://healthcare-platform.vercel.app",
]
_extra = os.environ.get("FRONTEND_ORIGINS", "").strip()
_extra_list = [o.strip() for o in _extra.split(",") if o.strip()] if _extra else []
_cors_origins = list(
    dict.fromkeys(
        x
        for x in (
            _normalize_cors_origin(o) for o in (_default_cors + _extra_list)
        )
        if x
    )
)

CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": _cors_origins}},
)


# ─── Helper: password hashing (Task 10) ─────────────────────────────────────
def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ─── Auth decorator ──────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "login required"}), 401
        return f(*args, **kwargs)
    return wrapper


# ─── Health + Mongo test ─────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "message": "Backend is running"})

@app.route("/mongo-test")
def mongo_test():
    if mongo_db is None:
        return jsonify({
            "connected": False,
            "error": "MONGO_URI not set or connection failed. Check your host's environment variables (e.g. Render)."
        }), 500
    try:
        collections = mongo_db.list_collection_names()
        stats = {col: mongo_db[col].count_documents({}) for col in collections}
        return jsonify({
            "connected":   True,
            "database":    mongo_db.name,
            "collections": collections,
            "doc_counts":  stats,
            "message":     "MongoDB Atlas is connected!"
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500


@app.route("/test-email")
def test_email():
    """Debug endpoint: send a test message via Resend API to BOOKING_EMAIL_TO.
    Wrapped with BaseException guard — always returns JSON, never crashes worker."""
    try:
        import traceback

        info = {
            "transport": "resend_api",
            "resend_key_configured": bool(RESEND_API_KEY),
            "resend_from": _redact_addr(RESEND_FROM),
            "booking_to_configured": bool(BOOKING_EMAIL_TO),
            "test_mode": EMAIL_TEST_MODE,
        }
        if not RESEND_API_KEY:
            info["status"] = "SKIPPED"
            info["error"] = "RESEND_API_KEY not set"
            return jsonify(info), 400
        if not BOOKING_EMAIL_TO:
            info["status"] = "SKIPPED"
            info["error"] = "BOOKING_EMAIL_TO not set"
            return jsonify(info), 400

        subject = "Healthcare Platform: Resend API test"
        if EMAIL_TEST_MODE:
            subject = "[TEST MODE] " + subject
        html = "<p><strong>Resend API test from Render.</strong></p><p>If you received this, the Resend API key and delivery are working.</p>"
        ok, err = send_html_email(
            to_addrs=[BOOKING_EMAIL_TO],
            subject=subject,
            html_body=html,
            log_label="test-email",
        )
        if ok:
            info["status"] = "SUCCESS"
            info["message"] = f"Check inbox at configured BOOKING_EMAIL_TO ({_redact_addr(BOOKING_EMAIL_TO)})."
            return jsonify(info)
        info["status"] = "FAILED"
        info["error"] = err
        try:
            info["traceback"] = traceback.format_exc()
        except Exception:
            pass
        return jsonify(info), 500

    except BaseException as exc:
        _email_log.error("test-email: unhandled %s: %s", type(exc).__name__, exc, exc_info=True)
        return jsonify({
            "status": "FAILED",
            "error": f"Email test aborted ({type(exc).__name__}). Worker survived.",
            "transport": "resend_api",
        }), 500


@app.route("/test-email-custom")
def test_email_custom():
    """Diagnostic: send Resend API test to the address in ?to= (must be valid email).
    Wrapped with BaseException guard — always returns JSON, never crashes worker."""
    try:
        to_email = request.args.get("to", "").strip()
        if not to_email or "@" not in to_email:
            return jsonify({"error": "Query param 'to' is required (e.g. /test-email-custom?to=your@email.com)"}), 400

        import traceback
        info = {
            "transport": "resend_api",
            "to_email": to_email,
            "resend_key_configured": bool(RESEND_API_KEY),
            "resend_from": _redact_addr(RESEND_FROM),
        }
        if not RESEND_API_KEY:
            info["status"] = "SKIPPED"
            info["error"] = "RESEND_API_KEY not set"
            return jsonify(info), 400

        subject = f"Healthcare Platform Resend diagnostic — {_redact_addr(to_email)}"
        html = f"<p><strong>Resend API diagnostic</strong></p><p>Requested recipient: {to_email}</p>"
        ok, err = send_html_email(
            to_addrs=[to_email],
            subject=subject,
            html_body=html,
            log_label="test-email-custom",
        )
        if ok:
            info["status"] = "SUCCESS"
            return jsonify(info)
        info["status"] = "FAILED"
        info["error"] = err
        info["traceback"] = traceback.format_exc()
        return jsonify(info), 500

    except BaseException as exc:
        _email_log.error("test-email-custom: unhandled %s: %s", type(exc).__name__, exc, exc_info=True)
        return jsonify({
            "status": "FAILED",
            "error": f"Email test aborted ({type(exc).__name__}). Worker survived.",
            "transport": "resend_api",
        }), 500

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES  (MongoDB-first, bcrypt passwords)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["POST"])
def login():
    data     = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    # Hardcoded admin
    if username == "admin" and password == "admin123":
        session["user_id"]  = "admin"
        session["username"] = "admin"
        session["role"]     = "admin"
        return jsonify({"success": True, "role": "admin"})

    if mongo_db is not None:
        user = mongo_db.users.find_one({"username": username})
        if user and check_password(password, user["password"]):
            session["user_id"]  = str(user["_id"])
            session["username"] = user["username"]
            session["role"]     = user.get("role", "user")
            # Check if MFA is enabled (Task 6)
            if user.get("mfa_enabled"):
                session["mfa_pending"] = True
                return jsonify({"success": True, "role": session["role"], "mfa_required": True})
            return jsonify({"success": True, "role": session["role"]})
        return jsonify({"error": "Invalid username or password"}), 401
    else:
        return jsonify({"error": "Database not available"}), 500


@app.route("/register", methods=["POST"])
def register():
    try:
        data     = request.get_json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        email    = data.get("email", "").strip()
        phone    = data.get("phone", "").strip()
        security_question = data.get("security_question", "").strip()
        security_answer   = data.get("security_answer", "").strip().lower()

        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        if len(password) < 4:
            return jsonify({"error": "Password must be at least 4 characters"}), 400

        if mongo_db is not None:
            # Check if username is taken
            if mongo_db.users.find_one({"username": username}):
                return jsonify({"error": "Username already taken"}), 409

            user_doc = {
                "username":          username,
                "password":          hash_password(password),
                "role":              "user",
                "email":             email,
                "phone":             phone,
                "security_question": security_question,
                "security_answer":   hash_password(security_answer) if security_answer else "",
                "mfa_enabled":       False,
                "created_at":        datetime.utcnow(),
            }
            result = mongo_db.users.insert_one(user_doc)
            session["user_id"]  = str(result.inserted_id)
            session["username"] = username
            session["role"]     = "user"
            return jsonify({"success": True, "role": "user"})
        else:
            return jsonify({"error": "Database not available"}), 500
    except Exception as e:
        print(f"[ERROR] Register failed: {e}")
        return jsonify({"error": f"Registration error: {str(e)}"}), 500


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/me")
def me():
    if session.get("user_id") is not None:
        return jsonify({
            "role":     session.get("role", "user"),
            "username": session.get("username")
        })
    return jsonify({"role": "guest"}), 401


# ═══════════════════════════════════════════════════════════════════════════════
#  FORGOT PASSWORD (Task 3)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    """Step 1: User provides username → get security question."""
    data = request.get_json()
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"error": "Username is required"}), 400

    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    user = mongo_db.users.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    sq = user.get("security_question", "")
    if not sq:
        return jsonify({"error": "No security question set. Please contact admin."}), 400

    return jsonify({"success": True, "security_question": sq, "username": username})


@app.route("/verify-reset", methods=["POST"])
def verify_reset():
    """Step 2: Verify security answer → issue reset token."""
    data = request.get_json()
    username = data.get("username", "").strip()
    answer   = data.get("security_answer", "").strip().lower()

    if not username or not answer:
        return jsonify({"error": "Username and answer required"}), 400

    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    user = mongo_db.users.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    stored_hash = user.get("security_answer", "")
    if not stored_hash or not check_password(answer, stored_hash):
        return jsonify({"error": "Incorrect answer"}), 401

    # Generate a one-time reset token
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    mongo_db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"reset_token": token, "reset_expires": datetime.utcnow() + timedelta(minutes=15)}}
    )
    return jsonify({"success": True, "reset_token": token})


@app.route("/reset-password", methods=["POST"])
def reset_password():
    """Step 3: Use reset token to set new password."""
    data     = request.get_json()
    username = data.get("username", "").strip()
    token    = data.get("reset_token", "").strip()
    new_pass = data.get("new_password", "").strip()

    if not username or not token or not new_pass:
        return jsonify({"error": "All fields required"}), 400
    if len(new_pass) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400

    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    user = mongo_db.users.find_one({"username": username, "reset_token": token})
    if not user:
        return jsonify({"error": "Invalid or expired token"}), 401

    if user.get("reset_expires") and user["reset_expires"] < datetime.utcnow():
        return jsonify({"error": "Reset token expired"}), 401

    mongo_db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password": hash_password(new_pass)}, "$unset": {"reset_token": "", "reset_expires": ""}}
    )
    return jsonify({"success": True, "message": "Password reset successful"})


# ═══════════════════════════════════════════════════════════════════════════════
#  MFA — Multi-Factor Authentication (Task 6)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/mfa/setup", methods=["POST"])
def mfa_setup():
    """Enable MFA for the logged-in user. Method: security_question."""
    if not session.get("user_id"):
        return jsonify({"error": "Login required"}), 401
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    data = request.get_json()
    method = data.get("method", "security_question")

    if method == "security_question":
        sq = data.get("security_question", "").strip()
        sa = data.get("security_answer", "").strip().lower()
        if not sq or not sa:
            return jsonify({"error": "Security question and answer required"}), 400

        from bson import ObjectId
        mongo_db.users.update_one(
            {"_id": ObjectId(session["user_id"])},
            {"$set": {
                "mfa_enabled": True,
                "mfa_method": "security_question",
                "security_question": sq,
                "security_answer": hash_password(sa),
            }}
        )
        return jsonify({"success": True, "message": "MFA enabled with security question"})

    elif method == "email_otp":
        # Generate a 6-digit OTP and store it
        otp = ''.join(random.choices(string.digits, k=6))
        from bson import ObjectId
        mongo_db.users.update_one(
            {"_id": ObjectId(session["user_id"])},
            {"$set": {
                "mfa_enabled": True,
                "mfa_method": "email_otp",
                "mfa_otp": otp,
                "mfa_otp_expires": datetime.utcnow() + timedelta(minutes=10),
            }}
        )
        # In production, send OTP via email. For now, return it.
        return jsonify({"success": True, "message": "MFA enabled with email OTP", "otp": otp})

    return jsonify({"error": "Invalid MFA method"}), 400


@app.route("/mfa/verify", methods=["POST"])
def mfa_verify():
    """Verify MFA after login."""
    if not session.get("user_id") or not session.get("mfa_pending"):
        return jsonify({"error": "No MFA verification pending"}), 400
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    data = request.get_json()
    from bson import ObjectId

    user_id = session["user_id"]
    if user_id == "admin":
        session.pop("mfa_pending", None)
        return jsonify({"success": True})

    user = mongo_db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"error": "User not found"}), 404

    method = user.get("mfa_method", "security_question")

    if method == "security_question":
        answer = data.get("security_answer", "").strip().lower()
        stored = user.get("security_answer", "")
        if not stored or not check_password(answer, stored):
            return jsonify({"error": "Incorrect answer"}), 401
        session.pop("mfa_pending", None)
        return jsonify({"success": True})

    elif method == "email_otp":
        otp = data.get("otp", "").strip()
        stored_otp = user.get("mfa_otp", "")
        expires = user.get("mfa_otp_expires")
        if otp != stored_otp:
            return jsonify({"error": "Incorrect OTP"}), 401
        if expires and expires < datetime.utcnow():
            return jsonify({"error": "OTP expired"}), 401
        session.pop("mfa_pending", None)
        # Clear used OTP
        mongo_db.users.update_one({"_id": ObjectId(user_id)}, {"$unset": {"mfa_otp": "", "mfa_otp_expires": ""}})
        return jsonify({"success": True})

    return jsonify({"error": "Unknown MFA method"}), 400


# ═══════════════════════════════════════════════════════════════════════════════
#  TESTS + SEARCH ROUTES  (MongoDB-first with alias support)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/tests")
def get_tests():
    if mongo_db is not None:
        tests = mongo_db.tests.distinct("canonical_name")
        return jsonify({"tests": sorted(tests)})
    # Fallback
    if df is not None:
        return jsonify({"tests": sorted(df["canonical_name"].unique().tolist())})
    return jsonify({"tests": []})


@app.route("/search", methods=["POST"])
def search():
    data  = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"results": []})

    if mongo_db is not None:
        return _search_mongo(query)
    elif df is not None:
        return _search_pandas(query)
    return jsonify({"results": []})


def _search_mongo(query):
    """Search using MongoDB with alias support (Task 7)."""
    nq = query.lower().translate(str.maketrans("", "", string.punctuation)).replace(" ", "")

    # Find matching canonical tests via aliases
    all_tests = list(mongo_db.tests.find({}, {"canonical_name": 1, "aliases": 1, "info": 1}))
    matched_canonicals = []

    for test_doc in all_tests:
        best_score = 0
        for alias in test_doc.get("aliases", []):
            na = alias.translate(str.maketrans("", "", string.punctuation)).replace(" ", "")
            score = (fuzz.token_sort_ratio(nq, na)
                   + fuzz.token_set_ratio(nq, na)
                   + fuzz.partial_ratio(nq, na)) / 3
            best_score = max(best_score, score)
        if best_score >= 70:
            matched_canonicals.append((test_doc, best_score))

    # Sort by match quality
    matched_canonicals.sort(key=lambda x: x[1], reverse=True)

    results = []
    for test_doc, _ in matched_canonicals:
        canonical = test_doc["canonical_name"]
        info = test_doc.get("info", {})

        # Get all labs for this canonical test (cheapest per lab)
        pipeline = [
            {"$match": {"canonical_name": canonical}},
            {"$group": {
                "_id": "$lab_name",
                "price":    {"$min": "$price"},
                "location": {"$first": "$location"},
                "phone":    {"$first": "$phone"},
                "email":    {"$first": "$email"},
                "website":  {"$first": "$website"},
                "address":  {"$first": "$address"},
            }},
            {"$sort": {"price": 1}},
        ]
        lab_results = list(mongo_db.labs.aggregate(pipeline))

        labs = [{
            "company":  lr["_id"],
            "location": lr.get("location", "Hyderabad"),
            "price":    lr["price"],
            "phone":    lr.get("phone", ""),
            "email":    lr.get("email", ""),
            "website":  lr.get("website", ""),
            "address":  lr.get("address", ""),
        } for lr in lab_results]

        if not labs:
            continue

        prices = [l["price"] for l in labs]
        results.append({
            "matched_test": canonical,
            "info": info,
            "statistics": {
                "min_price":   min(prices),
                "max_price":   max(prices),
                "avg_price":   round(sum(prices) / len(prices)),
                "min_company": labs[0]["company"],
                "max_company": labs[-1]["company"],
            },
            "results": labs,
        })

    return jsonify({"results": results})


def _search_pandas(query):
    """Fallback search using pandas (original logic)."""
    STOPWORDS = {"test", "panel", "function", "profile", "of", "the", "and", "in", "for"}
    nq = query.lower().translate(str.maketrans("", "", string.punctuation)).replace(" ", "")

    matches = set()
    for norm, orig in norm_test_map.items():
        score = (fuzz.token_sort_ratio(nq, norm)
               + fuzz.token_set_ratio(nq, norm)
               + fuzz.partial_ratio(nq, norm)) / 3
        if score >= 80:
            matches.add(orig)

    if not matches:
        return jsonify({"results": []})

    results = []
    seen = set()
    for match in matches:
        subset = df[df["test name"] == match]
        if subset.empty:
            continue
        canonical = subset.iloc[0]["canonical_name"]
        if canonical in seen:
            continue
        seen.add(canonical)
        grouped = subset.groupby("company name", as_index=False)["price"].min()
        labs = sorted([
            {"company": str(row["company name"]), "location": "Hyderabad", "price": int(row["price"])}
            for _, row in grouped.iterrows()
        ], key=lambda x: x["price"])
        prices = [l["price"] for l in labs]
        results.append({
            "matched_test": canonical,
            "info": metadata.get(canonical, {}),
            "statistics": {
                "min_price": min(prices), "max_price": max(prices),
                "avg_price": round(sum(prices) / len(prices)),
                "min_company": labs[0]["company"], "max_company": labs[-1]["company"],
            },
            "results": labs,
        })

    return jsonify({"results": results})


# ─── Autosuggest (Task 8) ────────────────────────────────────────────────────
@app.route("/suggest")
def suggest():
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify({"suggestions": []})

    if mongo_db is not None:
        # Search aliases for matches
        all_tests = list(mongo_db.tests.find({}, {"canonical_name": 1, "aliases": 1}))
        scored = []
        for t in all_tests:
            best = 0
            for alias in t.get("aliases", []):
                if q in alias:
                    best = max(best, 90)
                else:
                    best = max(best, fuzz.partial_ratio(q, alias))
            if best >= 60:
                scored.append((t["canonical_name"], best))
        scored.sort(key=lambda x: x[1], reverse=True)
        return jsonify({"suggestions": [s[0] for s in scored[:5]]})
    else:
        # Fallback
        if df is not None:
            names = sorted(df["canonical_name"].unique().tolist())
            matches = [n for n in names if q in n.lower()]
            return jsonify({"suggestions": matches[:5]})
    return jsonify({"suggestions": []})


# ═══════════════════════════════════════════════════════════════════════════════
#  CART ROUTES  (MongoDB)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/cart")
@login_required
def get_cart():
    if mongo_db is not None:
        items = list(mongo_db.carts.find({"user_id": session["user_id"]}))
        cart = [{
            "id":        str(i["_id"]),
            "test_name": i["test_name"],
            "company":   i["company"],
            "price":     i["price"],
        } for i in items]
        total = sum(i["price"] for i in cart)
        return jsonify({"cart": cart, "total": total})
    return jsonify({"cart": [], "total": 0})


@app.route("/cart/add", methods=["POST"])
@login_required
def add_cart():
    data = request.get_json()
    if mongo_db is not None:
        existing = mongo_db.carts.find_one({
            "user_id":   session["user_id"],
            "test_name": data["test_name"],
            "company":   data["company"],
        })
        if existing:
            return jsonify({"error": "Already in cart"}), 409
        mongo_db.carts.insert_one({
            "user_id":   session["user_id"],
            "test_name": data["test_name"],
            "company":   data["company"],
            "price":     data["price"],
            "added_at":  datetime.utcnow(),
        })
        return jsonify({"success": True})
    return jsonify({"error": "Database not available"}), 500


@app.route("/cart/remove", methods=["POST"])
@login_required
def remove_cart():
    data = request.get_json()
    if mongo_db is not None:
        from bson import ObjectId
        mongo_db.carts.delete_one({"_id": ObjectId(data["item_id"]), "user_id": session["user_id"]})
        return jsonify({"success": True})
    return jsonify({"error": "Database not available"}), 500


@app.route("/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    if mongo_db is not None:
        mongo_db.carts.delete_many({"user_id": session["user_id"]})
        return jsonify({"success": True})
    return jsonify({"error": "Database not available"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  BOOKING SYSTEM (Task 4)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/book", methods=["POST"])
@login_required
def book_test():
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    data = request.get_json()
    test_name = data.get("test_name", "").strip()
    lab_name  = data.get("lab_name", "").strip()
    mode      = data.get("mode", "direct_contact")  # "email_request" or "direct_contact"

    if not test_name or not lab_name:
        return jsonify({"error": "Test name and lab name required"}), 400

    # Get lab info for contact details
    lab = mongo_db.labs.find_one({"lab_name": lab_name, "canonical_name": test_name})
    price = lab["price"] if lab else 0

    booking_doc = {
        "user_id":    session["user_id"],
        "username":   session.get("username", ""),
        "test_name":  test_name,
        "lab_name":   lab_name,
        "price":      price,
        "mode":       mode,
        "status":     "confirmed" if mode == "direct_contact" else "pending",
        "created_at": datetime.utcnow(),
    }
    result = mongo_db.bookings.insert_one(booking_doc)
    booking_id = str(result.inserted_id)

    response = {
        "success": True,
        "booking_id": booking_id,
        "status": booking_doc["status"],
        "mode": mode,
    }

    # For direct contact mode, return lab phone + address
    if mode == "direct_contact" and lab:
        response["lab_phone"] = lab.get("phone", "")
        response["lab_address"] = lab.get("address", "")

    # For email request mode, send synchronously so we can report real success/failure
    if mode == "email_request":
        lab_email = lab.get("email", "") if lab else ""
        user = mongo_db.users.find_one({"_id": __import__('bson').ObjectId(session["user_id"])})
        patient_email = user.get("email", "") if user else ""
        patient_phone = user.get("phone", "") if user else ""
        ok, err_msg = send_booking_email(
            to_email=lab_email,
            test_name=test_name,
            lab_name=lab_name,
            patient_name=session.get("username", "Patient"),
            patient_email=patient_email,
            patient_phone=patient_phone,
            booking_id=booking_id,
        )
        response["email_sent"] = ok
        if not ok:
            response["email_error"] = err_msg

    return jsonify(response)


@app.route("/bookings")
@login_required
def get_bookings():
    if mongo_db is None:
        return jsonify({"bookings": []})

    bookings = list(mongo_db.bookings.find(
        {"user_id": session["user_id"]},
    ).sort("created_at", -1))

    return jsonify({"bookings": [{
        "id":         str(b["_id"]),
        "test_name":  b["test_name"],
        "lab_name":   b["lab_name"],
        "price":      b.get("price", 0),
        "mode":       b.get("mode", ""),
        "status":     b.get("status", "pending"),
        "created_at": b["created_at"].isoformat() if b.get("created_at") else "",
    } for b in bookings]})


@app.route("/bookings/cancel", methods=["POST"])
@login_required
def cancel_booking():
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500

    data = request.get_json()
    from bson import ObjectId
    booking_id = data.get("booking_id", "")

    result = mongo_db.bookings.update_one(
        {"_id": ObjectId(booking_id), "user_id": session["user_id"]},
        {"$set": {"status": "cancelled"}}
    )
    if result.modified_count:
        return jsonify({"success": True})
    return jsonify({"error": "Booking not found"}), 404


# ═══════════════════════════════════════════════════════════════════════════════
#  DOCTOR DASHBOARD (Task 5)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/doctor/profile")
@login_required
def get_doctor_profile():
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500
    if session.get("role") != "doctor":
        return jsonify({"error": "Access denied"}), 403

    from bson import ObjectId
    doctor = mongo_db.doctors.find_one({"user_id": session["user_id"]})
    if not doctor:
        return jsonify({"profile": None})

    return jsonify({"profile": {
        "name":             doctor.get("name", ""),
        "specialization":   doctor.get("specialization", ""),
        "hospital":         doctor.get("hospital", ""),
        "rating":           doctor.get("rating", 0),
        "patients_treated": doctor.get("patients_treated", 0),
        "reviews":          doctor.get("reviews", []),
    }})


@app.route("/doctor/profile", methods=["POST"])
@login_required
def update_doctor_profile():
    if mongo_db is None:
        return jsonify({"error": "Database not available"}), 500
    if session.get("role") != "doctor":
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json()
    update_fields = {}
    for field in ["name", "specialization", "hospital"]:
        if field in data:
            update_fields[field] = data[field]

    from bson import ObjectId
    mongo_db.doctors.update_one(
        {"user_id": session["user_id"]},
        {"$set": update_fields},
        upsert=True
    )
    return jsonify({"success": True})


@app.route("/doctor/appointments")
@login_required
def get_doctor_appointments():
    if mongo_db is None:
        return jsonify({"appointments": []})
    if session.get("role") != "doctor":
        return jsonify({"error": "Access denied"}), 403

    # Doctor sees all bookings
    bookings = list(mongo_db.bookings.find().sort("created_at", -1).limit(50))
    return jsonify({"appointments": [{
        "id":         str(b["_id"]),
        "username":   b.get("username", ""),
        "test_name":  b["test_name"],
        "lab_name":   b["lab_name"],
        "status":     b.get("status", "pending"),
        "created_at": b["created_at"].isoformat() if b.get("created_at") else "",
    } for b in bookings]})


@app.route("/doctor/reviews")
@login_required
def get_doctor_reviews():
    if mongo_db is None:
        return jsonify({"reviews": []})
    if session.get("role") != "doctor":
        return jsonify({"error": "Access denied"}), 403

    doctor = mongo_db.doctors.find_one({"user_id": session["user_id"]})
    if doctor:
        return jsonify({"reviews": doctor.get("reviews", [])})
    return jsonify({"reviews": []})


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/users")
@login_required
def admin_users():
    if session.get("role") != "admin":
        return jsonify({"error": "Admins only"}), 403

    if mongo_db is not None:
        users = list(mongo_db.users.find({"role": {"$ne": "admin"}}))
        user_list = []
        for u in users:
            uid = str(u["_id"])
            cart_items = list(mongo_db.carts.find({"user_id": uid}))
            cart_total = sum(i.get("price", 0) for i in cart_items)
            user_list.append({
                "id":         uid,
                "username":   u["username"],
                "role":       u.get("role", "user"),
                "joined":     u.get("created_at", "").isoformat() if u.get("created_at") else "",
                "cart_count":  len(cart_items),
                "cart_total":  cart_total,
            })
        return jsonify({"users": user_list})

    return jsonify({"users": []})


# ─── Serve frontend ──────────────────────────────────────────────────────────
@app.route("/")
def root():
    return send_from_directory(FRONTEND_DIR, "login.html")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)