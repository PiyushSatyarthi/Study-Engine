import os
from pymongo import MongoClient, TEXT
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI"),
    maxPoolSize=10,
    serverSelectionTimeoutMS=5000
)

db = client["study_engine"]

resources   = db["resources"]
payments    = db["payments"]
users       = db["users"]
sessions    = db["sessions"]
saved       = db["saved_papers"]
collections = db["collections"]
alerts      = db["alerts"]
digest_log  = db["digest_log"]


def ensure_indexes():

    # ── resources ──────────────────────────────────────────────
    resources.create_index("pdf", unique=True)
    resources.create_index("topic")
    resources.create_index("source")
    resources.create_index("indexed_at")

    existing = resources.index_information()
    for name, info in existing.items():
        if "text" in [v for _, v in info.get("key", [])]:
            print(f"[db] Dropping old text index: {name}")
            resources.drop_index(name)
            break

    resources.create_index(
        [("title", TEXT), ("summary", TEXT), ("search_text", TEXT)],
        weights={"title": 10, "summary": 5, "search_text": 1},
        name="text_search_index"
    )

    # ── users ──────────────────────────────────────────────────
    users.create_index("user_id", unique=True)

    # ── payments ───────────────────────────────────────────────
    payments.create_index("payment_link_id", unique=True)

    # ── sessions (pagination) — auto-expire after 24h ─────────
    sessions.create_index("user_id", unique=True)
    sessions.create_index("updated_at", expireAfterSeconds=86400)

    # ── saved papers ───────────────────────────────────────────
    saved.create_index([("user_id", 1), ("pdf", 1)], unique=True)
    saved.create_index("user_id")

    # ── collections ────────────────────────────────────────────
    collections.create_index([("user_id", 1), ("name", 1)], unique=True)

    # ── topic alerts ───────────────────────────────────────────
    alerts.create_index([("user_id", 1), ("topic", 1)], unique=True)
    alerts.create_index("topic")

    # ── digest log — auto-expire after 7 days ─────────────────
    digest_log.create_index([("user_id", 1), ("date", 1)], unique=True)
    digest_log.create_index("sent_at", expireAfterSeconds=604800)

    # ── assignment answers knowledge base ──────────────────────
    # Stores LLM-generated answers with embeddings for semantic search.
    # Future users with similar questions get stored answers instantly.
    # Requires MongoDB Atlas vector index named "assignment_vector_index"
    # on "embedding" field (768 dims, cosine similarity).
    assignment_answers = db["assignment_answers"]
    assignment_answers.create_index("question_hash", unique=True)
    assignment_answers.create_index("topic")
    assignment_answers.create_index("created_at")

    print("[db] All indexes ready.")


ensure_indexes()