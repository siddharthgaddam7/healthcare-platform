"""
migrate_to_mongo.py
====================
One-time script to import data from Excel + JSON into MongoDB Atlas.

Collections created:
  - tests      : canonical test info + metadata + aliases
  - labs        : one doc per (lab, test, price)

Usage:
    set MONGO_URI=mongodb+srv://...
    python migrate_to_mongo.py
"""

import os
import sys
import json
import pandas as pd
from pymongo import MongoClient

# ─── Config ──────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_PATH     = os.path.join(BASE_DIR, "enriched_with_canonical_updated.xlsx")
METADATA_PATH = os.path.join(BASE_DIR, "test_metadata.json")

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    print("ERROR: Set the MONGO_URI environment variable first.")
    print("  e.g.  set MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/")
    sys.exit(1)

# ─── Connect ─────────────────────────────────────────────────────────────────
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
client.admin.command("ping")
db = client["healthcare_platform"]
print("[OK] Connected to MongoDB Atlas")

# ─── Alias map (Task 7 — search aliases) ─────────────────────────────────────
ALIASES = {
    "CBC":                  ["cbc", "complete blood count", "cbp", "blood count", "full blood count", "hemogram"],
    "Haemoglobin":          ["haemoglobin", "hemoglobin", "hb", "hb test"],
    "Lipid Profile":        ["lipid profile", "lipid panel", "cholesterol test", "cholesterol panel", "lipids"],
    "Cholesterol":          ["cholesterol", "total cholesterol", "cholesterol level"],
    "Thyroid Panel":        ["thyroid panel", "thyroid test", "thyroid profile", "tft", "thyroid function test", "t3 t4 tsh"],
    "Liver Function Test":  ["liver function test", "lft", "liver test", "liver panel", "liver profile", "sgpt", "sgot"],
    "Uric Acid":            ["uric acid", "uric acid test", "serum uric acid", "gout test"],
    "Post Prandial Glucose":["post prandial glucose", "ppg", "ppbs", "post meal glucose", "post meal sugar", "pp sugar"],
    "Dengue":               ["dengue", "dengue test", "dengue fever test"],
    "Dengue Antibody":      ["dengue antibody", "dengue ab"],
    "Dengue IgM/IgG":       ["dengue igm", "dengue igg", "dengue igm/igg", "dengue igm igg"],
    "Dengue NS1 Antigen":   ["dengue ns1", "ns1 antigen", "dengue ns1 antigen", "ns1"],
    "Dengue Serology":      ["dengue serology", "dengue serology test"],
    "ECG":                  ["ecg", "electrocardiogram", "ekg", "heart test", "cardiac test"],
    "Insulin":              ["insulin", "fasting insulin", "insulin test", "insulin level"],
    "Vitamin B12":          ["vitamin b12", "vit b12", "b12", "cobalamin", "b12 test"],
}

# ─── Load metadata ───────────────────────────────────────────────────────────
with open(METADATA_PATH, "r") as f:
    raw_meta = json.load(f)

# Remap to cleaner keys
metadata = {}
for k, v in raw_meta.items():
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

# ─── Load Excel data ────────────────────────────────────────────────────────
print("[INFO] Loading Excel dataset:", DATA_PATH)
df = pd.read_excel(DATA_PATH)
df.columns = df.columns.str.strip().str.lower()
df = df.dropna(subset=["price"])
df["test name"]      = df["test name"].astype(str).str.strip()
df["canonical_name"] = df["canonical_name"].astype(str).str.strip()
df["company name"]   = df["company name"].astype(str).str.strip()
df["location"]       = df["location"].fillna("Hyderabad").astype(str).str.strip()
df["price"]          = df["price"].astype(int)

# ─── Import tests collection ─────────────────────────────────────────────────
print("\n[STEP 1] Importing tests collection...")
db.tests.drop()

canonical_names = sorted(df["canonical_name"].unique().tolist())
test_docs = []
for name in canonical_names:
    # Get all original test name variants from the dataset
    variants = df[df["canonical_name"] == name]["test name"].unique().tolist()
    # Combine with predefined aliases
    aliases = list(set(
        [a.lower() for a in ALIASES.get(name, [])] +
        [v.lower() for v in variants] +
        [name.lower()]
    ))

    doc = {
        "canonical_name": name,
        "aliases":        aliases,
        "info":           metadata.get(name, {}),
    }
    test_docs.append(doc)

result = db.tests.insert_many(test_docs)
print(f"  Inserted {len(result.inserted_ids)} test documents")

# Create index on aliases for fast search
db.tests.create_index("aliases")
db.tests.create_index("canonical_name", unique=True)

# ─── Import labs collection ──────────────────────────────────────────────────
print("\n[STEP 2] Importing labs collection...")
db.labs.drop()

lab_docs = []
for _, row in df.iterrows():
    lab_docs.append({
        "lab_name":       row["company name"],
        "location":       row["location"],
        "test_name":      row["test name"],
        "canonical_name": row["canonical_name"],
        "price":          int(row["price"]),
        # Task 2 — real contact fields from updated dataset
        "phone":   str(row.get("phone", "")).strip() if pd.notna(row.get("phone")) else "",
        "email":   str(row.get("email", "")).strip() if pd.notna(row.get("email")) else "",
        "website": str(row.get("website", "")).strip() if pd.notna(row.get("website")) else "",
        "address": str(row.get("address", "")).strip() if pd.notna(row.get("address")) else "",
    })

result = db.labs.insert_many(lab_docs)
print(f"  Inserted {len(result.inserted_ids)} lab documents")

# Create indexes for fast queries
db.labs.create_index("canonical_name")
db.labs.create_index("lab_name")
db.labs.create_index([("canonical_name", 1), ("lab_name", 1)])

# ─── Summary ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
print("MIGRATION COMPLETE")
print("=" * 50)
for col in db.list_collection_names():
    count = db[col].count_documents({})
    print(f"  {col}: {count} documents")
print()
print("You can now deploy the updated app.py to Render.")
print("Existing SQLite users will need to re-register.")
