# db.py — fixed version

import os
from pymongo import MongoClient, ASCENDING, TEXT
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI"),
    maxPoolSize=10,          # connection pool for VPS
    serverSelectionTimeoutMS=5000
)

db = client["study_engine"]
resources = db["resources"]
payments = db["payments"]
users = db["users"]

# --- Resource indexes ---
resources.create_index("pdf", unique=True)
resources.create_index("topic")
resources.create_index("source")   # add this — used in domain boost

# Weighted text index: title matters more than summary
resources.create_index(
    [
        ("title", TEXT),
        ("summary", TEXT),
        ("search_text", TEXT)
    ],
    weights={
        "title": 10,        # title match is most important
        "summary": 5,
        "search_text": 1
    },
    name="text_search_index"
)

# --- User indexes ---
users.create_index("user_id", unique=True)

# --- Payment indexes ---
payments.create_index("payment_link_id", unique=True)