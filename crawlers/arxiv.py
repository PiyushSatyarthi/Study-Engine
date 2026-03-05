import feedparser
from urllib.parse import quote


def search_arxiv(query, max_results=20):

    encoded_query = quote(query)

    url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&start=0&max_results={max_results}"

    feed = feedparser.parse(url)

    results = []

    for entry in feed.entries:

        pdf_link = entry.id.replace("abs", "pdf")

        results.append({
            "title": entry.title,
            "summary": entry.summary,
            "pdf": pdf_link,
            "type": "paper",
            "source": "arxiv"
        })

    return results