from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes
from db import resources
from crawler_worker import index_topic
from search_engine import search
from dotenv import load_dotenv
import os
from bson import ObjectId
from users import can_use_summary, increment_summary_usage, is_premium
from llm_summarizer import summarize_text
from db import users
load_dotenv()
TOKEN = os.getenv("TOKEN")

PAGE_SIZE = 10
user_sessions = {}
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}
from payments.razorpay_client import create_payment_link
from db import payments

async def givepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):

    admin_id = update.effective_user.id

    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/givepremium <user_id> [days]\n\nExample:\n/givepremium 123456789 30"
        )
        return

    try:
        target_user = int(context.args[0])
    except:
        await update.message.reply_text("Invalid user_id.")
        return

    days = 30
    if len(context.args) > 1:
        try:
            days = int(context.args[1])
        except:
            pass

    expiry = datetime.utcnow() + timedelta(days=days)

    users.update_one(
        {"user_id": target_user},
        {
            "$set": {
                "is_premium": True,
                "premium_expiry": expiry
            }
        },
        upsert=True
    )

    await update.message.reply_text(
        f"✅ Premium granted\n\nUser: {target_user}\nDays: {days}"
    )
async def premium(update, context):

    user_id = update.effective_user.id

    url, link_id = create_payment_link(user_id)

    payments.insert_one({
        "payment_link_id": link_id,
        "user_id": user_id,
        "status": "created"
    })

    await update.message.reply_text(
        "💎 Study Engine Premium\n\n"
        "• AI research summaries\n"
        "• Future advanced tools\n\n"
        "Price: ₹199 / month\n\n"
        f"Pay securely:\n{url}"
    )
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📚 Study Search Bot\n\n"
        "Find academic papers instantly.\n\n"
        "Example:\n"
        "/study blockchain\n"
        "/summarize <link>"
    )


def build_page(query, results, page):

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    page_results = results[start:end]

    total_pages = (len(results) - 1) // PAGE_SIZE + 1

    msg = f"📚 Study Resources for: {query}\n"
    msg += f"Page {page+1} / {total_pages}\n\n"

    for i, r in enumerate(page_results):

        msg += f"{i+1}. {r['title']}\n"
        msg += f"🔎 {r['source']}\n"
        msg += f"{r['pdf']}\n\n"

    msg += (
        "🧠 To summarize a paper:\n"
        "/summarize <paper link>\n\n"
        "Example:\n"
        "/summarize https://arxiv.org/pdf/2303.09079v3\n\n"
    )

    nav_buttons = []

    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Back", callback_data=f"page:{page-1}")
        )

    if end < len(results):
        nav_buttons.append(
            InlineKeyboardButton("➡️ Next", callback_data=f"page:{page+1}")
        )

    keyboard = InlineKeyboardMarkup([nav_buttons]) if nav_buttons else None

    return msg, keyboard
async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/summarize <paper link>"
        )
        return

    link = context.args[0]

    # check premium
    if not is_premium(user_id):
        await update.message.reply_text(
            "💎 AI summaries are a premium feature.\nUse /premium to upgrade."
        )
        return

    allowed, remaining = can_use_summary(user_id)

    if not allowed:
        await update.message.reply_text(
            "⚠️ Daily summary limit reached (20/day)."
        )
        return

    doc = resources.find_one({"pdf": link})

    if not doc:
        await update.message.reply_text(
            "Paper not found in database yet.\nTry searching it first."
        )
        return

    summary = doc.get("ai_summary")

    if not summary:

        await update.message.reply_text("🧠 Generating summary...")

        summary = summarize_text(doc.get("summary", ""))

        resources.update_one(
            {"_id": doc["_id"]},
            {"$set": {"ai_summary": summary}}
        )

        increment_summary_usage(user_id)

    await update.message.reply_text(
        f"🧠 Summary\n\n{summary}"
    )
async def study(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Please provide a topic.")
        return

    await update.message.reply_text("🔎 Searching resources...")

    results = search(query, limit=40)

    if len(results) < 5:

        await update.message.reply_text("📡 Fetching new resources...")

        try:
            index_topic(query)
        except Exception as e:
            print("Crawler error:", e)

        results = search(query, limit=40)

    if not results:
        await update.message.reply_text("❌ No relevant resources found.")
        return

    user_sessions[update.effective_user.id] = {
        "query": query,
        "results": results
    }

    msg, keyboard = build_page(query, results, 0)

    await update.message.reply_text(msg, reply_markup=keyboard)


async def page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query_data = update.callback_query
    await query_data.answer()

    page = int(query_data.data.split(":")[1])

    session = user_sessions.get(query_data.from_user.id)

    if not session:
        return

    query = session["query"]
    results = session["results"]

    msg, keyboard = build_page(query, results, page)

    await query_data.edit_message_text(msg, reply_markup=keyboard)


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query_data = update.callback_query
    await query_data.answer()

    user_id = query_data.from_user.id

    # check premium
    if not is_premium(user_id):

        await query_data.answer(
            "💎 AI summaries are a premium feature.\nUse /premium to upgrade.",
            show_alert=True
        )
        return

    # rate limit check
    allowed, remaining = can_use_summary(user_id)

    if not allowed:

        await query_data.answer(
            "⚠️ Daily summary limit reached.\n"
            "You can generate 20 summaries per day.",
            show_alert=True
        )
        return

    data = query_data.data.split(":")
    page = int(data[1])
    index = int(data[2])

    session = user_sessions.get(user_id)

    if not session:
        return

    results = session["results"]

    start = page * PAGE_SIZE
    doc = results[start + index]

    # fetch latest document from DB
    db_doc = resources.find_one({"pdf": doc["pdf"]})

    if not db_doc:
        return

    summary = db_doc.get("ai_summary")

    # generate summary if not cached
    if not summary:

        summary = summarize_text(db_doc.get("summary", ""))

        resources.update_one(
            {"_id": db_doc["_id"]},
            {"$set": {"ai_summary": summary}}
        )

    # increment usage AFTER successful summary
    increment_summary_usage(user_id)

    await query_data.message.reply_text(
        f"🧠 Summary\n\n{summary}"
    )

def run_bot():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("study", study))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CallbackQueryHandler(page_callback, pattern="^page"))
    app.add_handler(CommandHandler("summarize", summarize))
    app.add_handler(CommandHandler("donate", givepremium))

    print("Bot running...")

    app.run_polling()