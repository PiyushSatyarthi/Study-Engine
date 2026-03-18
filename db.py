import os
from pymongo import MongoClient, TEXT
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI"),
    maxPoolSize=50,
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
study_plans = db["study_plans"]
shared_collections = db["shared_collections"]
collection_members = db["collection_members"]


def ensure_indexes():

    # ── resources ──────────────────────────────────────────────
    resources.create_index("pdf", unique=True)
    resources.create_index("topic")
    resources.create_index("source")
    resources.create_index("indexed_at")

    # Only create text index if it doesn't already exist
    existing = resources.index_information()
    has_text = any(
        "text" in [v for _, v in info.get("key", [])]
        for info in existing.values()
    )
    if not has_text:
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

    # ── study plans ────────────────────────────────────────────
    study_plans.create_index([("user_id", 1), ("topic", 1)], unique=True)
    study_plans.create_index("updated_at")

    # ── collaborative collections ──────────────────────────────
    shared_collections.create_index("code", unique=True)
    shared_collections.create_index([("owner_user_id", 1), ("collection_name", 1)], unique=True)
    collection_members.create_index([("code", 1), ("user_id", 1)], unique=True)
    collection_members.create_index("user_id")

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
