from datetime import datetime, timedelta, timezone
import threading
import os
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler,
    CommandHandler, ContextTypes, MessageHandler, filters
)

from db import resources, sessions, users
from crawler_worker import index_topic
from search_engine import search, search_related
from dotenv import load_dotenv

from users import (
    can_use_study, increment_study_usage, get_results_limit,
    can_use_summary, increment_summary_usage, is_premium,
    add_to_history, get_history,
    get_digest_time, set_digest_time, now_utc
)
from llm_summarizer import summarize_text, ask_paper as _ask_paper_fn, compare_papers as _compare_papers_fn
from users import get_education_level, set_education_level, EDUCATION_LEVELS
from assignment_analyzer import analyze_assignment

from features.saved_papers import save_paper, unsave_paper, get_saved_papers, add_note
from features.collections_feature import create_collection, delete_collection, list_collections
from features.alerts import add_alert, remove_alert, list_alerts
from features.export_pdf import generate_export_pdf
from features.ask_paper import ask_paper
from features.multi_summary import compare_papers, MAX_PAPERS
from features.suggestions import get_suggestions
from features.digest import run_digest_scheduler

load_dotenv()
TOKEN = os.getenv("TOKEN")

PAGE_SIZE = 5
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}

crawling_in_progress = set()
crawl_cooldowns = {}
crawling_lock = threading.Lock()
CRAWL_COOLDOWN_SECONDS = 600

# Tracks users who sent /assignment and are waiting to send their content
assignment_sessions = {}


# ── Helpers ───────────────────────────────────────────────────

def is_crawl_needed(topic_key: str) -> bool:
    with crawling_lock:
        if topic_key in crawling_in_progress:
            return False
        last = crawl_cooldowns.get(topic_key)
        if last:
            if (now_utc() - last).total_seconds() < CRAWL_COOLDOWN_SECONDS:
                return False
        return True


def save_session(user_id: int, query: str, results: list):
    slim = [{"pdf": r["pdf"], "title": r["title"], "source": r["source"]} for r in results]
    sessions.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "query": query, "results": slim, "updated_at": now_utc()}},
        upsert=True
    )


def load_session(user_id: int):
    return sessions.find_one({"user_id": user_id})


def build_page(query: str, results: list, page: int):
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_results = results[start:end]
    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)

    msg = f"📚 Results for: {query}\nPage {page+1}/{total_pages}\n\n"
    for i, r in enumerate(page_results):
        msg += f"{i+1}. {r['title']}\n🔎 {r['source']}\n{r['pdf']}\n\n"
    msg += "🧠 /summarize <link>  💾 /save <link>"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page:{page-1}"))
    if end < len(results):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page:{page+1}"))
    keyboard = InlineKeyboardMarkup([nav]) if nav else None
    return msg, keyboard


# ── /start ────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_username = os.getenv("ADMIN_USERNAME", "@admin")
    user_name = update.effective_user.first_name or "there"

    # ── Message 1: Intro ──────────────────────────────────────
    await update.message.reply_text(
        f"Hey {user_name} 👋\n\n"
        "I'm *Study Atlas* — your academic research assistant.\n\n"
        "I search millions of papers from ArXiv, PubMed, and Semantic Scholar, "
        "summarize them in plain English, and help you understand them — "
        "so you spend less time hunting for sources and more time actually studying.\n\n"
        "Free to start. No sign-up needed.",
        parse_mode="Markdown"
    )

    # ── Message 2: Assignment Analyzer (flagship feature) ─────
    await update.message.reply_text(
        "🧠 *New — Assignment Analyzer*\n\n"
        "Send me your assignment and I'll:\n"
        "• Break it into individual questions\n"
        "• Find relevant research papers for each one\n"
        "• Generate research-backed answers with citations\n\n"
        "Supports PDF uploads or plain text paste.\n\n"
        "Try it: /assignment",
        parse_mode="Markdown"
    )

    # ── Message 3: Core search ────────────────────────────────
    await update.message.reply_text(
        "🔍 *Search & Read Papers*\n\n"
        "/study <topic> — find papers on any topic\n"
        "/summarize <link> — get a plain English summary ✨\n"
        "/ask <link> <question> — ask anything about a paper ✨\n"
        "/compare <link1> <link2> — compare two papers side by side ✨\n\n"
        "✨ Premium feature",
        parse_mode="Markdown"
    )

    # ── Message 4: Organisation features ─────────────────────
    await update.message.reply_text(
        "📂 *Stay Organised*\n\n"
        "/save <link> — save a paper to your library\n"
        "/saved — view your saved papers\n"
        "/collections — group papers into collections ✨\n"
        "/export — export your library as PDF ✨\n"
        "/history — your recent searches",
        "/setlevel — set your education level (affects answer depth & style)",
        parse_mode="Markdown"
    )

    # ── Message 5: Alerts + digest (grouped as minor features)
    await update.message.reply_text(
        "🔔 *Stay Updated*\n\n"
        "/setalert <topic> — get notified when new papers drop ✨\n"
        "/digest — daily research digest delivered every morning ✨\n\n"
        "✨ Premium feature\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💎 Upgrade for full access: /premium\n"
        f"❓ Need help: {admin_username}",
        parse_mode="Markdown"
    )




# ── /study ────────────────────────────────────────────────────

async def study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text("Usage: /study <topic>\nExample: /study quantum computing")
        return

    allowed, remaining, limit = can_use_study(user_id)
    if not allowed:
        if is_premium(user_id):
            await update.message.reply_text(f"Daily limit reached ({limit}/day). Resets midnight UTC.")
        else:
            await update.message.reply_text(
                f"Free limit reached ({limit} searches/day).\n\n"
                "Upgrade for 50 searches/day + 20 results/search.\n/premium"
            )
        return

    await update.message.reply_text("Searching...")

    result_limit = get_results_limit(user_id)
    results, needs_crawl = search(query, limit=result_limit)
    topic_key = query.lower()

    if results:
        increment_study_usage(user_id)
        add_to_history(user_id, query)
        save_session(user_id, query, results)

        msg, keyboard = build_page(query, results, 0)
        if not is_premium(user_id):
            msg += f"\n\nShowing {result_limit}/20 results. /premium for full access."

        suggestions = get_suggestions(query)
        if suggestions:
            msg += "\n\nRelated topics:\n" + " | ".join(f"/study {s}" for s in suggestions)

        await update.message.reply_text(msg, reply_markup=keyboard)

        if needs_crawl and is_crawl_needed(topic_key):
            with crawling_lock:
                crawling_in_progress.add(topic_key)
            _application.create_task(
                crawl_and_notify(query, update.effective_chat.id, _application, silent=True, user_id=user_id)
            )
        return

    if not is_crawl_needed(topic_key):
        await update.message.reply_text("Already fetching this topic. Please wait and try again.")
        return

    increment_study_usage(user_id)
    add_to_history(user_id, query)

    with crawling_lock:
        crawling_in_progress.add(topic_key)

    await update.message.reply_text(
        f"No results found yet.\nFetching papers for: {query}\n\nThis takes ~30 seconds."
    )
    _application.create_task(
        crawl_and_notify(query, update.effective_chat.id, _application, silent=False, user_id=user_id)
    )


async def page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])
    session = load_session(q.from_user.id)
    if not session:
        await q.edit_message_text("Session expired. Search again with /study.")
        return
    msg, keyboard = build_page(session["query"], session["results"], page)
    if not is_premium(q.from_user.id):
        msg += f"\n\nShowing {get_results_limit(q.from_user.id)}/20 results. /premium"
    await q.edit_message_text(msg, reply_markup=keyboard)


async def crawl_and_notify(query: str, chat_id: int, application,
                            silent: bool = False, user_id: int = None):
    try:
        await asyncio.get_event_loop().run_in_executor(None, index_topic, query)
    except Exception as e:
        print(f"[crawl] Error for '{query}': {e}")
    finally:
        with crawling_lock:
            crawling_in_progress.discard(query.lower())
            crawl_cooldowns[query.lower()] = now_utc()

    result_limit = get_results_limit(user_id) if user_id else 5
    results, _ = search(query, limit=result_limit)

    if silent and results:
        if user_id:
            save_session(user_id, query, results)
        return

    if not results:
        await application.bot.send_message(chat_id=chat_id,
            text="No relevant papers found. Try a more specific term.")
        return

    if user_id:
        save_session(user_id, query, results)

    msg, keyboard = build_page(query, results, 0)
    if user_id and not is_premium(user_id):
        msg += f"\n\nShowing {result_limit}/20 results. /premium for full access."

    suggestions = get_suggestions(query)
    if suggestions:
        msg += "\n\nRelated topics:\n" + " | ".join(f"/study {s}" for s in suggestions)

    await application.bot.send_message(chat_id=chat_id, text=msg, reply_markup=keyboard)


# ── /history ──────────────────────────────────────────────────

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    hist = get_history(user_id)
    if not hist:
        await update.message.reply_text("No search history yet. Use /study.")
        return
    msg = "Search History\n\n"
    for i, h in enumerate(hist, 1):
        msg += f"{i}. {h['query']}\n"
    if not is_premium(user_id):
        msg += "\nShowing last 3. Premium shows full history.\n/premium"
    await update.message.reply_text(msg)


# ── /save & /saved ────────────────────────────────────────────

async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: /save <link> [collection]\n"
            "Example: /save https://arxiv.org/pdf/xxxx my-thesis"
        )
        return

    pdf = context.args[0]
    collection_name = " ".join(context.args[1:]) or None

    if collection_name and not is_premium(user_id):
        await update.message.reply_text("Collections require premium.\n/premium")
        return

    doc = resources.find_one({"pdf": pdf})
    if not doc:
        await update.message.reply_text("Paper not found. Search first: /study <topic>")
        return

    ok, msg = save_paper(user_id, pdf, doc["title"], doc.get("source", ""),
                          doc.get("topic", ""), collection_name)
    await update.message.reply_text(msg)


async def unsave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unsave <link>")
        return
    ok, msg = unsave_paper(update.effective_user.id, context.args[0])
    await update.message.reply_text(msg)


async def saved_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    collection_name = " ".join(context.args) if context.args else None
    papers = get_saved_papers(user_id, collection_name)

    if not papers:
        await update.message.reply_text(
            "No saved papers" + (f" in '{collection_name}'" if collection_name else "") +
            ".\nSave with /save <link>"
        )
        return

    msg = f"Saved Papers ({len(papers)})"
    if collection_name:
        msg += f" — {collection_name}"
    msg += "\n\n"

    for i, p in enumerate(papers, 1):
        msg += f"{i}. {p['title']}\n{p['pdf']}\n"
        if p.get("note"):
            msg += f"Note: {p['note']}\n"
        msg += "\n"
        if len(msg) > 3500:
            msg += f"... and {len(papers)-i} more."
            break

    msg += "\n/export — download as PDF"
    await update.message.reply_text(msg)


async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Notes require premium.\n/premium")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /note <link> <your note>")
        return
    ok, msg = add_note(user_id, context.args[0], " ".join(context.args[1:]))
    await update.message.reply_text(msg)


# ── /collections ──────────────────────────────────────────────

async def collections_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Collections require premium.\n/premium")
        return
    cols = list_collections(user_id)
    if not cols:
        await update.message.reply_text("No collections yet.\nCreate: /newcollection <name>")
        return
    msg = "Your Collections\n\n"
    for c in cols:
        msg += f"• {c['name']} ({c['paper_count']} papers)\n"
    msg += "\n/newcollection <name>\n/delcollection <name>\n/saved <name>"
    await update.message.reply_text(msg)


async def new_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Collections require premium.\n/premium")
        return
    if not context.args:
        await update.message.reply_text("Usage: /newcollection <name>")
        return
    ok, msg = create_collection(user_id, " ".join(context.args))
    await update.message.reply_text(msg)


async def del_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Collections require premium.\n/premium")
        return
    if not context.args:
        await update.message.reply_text("Usage: /delcollection <name>")
        return
    ok, msg = delete_collection(user_id, " ".join(context.args))
    await update.message.reply_text(msg)


# ── /export ───────────────────────────────────────────────────

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Export requires premium.\n/premium")
        return

    collection_name = " ".join(context.args) if context.args else None
    papers = get_saved_papers(user_id, collection_name)

    if not papers:
        await update.message.reply_text("No saved papers to export.\nSave with /save <link>")
        return

    for p in papers:
        doc = resources.find_one({"pdf": p["pdf"]})
        if doc:
            p["ai_summary"] = doc.get("ai_summary")

    await update.message.reply_text(f"Generating PDF for {len(papers)} papers...")

    path = None
    try:
        title = f"Collection: {collection_name}" if collection_name else "My Saved Papers"
        path = generate_export_pdf(user_id, papers, title)
        with open(path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="study_engine_export.pdf",
                caption=f"📚 {len(papers)} papers exported"
            )
    except Exception as e:
        await update.message.reply_text(f"Export failed: {e}")
    finally:
        if path and os.path.exists(path):
            os.remove(path)


# ── /summarize ────────────────────────────────────────────────

async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /summarize <link>")
        return
    if not is_premium(user_id):
        await update.message.reply_text(
            "AI summaries require premium.\n\n"
            "Premium: 20 summaries/day, 50 searches, 20 results/search + more.\n/premium"
        )
        return
    allowed, remaining = can_use_summary(user_id)
    if not allowed:
        await update.message.reply_text("Daily summary limit reached (20/day). Resets midnight UTC.")
        return

    link = context.args[0]
    doc = resources.find_one({"pdf": link})
    if not doc:
        await update.message.reply_text("Paper not found. Search first: /study <topic>")
        return

    level = get_education_level(user_id)
    level_key = level["short"].lower().replace("/", "_").replace(" ", "_")
    cache_field = f"ai_summary_{level_key}"

    summary = doc.get(cache_field)
    if not summary:
        await update.message.reply_text(f"Generating summary [{level['short']}]...")
        summary = summarize_text(doc.get("summary", ""), level=level)
        resources.update_one({"_id": doc["_id"]}, {"$set": {cache_field: summary}})
        increment_summary_usage(user_id)

    await update.message.reply_text(f"📄 Summary [{level['short']}]\n\n{summary}")

    related_query = doc.get("topic") or doc.get("title", "")
    related = search_related(related_query, current_pdf=doc["pdf"], limit=4)
    if related:
        text = "Related Papers\n\n"
        for r in related:
            text += f"• {r['title']}\n{r['pdf']}\n\n"
        await update.message.reply_text(text)


# ── /ask ──────────────────────────────────────────────────────

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Ask a Paper requires premium.\n/premium")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /ask <link> <question>\n"
            "Example: /ask https://arxiv.org/pdf/xxxx What method did they use?"
        )
        return
    link = context.args[0]
    question = " ".join(context.args[1:])
    doc = resources.find_one({"pdf": link})
    if not doc:
        await update.message.reply_text("Paper not found. Search first: /study <topic>")
        return
    await update.message.reply_text("Thinking...")
    level = get_education_level(user_id)
    answer = _ask_paper_fn(doc.get("summary", ""), question, doc.get("title", ""), level=level)
    await update.message.reply_text(f"Answer\n\n{answer}")


# ── /compare ─────────────────────────────────────────────────

async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Paper comparison requires premium.\n/premium")
        return
    links = (context.args or [])[:MAX_PAPERS]
    if len(links) < 2:
        await update.message.reply_text(
            f"Usage: /compare <link1> <link2> [link3]\nUp to {MAX_PAPERS} papers."
        )
        return
    papers = []
    for link in links:
        doc = resources.find_one({"pdf": link})
        if doc:
            papers.append({"title": doc["title"], "summary": doc.get("summary", "")})

    if len(papers) < 2:
        await update.message.reply_text("Need at least 2 papers in DB. Search them first.")
        return

    await update.message.reply_text("Comparing papers...")
    level = get_education_level(user_id)
    result = _compare_papers_fn(papers, level=level)
    await update.message.reply_text(f"Comparison\n\n{result}")


# ── /setalert /removealert /alerts ────────────────────────────

async def setalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Topic alerts require premium.\n/premium")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setalert <topic>\nExample: /setalert CRISPR")
        return
    ok, msg = add_alert(user_id, " ".join(context.args))
    await update.message.reply_text(msg)


async def removealert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removealert <topic>")
        return
    ok, msg = remove_alert(update.effective_user.id, " ".join(context.args))
    await update.message.reply_text(msg)


async def myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Alerts require premium.\n/premium")
        return
    alert_list = list_alerts(user_id)
    if not alert_list:
        await update.message.reply_text("No alerts. Add one: /setalert <topic>")
        return
    msg = "Your Alerts\n\n"
    for a in alert_list:
        msg += f"• {a['topic']}\n"
    msg += "\n/removealert <topic> to remove"
    await update.message.reply_text(msg)


# ── /digest ───────────────────────────────────────────────────

async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("Daily digest requires premium.\n/premium")
        return
    if context.args:
        try:
            h, m = context.args[0].split(":")
            assert 0 <= int(h) <= 23 and 0 <= int(m) <= 59
            set_digest_time(user_id, f"{int(h):02d}:{int(m):02d}")
            await update.message.reply_text(
                f"Daily digest set to {context.args[0]} UTC\n"
                "Set alert topics with /setalert <topic>"
            )
        except Exception:
            await update.message.reply_text("Invalid time. Use: /digest HH:MM (e.g. /digest 08:30)")
    else:
        current = get_digest_time(user_id)
        await update.message.reply_text(
            f"Daily Digest\nCurrent time: {current} UTC\n\n"
            "Change with /digest HH:MM\n"
            "Digest sends new papers for your /setalert topics."
        )


# ── /setlevel ─────────────────────────────────────────────────

async def setlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # No argument — show current level + options
    if not context.args:
        current = get_education_level(user_id)
        lines = [
            f"🎓 Your current level: *{current['label']}*\n",
            "This affects how answers, summaries, and comparisons are written.\n",
            "Choose your level:\n"
        ]
        for key, lvl in EDUCATION_LEVELS.items():
            lines.append(f"/setlevel {key} — {lvl['label']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    level_key = context.args[0].lower().strip()
    if set_education_level(user_id, level_key):
        lvl = EDUCATION_LEVELS[level_key]
        await update.message.reply_text(
            f"✅ Level set to *{lvl['label']}*\n\n"
            f"All future answers, summaries, and assignment analysis "
            f"will be written at *{lvl['short']}* level.",
            parse_mode="Markdown"
        )
    else:
        valid = ", ".join(EDUCATION_LEVELS.keys())
        await update.message.reply_text(
            f"❌ Unknown level `{level_key}`.\n\nValid options: {valid}",
            parse_mode="Markdown"
        )


# ── /premium & /givepremium ───────────────────────────────────

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from payments.razorpay_client import create_payment_link
    from db import payments as pay_col

    user_id = update.effective_user.id
    if is_premium(user_id):
        u = users.find_one({"user_id": user_id})
        expiry = u.get("premium_expiry")
        await update.message.reply_text(
            f"You have Premium! Expires: {expiry.strftime('%d %b %Y') if expiry else 'N/A'}\n\n"
            "Commands: /summarize /ask /compare /export /collections /setalert /digest /assignment"
        )
        return

    url, link_id = create_payment_link(user_id)
    pay_col.insert_one({"payment_link_id": link_id, "user_id": user_id, "status": "created"})

    await update.message.reply_text(
        "Study Engine Premium — Rs.199/month\n\n"
        "Free tier:\n"
        "• 5 searches/day  • 5 results/search\n"
        "• 5 saved papers  • Last 3 history entries\n\n"
        "Premium tier:\n"
        "• 50 searches/day  • 20 results/search\n"
        "• Unlimited saved papers  • Full history\n"
        "• 20 AI summaries/day\n"
        "• Ask a paper (Q&A)\n"
        "• Compare up to 3 papers\n"
        "• Collections & notes\n"
        "• Topic alerts\n"
        "• Daily digest\n"
        "• PDF export\n"
        "• Assignment analyzer\n\n"
        f"Pay securely:\n{url}"
    )


async def givepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /givepremium <user_id> [days]")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user_id.")
        return
    days = int(context.args[1]) if len(context.args) > 1 else 30
    expiry = now_utc() + timedelta(days=days)
    users.update_one({"user_id": target}, {"$set": {"is_premium": True, "premium_expiry": expiry}}, upsert=True)
    await update.message.reply_text(f"Premium granted. User: {target} | Days: {days}")


# ── /assignment ───────────────────────────────────────────────

async def assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_premium(user_id):
        await update.message.reply_text(
            "💎 Assignment Analyzer is a Premium feature.\n\n"
            "Use /premium to upgrade."
        )
        return

    assignment_sessions[user_id] = {"step": "waiting_for_content"}

    await update.message.reply_text(
        "📋 Assignment Analyzer\n\n"
        "Send me your assignment as:\n"
        "• Plain text — type or paste your questions\n"
        "• A PDF file\n\n"
        "I'll extract all questions and suggest the best topics to read.\n\n"
        "Send your assignment now 👇"
    )


async def assignment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catches text/PDF sent after /assignment.
    Ignores all other messages so it doesn't interfere with normal bot usage.
    """
    user_id = update.effective_user.id
    session = assignment_sessions.get(user_id)

    # Not in assignment flow — ignore completely
    if not session or session.get("step") != "waiting_for_content":
        return

    assignment_text = None

    # ── Plain text ──
    if update.message.text:
        text = update.message.text.strip()
        # Ignore bot commands so /study etc still work even if session is open
        if text.startswith("/"):
            assignment_sessions.pop(user_id, None)
            return
        if len(text) < 20:
            await update.message.reply_text(
                "⚠️ That looks too short. Please send your full assignment questions."
            )
            return
        assignment_text = text

    # ── PDF ──
    elif update.message.document:
        doc = update.message.document
        mime = doc.mime_type or ""

        if mime != "application/pdf":
            await update.message.reply_text(
                "⚠️ Only PDF files are supported.\n"
                "Please send a PDF or paste your questions as text.\n\n"
                "Images are not supported."
            )
            return

        if doc.file_size > 5 * 1024 * 1024:
            await update.message.reply_text(
                "⚠️ PDF too large (max 5MB). Please send a smaller file or paste the text."
            )
            return

        await update.message.reply_text("📄 Reading your PDF...")

        try:
            tg_file = await context.bot.get_file(doc.file_id)
            file_bytes = await tg_file.download_as_bytearray()
            assignment_text = _extract_pdf_text(bytes(file_bytes))

            if not assignment_text or len(assignment_text.strip()) < 20:
                await update.message.reply_text(
                    "⚠️ Could not extract text from this PDF. "
                    "It may be scanned or image-based. "
                    "Please paste your questions as text instead."
                )
                assignment_sessions.pop(user_id, None)
                return

        except Exception as e:
            print(f"[assignment] PDF read error: {e}")
            await update.message.reply_text(
                "⚠️ Failed to read the PDF. Please paste your questions as text."
            )
            return

    # ── Reject photos ──
    elif update.message.photo:
        await update.message.reply_text(
            "⚠️ Images are not supported.\n"
            "Please send a PDF or paste your questions as text."
        )
        return

    else:
        return

    # Got content — ask what the user wants
    assignment_sessions[user_id] = {
        "step": "choose_mode",
        "text": assignment_text
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📚 Topics only", callback_data="assign:mode:topics"),
            InlineKeyboardButton("✍️ Full answers", callback_data="assign:mode:answers")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="assign:cancel")]
    ])

    await update.message.reply_text(
        "✅ Got your assignment!\n\n"
        "What would you like?\n\n"
        "📚 Topics only — map each question to topics and papers to read\n"
        "✍️ Full answers — generate research-backed answers for each question (takes longer)",
        reply_markup=keyboard
    )


async def assignment_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    # data format: "assign:cancel" or "assign:mode:topics" or "assign:mode:answers"
    parts = query.data.split(":")
    action = parts[1]  # "cancel" or "mode"

    if action == "cancel":
        assignment_sessions.pop(user_id, None)
        await query.edit_message_text("❌ Assignment analysis cancelled.")
        return

    mode = parts[2] if len(parts) > 2 else "topics"  # "topics" or "answers"

    session = assignment_sessions.get(user_id)
    if not session or "text" not in session:
        await query.edit_message_text("⚠️ Session expired. Please use /assignment again.")
        return

    assignment_text = session["text"]
    assignment_sessions.pop(user_id, None)

    if mode == "topics":
        await query.edit_message_text(
            "🔍 Analyzing your assignment and mapping topics...\n\nThis takes about 15–30 seconds."
        )
    else:
        await query.edit_message_text(
            "🧠 Analyzing and generating research-backed answers...\n\n"
            "This takes 1–3 minutes depending on how many questions you have.\n"
            "Results will appear question by question."
        )

    loop = asyncio.get_event_loop()

    try:
        result = await loop.run_in_executor(
            None,
            lambda: analyze_assignment(assignment_text, mode=mode,
                                         level=get_education_level(query.from_user.id))
        )
    except Exception as e:
        print(f"[assignment] Analysis error: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⚠️ Something went wrong during analysis. Please try again."
        )
        return

    if result.get("error"):
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⚠️ {result['error']}"
        )
        return

    questions = result.get("questions", [])
    total = result.get("total", 0)

    if mode == "topics":
        await _send_topic_map(context.bot, query.message.chat_id, questions, total)
    else:
        await _send_answers(context.bot, query.message.chat_id, questions, total)


async def assignment_regen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Regenerate' button — force fresh LLM answer, skip KB."""
    query = update.callback_query
    await query.answer("🔄 Regenerating with fresh search...")

    regen_id = query.data.split(":", 2)[2]
    bot = context.bot

    # Retrieve stored question data
    store = getattr(bot, '_regen_store', {})
    data = store.get(regen_id)
    if not data:
        await query.edit_message_reply_markup(reply_markup=None)
        await bot.send_message(
            chat_id=query.message.chat_id,
            text="⚠️ Regenerate session expired. Please use /assignment again."
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await bot.send_message(
        chat_id=data['chat_id'],
        text=f"🔄 Regenerating answer for Q{data['number']}...\nSearching papers now."
    )

    loop = asyncio.get_event_loop()

    def run_regen():
        from assignment_analyzer import _gather_relevant_papers, generate_answer
        q = {
            "number": data['number'],
            "question": data['question'],
            "type": data['type'],
            "topics": data.get('topics', [])
        }
        q['papers'] = _gather_relevant_papers(q['question'], q['topics'])
        return generate_answer(q, q['papers'], force_regenerate=True)

    try:
        result = await loop.run_in_executor(None, run_regen)
        await _send_answers(bot, data['chat_id'], [result], 1)
    except Exception as e:
        print(f"[assignment] Regen error: {e}")
        await bot.send_message(
            chat_id=data['chat_id'],
            text="⚠️ Regeneration failed. Please try /assignment again."
        )

    # Clean up store
    store.pop(regen_id, None)


async def _send_topic_map(bot, chat_id: int, questions: list, total: int):
    await bot.send_message(
        chat_id=chat_id,
        text=f"📋 Assignment Analysis — {total} question(s) found\n\nTopics to study for each question:"
    )

    type_emoji = {"factual": "🔬", "essay": "✍️", "numerical": "🔢", "definition": "📖"}

    for q in questions:
        topics = q.get("topics", [])
        topic_str = "\n".join(f"  • {t}" for t in topics) if topics else f"  • {q['question']}"
        emoji = type_emoji.get(q["type"], "❓")

        msg = (
            f"{emoji} Q{q['number']} [{q['type']}]\n"
            f"{q['question']}\n\n"
            f"Topics to read:\n{topic_str}"
        )
        await bot.send_message(chat_id=chat_id, text=msg)

    await bot.send_message(
        chat_id=chat_id,
        text="💡 Want full research-backed answers? Use /assignment again and choose Full answers."
    )


async def _send_answers(bot, chat_id: int, questions: list, total: int):
    await bot.send_message(
        chat_id=chat_id,
        text=f"📋 Assignment Analysis — {total} question(s)\nGenerating answers from academic research..."
    )

    type_emoji = {"factual": "🔬", "essay": "✍️", "numerical": "🔢", "definition": "📖", "explain": "💡"}

    for q in questions:
        emoji = type_emoji.get(q.get("type", ""), "❓")
        confidence = q.get("confidence_label", "")
        papers_found = q.get("papers_found", 0)
        answer = q.get("answer", "No answer generated.")
        sources = q.get("sources", [])
        from_kb = q.get("from_kb", False)

        # KB answers get a subtle badge so user knows it's from stored results
        kb_badge = "⚡ Instant answer  |  " if from_kb else ""

        msg = (
            f"{emoji} Q{q['number']} — {q['type']}\n"
            f"{q['question']}\n\n"
            f"{answer}\n"
        )

        if sources:
            msg += "\nSources:\n"
            for s in sources[:3]:
                title_short = s["title"][:55] + "..." if len(s["title"]) > 55 else s["title"]
                msg += f"• {title_short}\n  {s['link']}\n"

        if confidence:
            msg += f"\n{kb_badge}Confidence: {confidence}"
            if papers_found:
                msg += f" ({papers_found} papers)"

        if len(msg) > 4000:
            msg = msg[:3950] + "\n\n(Answer truncated)"

        # Show Regenerate button only for KB answers
        keyboard = None
        if from_kb:
            import json
            regen_data = json.dumps({
                "q": q['question'],
                "t": q.get('type', 'factual'),
                "topics": q.get('topics', [])
            })
            # Store regen data in bot's user_data keyed by a short id
            regen_id = f"{chat_id}_{q['number']}"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔄 Not satisfied? Regenerate with fresh search",
                    callback_data=f"assign:regen:{regen_id}"
                )
            ]])
            # Store the question data so callback can retrieve it
            if not hasattr(bot, '_regen_store'):
                bot._regen_store = {}
            bot._regen_store[regen_id] = {
                "question": q['question'],
                "type": q.get('type', 'factual'),
                "topics": q.get('topics', []),
                "number": q['number'],
                "chat_id": chat_id
            }

        try:
            await bot.send_message(
                chat_id=chat_id, text=msg,
                disable_web_page_preview=True,
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"[assignment] Send error Q{q['number']}: {e}")
            await bot.send_message(chat_id=chat_id, text=f"Q{q['number']}: {answer[:1000]}")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import io
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except ImportError:
        pass
    except Exception as e:
        print(f"[assignment] PyPDF2 error: {e}")

    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        print(f"[assignment] pdfplumber error: {e}")
        return ""


# ── App entry ─────────────────────────────────────────────────

_application = None


def run_bot():
    global _application
    app = ApplicationBuilder().token(TOKEN).build()
    _application = app

    handlers = [
        ("start", start), ("study", study), ("history", history),
        ("save", save), ("unsave", unsave), ("saved", saved_list), ("note", note_cmd),
        ("export", export), ("collections", collections_cmd),
        ("newcollection", new_collection), ("delcollection", del_collection),
        ("summarize", summarize), ("ask", ask), ("compare", compare),
        ("setalert", setalert), ("removealert", removealert), ("alerts", myalerts),
        ("digest", digest), ("setlevel", setlevel), ("premium", premium), ("givepremium", givepremium),
        ("assignment", assignment),
    ]
    for name, handler in handlers:
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(CallbackQueryHandler(page_callback, pattern="^page:"))
    app.add_handler(CallbackQueryHandler(assignment_mode_callback, pattern="^assign:mode:|^assign:cancel"))
    app.add_handler(CallbackQueryHandler(assignment_regen_callback, pattern="^assign:regen:"))

    # Catches text and documents ONLY when user is in assignment flow
    # filters.COMMAND excluded so /study, /save etc are never intercepted
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.Document.ALL | filters.PHOTO,
        assignment_receive
    ))

    async def post_init(application):
        application.create_task(run_digest_scheduler(application))

    app.post_init = post_init

    print("Bot running...")
    app.run_polling()