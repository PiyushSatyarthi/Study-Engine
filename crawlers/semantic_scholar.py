import requests


def search_semantic_scholar(query, max_results=20):

    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,abstract,url,year,citationCount"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except:
        return []

    results = []

    for paper in data.get("data", []):

        title = paper.get("title", "")
        summary = paper.get("abstract", "") or title
        url = paper.get("url", "")

        results.append({
            "title": title,
            "summary": summary,
            "pdf": url,
            "type": "paper",
            "source": "semantic_scholar",
            "year": paper.get("year"),
            "citation_count": paper.get("citationCount", 0)
        })

    return results