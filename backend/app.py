"""
Healthcare Test Price Transparency Backend
==========================================
Routes:
  GET  /health         - server alive check
  GET  /mongo-test     - MongoDB connection check
  POST /login
  POST /register
  POST /logout
  GET  /me
  GET  /tests
  POST /search
  GET  /cart
  POST /cart/add
  POST /cart/remove
  POST /cart/clear
"""

import json
import os
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import pandas as pd
from rapidfuzz import fuzz
import string

# ─── MongoDB (optional — app works without it) ───────────────────────────────
mongo_db = None
try:
    from pymongo import MongoClient
    # Render env var is MONGO_URI (not MONGO_URL)
    MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL")
    if MONGO_URI:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")   # confirm it actually connects
        mongo_db = _client["healthcare_platform"]
        print("[OK] MongoDB Atlas connected")
    else:
        print("[INFO] No MONGO_URI set — MongoDB disabled")
except Exception as e:
    print(f"[WARN] MongoDB connection failed: {e}")
    mongo_db = None

# ─── Path setup ──────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
DATA_PATH    = os.path.join(BASE_DIR, "enriched_with_canonical (1).xlsx")
METADATA_PATH= os.path.join(BASE_DIR, "test_metadata.json")
DB_PATH      = os.path.join(BASE_DIR, "users.db")

# ─── Flask app ───────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.secret_key = "hyd_health_secret_2026"
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"]   = True

CORS(app, supports_credentials=True, resources={r"/*": {"origins": [
    "https://healthcare-platform-gamma.vercel.app",
    "https://healthcare-platform.vercel.app",
    "http://localhost:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]}})

# ─── SQLite setup ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role     TEXT DEFAULT 'user'
        )
    """)
    try:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except:
        pass   # column already exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER,
            test_name TEXT,
            company   TEXT,
            price     INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ─── Load dataset ────────────────────────────────────────────────────────────
def load_dataset():
    print("[INFO] Loading dataset:", DATA_PATH)
    df = pd.read_excel(DATA_PATH)
    df.columns = df.columns.str.strip().str.lower()
    for col in ["company name", "location", "test name", "canonical_name", "price"]:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
    df = df.dropna(subset=["price"])
    df["test name"]      = df["test name"].astype(str)
    df["canonical_name"] = df["canonical_name"].astype(str)
    return df

df           = load_dataset()
unique_tests = df["test name"].unique()

# ─── Load metadata ───────────────────────────────────────────────────────────
def load_metadata():
    try:
        with open(METADATA_PATH, "r") as f:
            raw = json.load(f)
        # Remap keys to what frontend expects
        result = {}
        for k, v in raw.items():
            result[k] = {
                "description":      v.get("short_description", ""),
                "why_done":         v.get("why_it_is_done", ""),
                "parameters":       v.get("parameters_measured", []),
                "normal_range":     v.get("normal_range_summary", ""),
                "fasting_required": v.get("fasting_required", ""),
                "sample_type":      v.get("sample_type", ""),
                "turnaround_time":  v.get("report_time", ""),
                "preparation":      v.get("preparation_instructions", ""),
            }
        print(f"[OK] Metadata loaded: {len(result)} tests")
        return result
    except Exception as e:
        print(f"[WARN] Metadata load failed: {e}")
        return {}

metadata = load_metadata()

# ─── Search helpers ──────────────────────────────────────────────────────────
STOPWORDS = {"test", "panel", "function", "profile", "of", "the", "and", "in", "for"}

def normalize(text):
    if not isinstance(text, str): return ""
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return text.replace(" ", "")

norm_test_map = {normalize(t): t for t in unique_tests}

def find_all_matches(query):
    results = set()
    nq = normalize(query)
    for norm, orig in norm_test_map.items():
        score = (fuzz.token_sort_ratio(nq, norm)
               + fuzz.token_set_ratio(nq, norm)
               + fuzz.partial_ratio(nq, norm)) / 3
        if score >= 80:
            results.add(orig)
    return list(results)

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
            "error": "MONGO_URI not set or connection failed. Check Render environment variables."
        }), 500
    try:
        collections = mongo_db.list_collection_names()
        stats = {col: mongo_db[col].count_documents({}) for col in collections}
        return jsonify({
            "connected":   True,
            "database":    "healthcare_platform",
            "collections": collections,
            "doc_counts":  stats,
            "message":     "MongoDB Atlas is connected!"
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500

# ─── Auth routes ─────────────────────────────────────────────────────────────
@app.route("/login", methods=["POST"])
def login():
    data     = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    # Hardcoded admin (no DB lookup needed)
    if username == "admin" and password == "admin123":
        session["user_id"]  = 0
        session["username"] = "admin"
        session["role"]     = "admin"
        return jsonify({"success": True, "role": "admin"})

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()

    if user:
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        session["role"]     = user["role"] or "user"
        return jsonify({"success": True, "role": session["role"]})

    return jsonify({"error": "Invalid username or password"}), 401

@app.route("/register", methods=["POST"])
def register():
    data     = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    conn = get_db()
    try:
        conn.execute("INSERT INTO users(username, password, role) VALUES(?,?,?)",
                     (username, password, "user"))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        session["role"]     = "user"
        return jsonify({"success": True, "role": "user"})
    except:
        return jsonify({"error": "Username already taken"}), 409
    finally:
        conn.close()

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

# ─── Tests list ──────────────────────────────────────────────────────────────
@app.route("/tests")
def get_tests():
    tests_list = sorted(df["canonical_name"].unique().tolist())
    return jsonify({"tests": tests_list})

# ─── Search ──────────────────────────────────────────────────────────────────
@app.route("/search", methods=["POST"])
def search():
    data    = request.get_json()
    query   = data.get("query", "")
    matches = find_all_matches(query)

    if not matches:
        return jsonify({"results": []})

    results = []
    seen_canonicals = set()

    for match in matches:
        subset = df[df["test name"] == match]
        if subset.empty:
            continue

        canonical = subset.iloc[0]["canonical_name"]
        if canonical in seen_canonicals:
            continue
        seen_canonicals.add(canonical)

        # One row per company (cheapest price if duplicates)
        grouped = subset.groupby("company name", as_index=False)["price"].min()

        labs = sorted([
            {
                "company":  str(row["company name"]),
                "location": "Hyderabad",
                "price":    int(row["price"])
            }
            for _, row in grouped.iterrows()
        ], key=lambda x: x["price"])

        prices = [l["price"] for l in labs]

        results.append({
            "matched_test": canonical,
            "info":         metadata.get(canonical, {}),
            "statistics": {
                "min_price":   min(prices),
                "max_price":   max(prices),
                "avg_price":   round(sum(prices) / len(prices)),
                "min_company": labs[0]["company"],
                "max_company": labs[-1]["company"],
            },
            "results": labs
        })

    return jsonify({"results": results})

# ─── Cart ────────────────────────────────────────────────────────────────────
@app.route("/cart")
@login_required
def get_cart():
    conn  = get_db()
    items = conn.execute("SELECT * FROM cart WHERE user_id=?",
                         (session["user_id"],)).fetchall()
    conn.close()
    cart  = [dict(i) for i in items]
    return jsonify({"cart": cart, "total": sum(i["price"] for i in cart)})

@app.route("/cart/add", methods=["POST"])
@login_required
def add_cart():
    data = request.get_json()
    conn = get_db()
    # Prevent duplicate
    existing = conn.execute(
        "SELECT id FROM cart WHERE user_id=? AND test_name=? AND company=?",
        (session["user_id"], data["test_name"], data["company"])
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Already in cart"}), 409
    conn.execute(
        "INSERT INTO cart(user_id, test_name, company, price) VALUES(?,?,?,?)",
        (session["user_id"], data["test_name"], data["company"], data["price"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/cart/remove", methods=["POST"])
@login_required
def remove_cart():
    data = request.get_json()
    conn = get_db()
    conn.execute("DELETE FROM cart WHERE id=? AND user_id=?",
                 (data["item_id"], session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    conn = get_db()
    conn.execute("DELETE FROM cart WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ─── Serve frontend ──────────────────────────────────────────────────────────
@app.route("/")
def root():
    return send_from_directory(FRONTEND_DIR, "login.html")

# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)