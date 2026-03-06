"""
Saved papers feature.
Free: up to 5. Premium: unlimited + collections.
"""
from db import saved, collections
from users import get_save_limit, is_premium, now_utc


def save_paper(user_id: int, pdf: str, title: str, source: str,
               topic: str = "", collection_name: str = None):
    count = saved.count_documents({"user_id": user_id})
    limit = get_save_limit(user_id)
    if count >= limit:
        if not is_premium(user_id):
            return False, f"Free limit reached ({limit} papers).\nUpgrade /premium for unlimited."
        return False, "Error saving paper."

    if collection_name and is_premium(user_id):
        if not collections.find_one({"user_id": user_id, "name": collection_name}):
            return False, f"Collection '{collection_name}' not found.\nCreate: /newcollection {collection_name}"

    try:
        saved.insert_one({
            "user_id": user_id, "pdf": pdf, "title": title,
            "source": source, "topic": topic,
            "collection": collection_name, "note": None,
            "saved_at": now_utc()
        })
        remaining = limit - count - 1
        msg = "✅ Paper saved!"
        if collection_name:
            msg += f"\nAdded to: {collection_name}"
        if not is_premium(user_id):
            msg += f"\n({remaining} saves remaining — /premium for unlimited)"
        return True, msg
    except Exception as e:
        if "duplicate" in str(e).lower():
            return False, "Already saved."
        return False, f"Error: {e}"


def unsave_paper(user_id: int, pdf: str):
    r = saved.delete_one({"user_id": user_id, "pdf": pdf})
    return (True, "🗑️ Removed.") if r.deleted_count else (False, "Not in your saves.")


def get_saved_papers(user_id: int, collection_name: str = None) -> list:
    q = {"user_id": user_id}
    if collection_name:
        q["collection"] = collection_name
    return list(saved.find(q).sort("saved_at", -1))


def add_note(user_id: int, pdf: str, note: str):
    r = saved.update_one({"user_id": user_id, "pdf": pdf}, {"$set": {"note": note}})
    return (True, "📝 Note saved.") if r.matched_count else (False, "Paper not in your saves.")
