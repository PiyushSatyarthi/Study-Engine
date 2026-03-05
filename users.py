from datetime import datetime, timedelta
from db import users

DAILY_LIMIT = 20


def is_premium(user_id):
    u = users.find_one({"user_id": user_id})
    if not u:
        return False

    expiry = u.get("premium_expiry")
    if not expiry:
        return False

    return expiry > datetime.utcnow()


def can_use_summary(user_id):
    """
    Returns (allowed: bool, remaining: int)
    Also handles daily reset.
    """

    now = datetime.utcnow()

    u = users.find_one({"user_id": user_id})

    # create user record if missing
    if not u:
        reset = datetime(now.year, now.month, now.day) + timedelta(days=1)

        users.insert_one({
            "user_id": user_id,
            "daily_summary_count": 0,
            "summary_reset": reset
        })

        return True, DAILY_LIMIT

    reset_time = u.get("summary_reset")
    count = u.get("daily_summary_count", 0)

    # reset counter if needed
    if not reset_time or reset_time < now:

        reset = datetime(now.year, now.month, now.day) + timedelta(days=1)

        users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "daily_summary_count": 0,
                    "summary_reset": reset
                }
            }
        )

        count = 0

    remaining = DAILY_LIMIT - count

    return remaining > 0, remaining

def increment_summary_usage(user_id):

    users.update_one(
        {"user_id": user_id},
        {"$inc": {"daily_summary_count": 1}}
    )