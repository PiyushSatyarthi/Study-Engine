import requests


def search_openalex(query, max_results=20):
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per-page": max_results,
        "select": "display_name,abstract_inverted_index,publication_year,primary_location,cited_by_count",
    }

    try:
        r = requests.get(url, params=params, timeout=12)
        data = r.json()
    except Exception as e:
        print("OpenAlex request error:", e)
        return []

    results = []
    for item in data.get("results", []):
        title = item.get("display_name", "")
        inv = item.get("abstract_inverted_index") or {}
        words = []
        if isinstance(inv, dict):
            pos_map = {}
            for word, poses in inv.items():
                for pos in poses:
                    pos_map[pos] = word
            words = [pos_map[k] for k in sorted(pos_map.keys())]
        summary = " ".join(words) if words else title

        primary = item.get("primary_location") or {}
        source_url = primary.get("landing_page_url") or primary.get("pdf_url") or ""
        if not source_url:
            continue

        results.append(
            {
                "title": title,
                "summary": summary if len(summary) > 40 else title,
                "pdf": source_url,
                "type": "paper",
                "source": "openalex",
                "year": item.get("publication_year"),
                "citation_count": item.get("cited_by_count", 0),
            }
        )

    return results
