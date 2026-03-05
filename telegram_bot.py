from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes
from crawler_worker import index_topic
from search_engine import search
from dotenv import load_dotenv
import os
load_dotenv()
TOKEN = os.getenv("TOKEN")
PAGE_SIZE = 10
user_sessions = {}
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📚 Study Search Bot\n\n"
        "Find academic papers instantly.\n\n"
        "Example:\n"
        "/study blockchain\n"
        "/study machine learning"
    )


def build_page(query, results, page):

    PAGE_SIZE = 10

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    page_results = results[start:end]

    total_pages = (len(results) - 1) // PAGE_SIZE + 1

    msg = f"📚 Study Resources for: {query}\n"
    msg += f"Page {page+1} / {total_pages}\n\n"

    grouped = {}

    for r in page_results:

        t = r.get("type", "other")

        if t not in grouped:
            grouped[t] = []

        grouped[t].append(r)

    titles = {
        "paper": "📄 Research Papers",
        "book": "📚 Books",
        "notes": "🧠 Study Notes",
        "course": "🎓 Courses"
    }

    for g in grouped:

        msg += f"{titles.get(g,g)}\n\n"

        for r in grouped[g]:
            msg += f"• {r['title']}\n"
            msg += f"{r['pdf']}\n\n"

    buttons = []

    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"page:{page-1}"))

    if end < len(results):
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"page:{page+1}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None

    return msg, keyboard

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

    # save session
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


def run_bot():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("study", study))

    app.add_handler(CallbackQueryHandler(page_callback))

    print("Bot running...")

    app.run_polling()