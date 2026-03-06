"""Daily digest scheduler (premium only)."""
import asyncio
from datetime import datetime, timezone
from db import users, resources, digest_log, alerts
from users import now_utc, get_digest_time
from features.alerts import get_new_papers_for_alert, mark_notified


def _today_str() -> str:
    return now_utc().strftime("%Y-%m-%d")


def _already_sent(user_id: int) -> bool:
    return bool(digest_log.find_one({"user_id": user_id, "date": _today_str()}))


def _mark_sent(user_id: int):
    try:
        digest_log.insert_one({
            "user_id": user_id,
            "date": _today_str(),
            "sent_at": now_utc()
        })
    except Exception:
        pass  # duplicate key — already sent


def _build_digest_message(user_id: int) -> str | None:
    """Build digest message from user's alert topics. Returns None if nothing new."""
    user_alerts = list(alerts.find({"user_id": user_id}))
    if not user_alerts:
        return None

    sections = []
    for alert in user_alerts:
        papers = get_new_papers_for_alert(alert)
        if papers:
            section = f"📌 {alert['topic'].title()}\n\n"
            for p in papers[:3]:
                section += f"• {p['title']}\n"
                section += f"  {p['pdf']}\n\n"
            sections.append(section)
            mark_notified(alert["_id"], now_utc())

    if not sections:
        return None

    msg = "🌅 Your Daily Study Digest\n\n"
    msg += "\n".join(sections)
    msg += "\nUse /summarize <link> to get AI summaries."
    return msg


async def run_digest_scheduler(application):
    """
    Runs as a background async task.
    Checks every minute if any premium user is due for their digest.
    """
    print("[digest] Scheduler started")
    while True:
        try:
            await asyncio.sleep(60)  # check every minute

            now = now_utc()
            current_time = now.strftime("%H:%M")

            # Find all premium users whose digest time matches current time
            premium_users = list(users.find({
                "is_premium": True,
                "premium_expiry": {"$gt": now},
                "digest_time": current_time
            }))

            for u in premium_users:
                user_id = u["user_id"]
                if _already_sent(user_id):
                    continue

                msg = _build_digest_message(user_id)
                if msg:
                    try:
                        await application.bot.send_message(chat_id=user_id, text=msg)
                        _mark_sent(user_id)
                        print(f"[digest] Sent to user {user_id}")
                    except Exception as e:
                        print(f"[digest] Failed for user {user_id}: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[digest] Scheduler error: {e}")
