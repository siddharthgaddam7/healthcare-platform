"""
Healthcare Test Price Transparency Backend
==========================================
Routes:
  POST /login          - login
  POST /register       - register new user
  POST /logout         - logout
  GET  /me             - who is logged in
  GET  /tests          - list all canonical tests
  POST /search         - search for a test
  GET  /cart           - get current user cart
  POST /cart/add       - add item to cart
  POST /cart/remove    - remove item from cart
  POST /cart/clear     - clear entire cart
  GET  /admin/users    - (admin only) all users + their carts
"""

import json
from typing import Any, Dict
import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, redirect
from flask_cors import CORS
import pandas as pd
from rapidfuzz import fuzz
import re
import string

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR  = os.path.normpath(os.path.join(BASE_DIR, "..", "frontend"))

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.secret_key = "hyd_health_secret_2026"   # change in production
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
CORS(app, supports_credentials=True, origins=["http://localhost:3000","http://localhost:5000","http://localhost:5500","http://127.0.0.1:5500","http://127.0.0.1:5000","null"])

METADATA_PATH = os.path.join(BASE_DIR, "test_metadata.json")
DB_PATH       = os.path.join(BASE_DIR, "users.db")
DATA_PATH     = r"C:\Users\gadda\OneDrive\Desktop\tanvitha\miniproject\mini_final\enriched_with_canonical (1).xlsx"

# ─────────────────────────────────────────
# ADMIN CREDENTIALS  (hardcoded for simplicity)
# ─────────────────────────────────────────
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────

def get_db():
    """Open a database connection (one per request)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets us access columns by name
    return conn

def init_db():
    """Create tables if they don't exist yet."""
    conn = get_db()
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)

    # Cart table — one row per item per user
    c.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            test_name     TEXT    NOT NULL,
            company       TEXT    NOT NULL,
            price         INTEGER NOT NULL,
            added_at      TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────

def login_required(f):
    """Decorator: block route if user is not logged in (admin has no cart)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("is_admin"):
            return jsonify({"error": "Admin does not have a personal cart"}), 403
        if not session.get("user_id"):
            return jsonify({"error": "Not logged in"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Decorator: block route if user is not admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────
# LOAD DATASET
# ─────────────────────────────────────────

def load_dataset(path):
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip().str.lower()
    required = ["company name","location","test name","canonical_name","price"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
    df = df.dropna(subset=["price"])
    df["test name"]      = df["test name"].astype(str)
    df["canonical_name"] = df["canonical_name"].astype(str)
    return df

df           = load_dataset(DATA_PATH)
unique_tests = df["test name"].unique()

# ─────────────────────────────────────────
# LOAD TEST METADATA
# ─────────────────────────────────────────

RAW_TEST_INFO: Dict[str, Any] = {}
try:
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        RAW_TEST_INFO = json.load(f)
    print(f"[OK] test_metadata.json loaded ({len(RAW_TEST_INFO)} tests)")
except Exception as e:
    RAW_TEST_INFO = {}
    print(f"[WARN] test_metadata.json not found: {e}")

TEST_INFO: Dict[str, Any] = {k.lower(): v for k, v in RAW_TEST_INFO.items()}

def _g(d: Any, key: str, default: Any = "") -> Any:
    """Safe dict getter that avoids Pyre2 overload complaints."""
    try:
        return d[key]
    except (KeyError, TypeError):
        return default

def get_test_info(canonical: str) -> dict:
    raw: Any = TEST_INFO.get(canonical.lower(), {})
    if not raw:
        return {}
    return {
        "description":      _g(raw, "short_description"),
        "why_done":         _g(raw, "why_it_is_done"),
        "parameters":       _g(raw, "parameters_measured", []),
        "normal_range":     _g(raw, "normal_range_summary"),
        "fasting_required": _g(raw, "fasting_required"),
        "sample_type":      _g(raw, "sample_type"),
        "turnaround_time":  _g(raw, "report_time"),
        "preparation":      _g(raw, "preparation_instructions")
    }

# ─────────────────────────────────────────
# SEARCH LOGIC (unchanged)
# ─────────────────────────────────────────

STOPWORDS = {"test","panel","function","level","profile","of","the","and","in","for","to"}

def normalize_text(text):
    if not isinstance(text, str): return ""
    text = text.lower().replace("-", " ")
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split()).replace(" ", "")

norm_test_map = {normalize_text(t): t for t in unique_tests}

def build_alias_dict(test_names):
    alias_dict = {}
    medical_aliases = {
        "cbc":        ["complete blood count","blood count","cbc"],
        "lft":        ["liver function test","lft","liverfunctiontest"],
        "kft":        ["kidney function test","kft"],
        "bloodsugar": ["glucose fasting","blood sugar","sugar"],
        "hba1c":      ["hb a1c","hba1c","glycated hemoglobin"],
        "esr":        ["erythrocyte sedimentation rate","esr"]
    }
    nt = {normalize_text(t): t for t in test_names}
    for aliases in medical_aliases.values():
        cn = normalize_text(aliases[0])
        if cn in nt:
            for a in aliases: alias_dict[normalize_text(a)] = nt[cn]
    for t in test_names: alias_dict[normalize_text(t)] = t
    return alias_dict

ALIAS_DICT = build_alias_dict(unique_tests)

def find_all_matches(query):
    m = set()
    a = ALIAS_DICT.get(normalize_text(query))
    if a: m.add(a)
    e = norm_test_map.get(normalize_text(query))
    if e: m.add(e)
    words = [w for w in re.split(r"\W+", query.lower()) if w and w not in STOPWORDS]
    for norm, orig in norm_test_map.items():
        if all(w in norm for w in words): m.add(orig)
    nq = normalize_text(query)
    for norm, orig in norm_test_map.items():
        if (fuzz.token_sort_ratio(nq,norm)+fuzz.token_set_ratio(nq,norm)+fuzz.partial_ratio(nq,norm))/3 >= 80:
            m.add(orig)
    return list(m)

def calculate_statistics(results):
    if results.empty:
        return {"min_price":None,"min_company":None,"max_price":None,"max_company":None,"avg_price":None}
    mn = results.loc[results["price"].idxmin()]
    mx = results.loc[results["price"].idxmax()]
    return {"min_price":int(mn["price"]),"min_company":mn["company name"],
            "max_price":int(mx["price"]),"max_company":mx["company name"],
            "avg_price":int(results["price"].mean())}

# ─────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────

@app.route("/login", methods=["POST"])
def login():
    data     = request.get_json()
    username = data.get("username","").strip()
    password = data.get("password","").strip()

    # Check admin first
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["is_admin"]  = True
        session["username"]  = "admin"
        session["user_id"]   = None
        return jsonify({"role":"admin","username":"admin"})

    # Check regular users
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()

    if user:
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        session["is_admin"] = False
        return jsonify({"role":"user","username":user["username"]})

    return jsonify({"error":"Invalid username or password"}), 401


@app.route("/register", methods=["POST"])
def register():
    data     = request.get_json()
    username = data.get("username","").strip()
    password = data.get("password","").strip()

    if not username or not password:
        return jsonify({"error":"Username and password required"}), 400
    if len(password) < 4:
        return jsonify({"error":"Password must be at least 4 characters"}), 400

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username, password) VALUES (?,?)", (username, password))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        session["is_admin"] = False
        conn.close()
        return jsonify({"role":"user","username":username})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error":"Username already taken"}), 409


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message":"Logged out"})


@app.route("/me", methods=["GET"])
def me():
    if session.get("is_admin"):
        return jsonify({"role":"admin","username":"admin"})
    if session.get("user_id"):
        return jsonify({"role":"user","username":session["username"],"user_id":session["user_id"]})
    return jsonify({"role":"guest"}), 401

# ─────────────────────────────────────────
# SEARCH ROUTE (unchanged logic)
# ─────────────────────────────────────────

@app.route("/search", methods=["POST"])
def search():
    data  = request.get_json()
    query = data.get("query","")
    matched_tests = find_all_matches(query)
    if not matched_tests:
        return jsonify({"results":[]})
    matched_canonicals = set(df[df["test name"].isin(matched_tests)]["canonical_name"])
    all_results = []
    for canonical in matched_canonicals:
        results = (df[df["canonical_name"]==canonical]
                   .groupby("company name",as_index=False).first())
        if not results.empty:
            results = results.sort_values("price")
        stats = calculate_statistics(results)
        all_results.append({
            "matched_test": canonical,
            "info":         get_test_info(canonical),
            "statistics":   stats,
            "results": [
                {"company":row["company name"],
                 "location":None if pd.isna(row["location"]) else row["location"],
                 "price":int(row["price"])}
                for _,row in results.iterrows()
            ]
        })
    return jsonify({"results":all_results})


@app.route("/tests", methods=["GET"])
def get_tests():
    return jsonify({"tests": sorted(df["canonical_name"].unique().tolist())})

# ─────────────────────────────────────────
# CART ROUTES
# ─────────────────────────────────────────

@app.route("/cart", methods=["GET"])
@login_required
def get_cart():
    user_id = session["user_id"]
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM cart WHERE user_id=? ORDER BY added_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    cart_list = [{"id":r["id"],"test_name":r["test_name"],"company":r["company"],"price":r["price"],"added_at":r["added_at"]} for r in items]
    total = sum(i["price"] for i in cart_list)
    return jsonify({"cart":cart_list,"total":total})


@app.route("/cart/add", methods=["POST"])
@login_required
def add_to_cart():
    data      = request.get_json()
    test_name = data.get("test_name","")
    company   = data.get("company","")
    price     = data.get("price",0)
    user_id   = session["user_id"]

    if not test_name or not company or not price:
        return jsonify({"error":"Missing test_name, company, or price"}), 400

    conn = get_db()

    # Prevent duplicate: same test + same company for same user
    existing = conn.execute(
        "SELECT id FROM cart WHERE user_id=? AND test_name=? AND company=?",
        (user_id, test_name, company)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({"error":"This test from this lab is already in your cart"}), 409

    conn.execute(
        "INSERT INTO cart (user_id, test_name, company, price) VALUES (?,?,?,?)",
        (user_id, test_name, company, price)
    )
    conn.commit()
    conn.close()
    return jsonify({"message":"Added to cart"})


@app.route("/cart/remove", methods=["POST"])
@login_required
def remove_from_cart():
    data    = request.get_json()
    item_id = data.get("item_id")
    user_id = session["user_id"]
    conn = get_db()
    conn.execute("DELETE FROM cart WHERE id=? AND user_id=?", (item_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"message":"Removed from cart"})


@app.route("/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    user_id = session["user_id"]
    conn = get_db()
    conn.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"message":"Cart cleared"})

# ─────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────

@app.route("/admin/users", methods=["GET"])
@admin_required
def admin_users():
    conn  = get_db()
    users = conn.execute("SELECT id, username, created_at FROM users ORDER BY created_at DESC").fetchall()
    result = []
    for u in users:
        cart_items = conn.execute(
            "SELECT test_name, company, price, added_at FROM cart WHERE user_id=? ORDER BY added_at DESC",
            (u["id"],)
        ).fetchall()
        result.append({
            "id":         u["id"],
            "username":   u["username"],
            "joined":     u["created_at"],
            "cart_count": len(cart_items),
            "cart_total": sum(c["price"] for c in cart_items),
            "cart":       [{"test_name":c["test_name"],"company":c["company"],"price":c["price"],"added_at":c["added_at"]} for c in cart_items]
        })
    conn.close()
    return jsonify({"users":result,"total_users":len(result)})


# ─────────────────────────────────────────
# SERVE FRONTEND
# ─────────────────────────────────────────

@app.route("/")
def serve_root():
    return send_from_directory(FRONTEND_DIR, "login.html")


if __name__ == "__main__":
    app.run(debug=True)
