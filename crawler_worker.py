from datetime import datetime, timezone
import re

from crawlers.arxiv import search_arxiv
from crawlers.pubmed import search_pubmed
from crawlers.doab import search_doab
from crawlers.semantic_scholar import search_semantic_scholar
from crawlers.github_learning import search_github_learning
from crawlers.mit_ocw import search_mit_ocw

from constants import STOPWORDS

from db import resources
from embeddings import embed

MIN_SUMMARY_LENGTH = 80

# GitHub repos that are clearly not academic — skip if title matches these patterns
GITHUB_JUNK_PATTERNS = [
    lambda t: len(t.split()) <= 2 and "-" in t,   # "lattice-example", "fhe-and-lbc"
    lambda t: any(c.isdigit() for c in t) and len(t) > 20,  # "CryptoKeyManagerTechNext123"
    lambda t: t.lower().startswith("echo") or t.lower().startswith("crypto"),
    lambda t: len(t) < 8,                           # too short to be meaningful
]


def is_quality_resource(r: dict) -> bool:
    """Filter out low-quality crawl results before indexing."""
    if not r.get("pdf"):
        return False
    if not r.get("title") or len(r["title"]) < 10:
        return False
    if not r.get("summary") or len(r["summary"]) < MIN_SUMMARY_LENGTH:
        return False

    # Extra quality checks for GitHub results
    if r.get("source", "").lower() == "github":
        title = r["title"]
        if any(check(title) for check in GITHUB_JUNK_PATTERNS):
            return False
        # GitHub repos must have a real description (summary), not just a name
        if len(r["summary"]) < 150:
            return False

    return True


def is_relevant_to_topic(r: dict, topic: str) -> bool:
    """
    Hard relevance gate before indexing.
    Requires at least 1 meaningful topic token to appear in title or summary.
    Prevents completely unrelated papers from polluting the DB.
    """
    tokens = [t for t in topic.lower().split() if t not in STOPWORDS and len(t) > 3]

    if not tokens:
        return True  # can't filter if no meaningful tokens

    text = (r.get("title", "") + " " + r.get("summary", "")).lower()

    for token in tokens:
        pattern = r'(?<![a-z])' + re.escape(token) + r'(?![a-z])'
        if re.search(pattern, text):
            return True

    return False


def index_topic(topic):
    results = []

    crawlers = [
        search_arxiv,
        search_pubmed,
        search_doab,
        search_semantic_scholar,
        search_github_learning,
        search_mit_ocw
    ]

    for crawler in crawlers:
        try:
            results += crawler(topic)
        except Exception as e:
            print(f"{crawler.__name__} error:", e)

    # Quality filter
    results = [r for r in results if is_quality_resource(r)]

    # Relevance filter — don't index papers unrelated to the topic
    results = [r for r in results if is_relevant_to_topic(r, topic)]

    print(f"Found {len(results)} quality resources for {topic}")

    added = 0
    for r in results:
        if resources.find_one({"pdf": r["pdf"]}):
            continue

        text = (r["title"] + ". " + r["summary"])[:2000]
        vector = embed(text)

        doc = {
            "title": r["title"],
            "summary": r["summary"],
            "search_text": text,
            "ai_summary": None,
            "type": r["type"],
            "source": r["source"],
            "pdf": r["pdf"],
            "topic": topic,
            "embedding": vector,
            "indexed_at": datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        }

        # Optional metadata from crawlers that provide it
        if r.get("year"):
            doc["year"] = r["year"]
        if r.get("citation_count"):
            doc["citation_count"] = r["citation_count"]

        resources.insert_one(doc)
        added += 1

    print(f"Indexed {added} new resources for topic: {topic}")