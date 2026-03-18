from __future__ import annotations

from db import collection_members, saved, shared_collections
from users import now_utc
from features.advanced_research import generate_share_code


def share_collection(owner_user_id: int, collection_name: str) -> tuple[bool, str]:
    if not collection_name.strip():
        return False, "Collection name is required."

    existing = shared_collections.find_one(
        {"owner_user_id": owner_user_id, "collection_name": collection_name.strip()}
    )
    if existing:
        return True, f"Share code for '{collection_name}': {existing['code']}"

    code = generate_share_code()
    for _ in range(5):
        if not shared_collections.find_one({"code": code}):
            break
        code = generate_share_code()

    shared_collections.insert_one(
        {
            "owner_user_id": owner_user_id,
            "collection_name": collection_name.strip(),
            "code": code,
            "created_at": now_utc(),
        }
    )
    return True, f"Share code for '{collection_name}': {code}"


def join_shared_collection(user_id: int, code: str) -> tuple[bool, str]:
    code = code.strip().upper()
    share = shared_collections.find_one({"code": code})
    if not share:
        return False, "Invalid code."

    if share.get("owner_user_id") == user_id:
        return False, "You already own this collection."

    collection_members.update_one(
        {"code": code, "user_id": user_id},
        {"$setOnInsert": {"joined_at": now_utc()}},
        upsert=True,
    )
    return True, f"Joined collection '{share['collection_name']}'. Use /sharedpapers {code}"


def list_shared_memberships(user_id: int) -> list:
    joins = list(collection_members.find({"user_id": user_id}))
    out = []
    for j in joins:
        share = shared_collections.find_one({"code": j["code"]})
        if not share:
            continue
        out.append(
            {
                "code": share["code"],
                "collection_name": share["collection_name"],
                "owner_user_id": share["owner_user_id"],
            }
        )
    return out


def get_shared_papers(user_id: int, code: str) -> tuple[bool, str, list]:
    code = code.strip().upper()
    share = shared_collections.find_one({"code": code})
    if not share:
        return False, "Invalid code.", []

    is_member = collection_members.find_one({"code": code, "user_id": user_id})
    if not is_member and share.get("owner_user_id") != user_id:
        return False, "Join first with /joincollection <code>.", []

    owner_id = share["owner_user_id"]
    papers = list(
        saved.find(
            {"user_id": owner_id, "collection": share["collection_name"]}
        ).sort("saved_at", -1)
    )
    return True, share["collection_name"], papers
