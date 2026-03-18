import os
import requests


def search_core(query, max_results=20):
    url = "https://api.core.ac.uk/v3/search/works"
    api_key = os.getenv("CORE_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    params = {"q": query, "limit": max_results}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        data = r.json()
    except Exception as e:
        print("CORE request error:", e)
        return []

    results = []
    for item in data.get("results", []):
        title = item.get("title", "")
        summary = item.get("abstract") or title
        pdf = item.get("downloadUrl") or item.get("sourceFulltextUrls", [""])[0]
        if not pdf:
            continue

        results.append(
            {
                "title": title,
                "summary": summary if len(summary) > 40 else title,
                "pdf": pdf,
                "type": "paper",
                "source": "core",
                "year": item.get("yearPublished"),
                "citation_count": item.get("citationCount", 0),
            }
        )

    return results
