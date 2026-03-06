"""Topic alerts (premium only). Notifies when new papers are indexed."""
from db import alerts, resources
from users import PREMIUM_ALERTS_MAX, now_utc


def add_alert(user_id: int, topic: str):
    if alerts.count_documents({"user_id": user_id}) >= PREMIUM_ALERTS_MAX:
        return False, f"Max {PREMIUM_ALERTS_MAX} alerts reached.\nRemove one with /removealert <topic>"
    try:
        alerts.insert_one({
            "user_id": user_id, "topic": topic.lower(),
            "created_at": now_utc(), "last_notified": None
        })
        return True, f"🔔 Alert set for: {topic}\nYou'll be notified when new papers are indexed."
    except Exception as e:
        if "duplicate" in str(e).lower():
            return False, f"Alert for '{topic}' already exists."
        return False, f"Error: {e}"


def remove_alert(user_id: int, topic: str):
    r = alerts.delete_one({"user_id": user_id, "topic": topic.lower()})
    return (True, f"🔕 Alert removed for: {topic}") if r.deleted_count else (False, f"No alert found for '{topic}'")


def list_alerts(user_id: int) -> list:
    return list(alerts.find({"user_id": user_id}))


def get_new_papers_for_alert(alert: dict) -> list:
    """Find papers indexed after last_notified for this alert topic."""
    query = {"topic": {"$regex": alert["topic"], "$options": "i"}}
    if alert.get("last_notified"):
        query["indexed_at"] = {"$gt": alert["last_notified"]}
    return list(resources.find(query).sort("indexed_at", -1).limit(3))


def mark_notified(alert_id, ts):
    alerts.update_one({"_id": alert_id}, {"$set": {"last_notified": ts}})
