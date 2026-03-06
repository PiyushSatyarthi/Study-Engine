from datetime import datetime, timedelta, timezone
from db import users

# ── Free tier ─────────────────────────────────────────────────
FREE_STUDY_DAILY        = 5
FREE_RESULTS_PER_SEARCH = 5
FREE_SUMMARY_DAILY      = 0
FREE_SAVED_PAPERS       = 5
FREE_HISTORY_SHOWN      = 3

# ── Premium tier ──────────────────────────────────────────────
PREMIUM_STUDY_DAILY        = 50
PREMIUM_RESULTS_PER_SEARCH = 20
PREMIUM_SUMMARY_DAILY      = 20
PREMIUM_SAVED_PAPERS       = 999999   # unlimited
PREMIUM_HISTORY_SHOWN      = 999999
PREMIUM_ALERTS_MAX         = 5
PREMIUM_COLLECTIONS_MAX    = 10


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _midnight_tomorrow():
    n = now_utc()
    return datetime(n.year, n.month, n.day) + timedelta(days=1)


def _get_or_create_user(user_id: int) -> dict:
    u = users.find_one({"user_id": user_id})
    if not u:
        doc = {
            "user_id": user_id,
            "is_premium": False,
            "premium_expiry": None,
            "daily_study_count": 0,
            "daily_summary_count": 0,
            "study_reset": _midnight_tomorrow(),
            "summary_reset": _midnight_tomorrow(),
            "search_history": [],
            "digest_time": "08:00",   # default 8 AM UTC
        }
        users.insert_one(doc)
        return doc
    return u


def _maybe_reset(user_id: int, count_field: str, reset_field: str):
    now = now_utc()
    u = users.find_one({"user_id": user_id})
    if not u:
        return
    reset_time = u.get(reset_field)
    if not reset_time or reset_time < now:
        users.update_one(
            {"user_id": user_id},
            {"$set": {count_field: 0, reset_field: _midnight_tomorrow()}}
        )


# ── Premium ───────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    u = users.find_one({"user_id": user_id})
    if not u:
        return False
    expiry = u.get("premium_expiry")
    return bool(expiry and expiry > now_utc())


# ── Study limits ──────────────────────────────────────────────

def can_use_study(user_id: int):
    """Returns (allowed, remaining, limit)"""
    _get_or_create_user(user_id)
    _maybe_reset(user_id, "daily_study_count", "study_reset")
    u = users.find_one({"user_id": user_id})
    count = u.get("daily_study_count", 0)
    limit = PREMIUM_STUDY_DAILY if is_premium(user_id) else FREE_STUDY_DAILY
    remaining = max(0, limit - count)
    return remaining > 0, remaining, limit


def increment_study_usage(user_id: int):
    users.update_one({"user_id": user_id}, {"$inc": {"daily_study_count": 1}})


def get_results_limit(user_id: int) -> int:
    return PREMIUM_RESULTS_PER_SEARCH if is_premium(user_id) else FREE_RESULTS_PER_SEARCH


# ── Summary limits ────────────────────────────────────────────

def can_use_summary(user_id: int):
    """Returns (allowed, remaining). Free users always get (False, 0)."""
    if not is_premium(user_id):
        return False, 0
    _get_or_create_user(user_id)
    _maybe_reset(user_id, "daily_summary_count", "summary_reset")
    u = users.find_one({"user_id": user_id})
    count = u.get("daily_summary_count", 0)
    remaining = max(0, PREMIUM_SUMMARY_DAILY - count)
    return remaining > 0, remaining


def increment_summary_usage(user_id: int):
    users.update_one({"user_id": user_id}, {"$inc": {"daily_summary_count": 1}})


# ── Search history ────────────────────────────────────────────

def add_to_history(user_id: int, query: str):
    """Push query to history, keep last 20 entries (deduplicated)."""
    _get_or_create_user(user_id)
    # Remove existing entry for same query to avoid duplicates
    users.update_one(
        {"user_id": user_id},
        {"$pull": {"search_history": {"query": query}}}
    )
    users.update_one(
        {"user_id": user_id},
        {
            "$push": {
                "search_history": {
                    "$each": [{"query": query, "ts": now_utc()}],
                    "$position": 0,
                    "$slice": 20
                }
            }
        }
    )


def get_history(user_id: int) -> list:
    _get_or_create_user(user_id)
    u = users.find_one({"user_id": user_id})
    history = u.get("search_history", [])
    limit = PREMIUM_HISTORY_SHOWN if is_premium(user_id) else FREE_HISTORY_SHOWN
    return history[:limit]


# ── Saved paper limits ────────────────────────────────────────

def get_save_limit(user_id: int) -> int:
    return PREMIUM_SAVED_PAPERS if is_premium(user_id) else FREE_SAVED_PAPERS


# ── Digest settings ───────────────────────────────────────────

def get_digest_time(user_id: int) -> str:
    """Returns HH:MM string in UTC."""
    u = users.find_one({"user_id": user_id})
    return (u or {}).get("digest_time", "08:00")


def set_digest_time(user_id: int, time_str: str):
    _get_or_create_user(user_id)
    users.update_one(
        {"user_id": user_id},
        {"$set": {"digest_time": time_str}}
    )