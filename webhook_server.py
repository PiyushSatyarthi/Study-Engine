from fastapi import FastAPI, Request
import hmac
import hashlib
import os
import requests
from datetime import datetime, timedelta

from db import payments, users

app = FastAPI()

WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
BOT_TOKEN = os.getenv("TOKEN")


def verify_signature(body, signature):

    generated = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    return generated == signature


def send_telegram_message(user_id, text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": user_id,
        "text": text
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)


@app.post("/razorpay/webhook")
async def razorpay_webhook(request: Request):

    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    if not verify_signature(body, signature):
        print("Invalid webhook signature")
        return {"status": "invalid signature"}

    data = await request.json()

    event = data.get("event")

    print("Webhook event:", event)

    if event == "payment_link.paid":

        entity = data["payload"]["payment_link"]["entity"]

        link_id = entity["id"]
        user_id = int(entity["notes"]["telegram_user_id"])

        # prevent duplicate activation
        payment = payments.find_one({"payment_link_id": link_id})

        if payment and payment.get("status") == "paid":
            return {"status": "already processed"}

        payments.update_one(
            {"payment_link_id": link_id},
            {"$set": {"status": "paid"}}
        )

        expiry = datetime.utcnow() + timedelta(days=30)

        users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_premium": True,
                    "premium_expiry": expiry
                }
            },
            upsert=True
        )

        # notify user
        send_telegram_message(
            user_id,
            "🎉 Payment Successful!\n\n"
            "💎 Premium activated for 30 days.\n\n"
            "You can now use AI summaries."
        )

        print("Premium activated for user:", user_id)

    return {"status": "ok"}