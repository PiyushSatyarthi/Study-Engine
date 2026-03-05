from crawlers.arxiv import search_arxiv
from crawlers.pubmed import search_pubmed
from crawlers.doab import search_doab

from crawlers.semantic_scholar import search_semantic_scholar
from crawlers.github_learning import search_github_learning
from crawlers.mit_ocw import search_mit_ocw

from db import resources
from embeddings import embed


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

    print(f"Found {len(results)} resources for {topic}")

    added = 0

    for r in results:

        if resources.find_one({"pdf": r["pdf"]}):
            continue

        vector = embed(r["title"] + " " + r["summary"])

        doc = {
            "title": r["title"],
            "summary": r["summary"],
            "ai_summary": None,
            "type": r["type"],
            "source": r["source"],
            "pdf": r["pdf"],
            "topic": topic,
            "embedding": vector
        }

        resources.insert_one(doc)
        added += 1

    print(f"Indexed {added} new resources for topic: {topic}")