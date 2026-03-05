import razorpay
import os

client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

def create_payment_link(user_id):

    payment = client.payment_link.create({
        "amount": 19900,  # ₹199
        "currency": "INR",
        "description": "Study Engine Premium (1 month)",
        "customer": {
            "name": f"tg_user_{user_id}"
        },
        "notify": {
            "sms": False,
            "email": False
        },
        "callback_method": "get",
        "notes": {
            "telegram_user_id": user_id
        }
    })

    return payment["short_url"], payment["id"]