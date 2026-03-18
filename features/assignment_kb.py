"""
Assignment Knowledge Base
─────────────────────────
Stores LLM-generated answers with embeddings.
When a new question comes in, we search for semantically similar
stored answers first. If similarity is high enough, serve from DB.
If user is not satisfied, they can regenerate with LLM.

Flow:
  1. New question arrives
  2. Embed the question
  3. Vector search assignment_answers for similar questions
  4. If best match similarity >= SIMILARITY_THRESHOLD → serve stored answer
  5. If no match → run LLM, store the result with embedding
  6. User presses "Regenerate" → force LLM, update stored answer
"""

import hashlib
from datetime import datetime, timezone
from db import db
from embeddings import embed_query

SIMILARITY_THRESHOLD = 0.88   # cosine similarity — tune based on testing
assignment_answers = db["assignment_answers"]


def _now():
    return datetime.now(timezone.utc)


def _question_hash(question: str) -> str:
    return hashlib.md5(question.lower().strip().encode()).hexdigest()


def find_similar_answer(question: str) -> dict | None:
    """
    Search the knowledge base for a semantically similar stored answer.
    Returns the stored answer dict if similarity >= threshold, else None.
    """
    try:
        embedding = embed_query(question)
        if not embedding:
            return None

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "assignment_vector_index",
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": 20,
                    "limit": 3
                }
            },
            {
                "$addFields": {"similarity": {"$meta": "vectorSearchScore"}}
            },
            {
                "$match": {"similarity": {"$gte": SIMILARITY_THRESHOLD}}
            },
            {
                "$sort": {"similarity": -1}
            },
            {"$limit": 1}
        ]

        results = list(assignment_answers.aggregate(pipeline))
        if results:
            best = results[0]
            print(f"[kb] Cache hit — similarity={best['similarity']:.3f} | {best['question'][:60]}")
            return best

    except Exception as e:
        print(f"[kb] Vector search failed: {e}")

    return None


def store_answer(question: str, topics: list, answer_result: dict):
    """
    Store a generated answer with its embedding for future reuse.
    Upserts by question_hash so re-generations overwrite the old answer.
    """
    try:
        embedding = embed_query(question)
        if not embedding:
            print("[kb] Skipping store — embedding failed")
            return

        doc = {
            "question_hash": _question_hash(question),
            "question": question,
            "topics": topics,
            "embedding": embedding,
            "answer": answer_result.get("answer", ""),
            "sources": answer_result.get("sources", []),
            "confidence_label": answer_result.get("confidence_label", ""),
            "papers_found": answer_result.get("papers_found", 0),
            "q_type": answer_result.get("type", "factual"),
            "created_at": _now(),
            "use_count": 1
        }

        assignment_answers.update_one(
            {"question_hash": doc["question_hash"]},
            {
                "$set": {k: v for k, v in doc.items() if k != "use_count"},
                "$inc": {"use_count": 1}
            },
            upsert=True
        )
        print(f"[kb] Stored answer for: {question[:60]}")

    except Exception as e:
        print(f"[kb] Store failed: {e}")


def format_kb_result(stored: dict, question_number: int) -> dict:
    """Convert a stored KB doc into the same format generate_answer returns."""
    return {
        "number": question_number,
        "question": stored.get("question", ""),
        "type": stored.get("q_type", "factual"),
        "answer": stored.get("answer", ""),
        "sources": stored.get("sources", []),
        "confidence_label": stored.get("confidence_label", ""),
        "papers_found": stored.get("papers_found", 0),
        "from_kb": True,   # flag so bot can show "Regenerate" button
        "similarity": stored.get("similarity", 0)
    }
