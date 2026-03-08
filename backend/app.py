"""
Healthcare Test Price Transparency Backend
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

# ---------------------------------------------------
# PATH SETUP
# ---------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

DATA_PATH = os.path.join(BASE_DIR, "enriched_with_canonical (1).xlsx")

METADATA_PATH = os.path.join(BASE_DIR, "test_metadata.json")
DB_PATH = os.path.join(BASE_DIR, "users.db")

# ---------------------------------------------------
# FLASK APP
# ---------------------------------------------------

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")

app.secret_key = "hyd_health_secret_2026"

app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

# ✅ FIX 1: CORS now points to your exact Vercel URL instead of wildcard *
# Wildcard * + credentials:include = browser blocks it. This fixes that.
CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": [
        "https://healthcare-platform-gamma.vercel.app",
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ]}}
)

# ---------------------------------------------------
# DATABASE
# ---------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            test_name TEXT,
            company TEXT,
            price INTEGER
        )
    """)

    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------
# LOAD DATASET
# ---------------------------------------------------

def load_dataset():
    print("Loading dataset from:", DATA_PATH)
    df = pd.read_excel(DATA_PATH)
    df.columns = df.columns.str.strip().str.lower()

    required = ["company name", "location", "test name", "canonical_name", "price"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")

    df = df.dropna(subset=["price"])
    df["test name"] = df["test name"].astype(str)
    df["canonical_name"] = df["canonical_name"].astype(str)
    return df


df = load_dataset()
unique_tests = df["test name"].unique()

# ---------------------------------------------------
# LOAD METADATA
# ---------------------------------------------------

def load_metadata():
    try:
        with open(METADATA_PATH, "r") as f:
            return json.load(f)
    except:
        return {}

metadata = load_metadata()

# ---------------------------------------------------
# SEARCH HELPERS
# ---------------------------------------------------

STOPWORDS = {"test", "panel", "function", "profile", "of", "the", "and", "in", "for"}


def normalize(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = text.replace(" ", "")
    return text


norm_test_map = {normalize(t): t for t in unique_tests}


def find_all_matches(query):
    results = set()
    nq = normalize(query)

    for norm, orig in norm_test_map.items():
        score = (
            fuzz.token_sort_ratio(nq, norm)
            + fuzz.token_set_ratio(nq, norm)
            + fuzz.partial_ratio(nq, norm)
        ) / 3

        if score >= 80:
            results.add(orig)

    return list(results)

# ---------------------------------------------------
# AUTH DECORATOR
# ---------------------------------------------------

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "login required"}), 401
        return f(*args, **kwargs)
    return wrapper

# ---------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()

    if user:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        return jsonify({"success": True, "role": user["role"]})

    return jsonify({"error": "invalid credentials"}), 401


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users(username, password, role) VALUES(?,?,?)",
            (username, password, "user")
        )
        conn.commit()
    except:
        return jsonify({"error": "username exists"}), 400
    finally:
        conn.close()

    return jsonify({"success": True})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/me", methods=["GET"])
def me():
    if session.get("user_id"):
        return jsonify({
            "role": session.get("role", "user"),
            "username": session.get("username")
        })
    return jsonify({"role": "guest"}), 401

# ---------------------------------------------------
# SEARCH
# ✅ FIX 2: Response now matches what frontend renderResult() expects
# ---------------------------------------------------

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    query = data.get("query", "")
    matches = find_all_matches(query)

    if not matches:
        return jsonify({"results": []})

    results = []

    for match in matches:
        subset = df[df["test name"] == match]

        if subset.empty:
            continue

        labs = []
        for _, row in subset.iterrows():
            labs.append({
                "company": str(row["company name"]),
                "location": str(row["location"]) if pd.notna(row["location"]) else "Hyderabad",
                "price": int(row["price"])
            })

        if not labs:
            continue

        prices = [l["price"] for l in labs]
        min_p = min(prices)
        max_p = max(prices)
        avg_p = round(sum(prices) / len(prices))
        min_company = labs[prices.index(min_p)]["company"]
        max_company = labs[prices.index(max_p)]["company"]

        # Get canonical name for this test
        canonical = subset.iloc[0]["canonical_name"]

        # Get metadata if available
        info = metadata.get(canonical, metadata.get(match, {}))

        results.append({
            "matched_test": canonical,
            "info": info,
            "statistics": {
                "min_price": min_p,
                "max_price": max_p,
                "avg_price": avg_p,
                "min_company": min_company,
                "max_company": max_company
            },
            "results": labs
        })

    return jsonify({"results": results})

# ---------------------------------------------------
# TEST LIST
# ---------------------------------------------------

@app.route("/tests")
def tests():
    tests_list = df["canonical_name"].unique().tolist()
    return jsonify({"tests": tests_list})

# ---------------------------------------------------
# CART
# ✅ FIX 3: Added total to GET /cart
# ✅ FIX 4: Added missing /cart/remove route
# ✅ FIX 5: Added missing /cart/clear route
# ---------------------------------------------------

@app.route("/cart", methods=["GET"])
@login_required
def get_cart():
    conn = get_db()
    items = conn.execute(
        "SELECT * FROM cart WHERE user_id=?",
        (session["user_id"],)
    ).fetchall()
    conn.close()

    cart = [dict(i) for i in items]
    total = sum(i["price"] for i in cart)

    return jsonify({"cart": cart, "total": total})


@app.route("/cart/add", methods=["POST"])
@login_required
def add_cart():
    data = request.get_json()
    conn = get_db()
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
    conn.execute(
        "DELETE FROM cart WHERE id=? AND user_id=?",
        (data["item_id"], session["user_id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/cart/clear", methods=["POST"])
@login_required
def clear_cart():
    conn = get_db()
    conn.execute(
        "DELETE FROM cart WHERE user_id=?",
        (session["user_id"],)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ---------------------------------------------------
# SERVE FRONTEND
# ---------------------------------------------------

@app.route("/")
def root():
    return send_from_directory(FRONTEND_DIR, "login.html")

# ---------------------------------------------------
# RUN SERVER (RENDER SAFE)
# ---------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)