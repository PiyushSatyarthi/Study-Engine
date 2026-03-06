"""Collections (premium only)."""
from db import collections, saved
from users import PREMIUM_COLLECTIONS_MAX, now_utc


def create_collection(user_id: int, name: str):
    if collections.count_documents({"user_id": user_id}) >= PREMIUM_COLLECTIONS_MAX:
        return False, f"Max {PREMIUM_COLLECTIONS_MAX} collections reached."
    try:
        collections.insert_one({"user_id": user_id, "name": name, "created_at": now_utc()})
        return True, f"✅ Collection '{name}' created.\nSave papers with: /save <link> {name}"
    except Exception as e:
        if "duplicate" in str(e).lower():
            return False, f"Collection '{name}' already exists."
        return False, f"Error: {e}"


def delete_collection(user_id: int, name: str):
    r = collections.delete_one({"user_id": user_id, "name": name})
    if r.deleted_count:
        saved.update_many({"user_id": user_id, "collection": name}, {"$set": {"collection": None}})
        return True, f"🗑️ '{name}' deleted. Papers moved to unsorted."
    return False, f"Collection '{name}' not found."


def list_collections(user_id: int) -> list:
    cols = list(collections.find({"user_id": user_id}).sort("name", 1))
    for c in cols:
        c["paper_count"] = saved.count_documents({"user_id": user_id, "collection": c["name"]})
    return cols
