import requests


def search_mit_ocw(query, max_results=10):

    url = "https://ocw.mit.edu/api/v0/search/"

    params = {
        "q": query
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except:
        return []

    results = []

    courses = data.get("results", [])[:max_results]

    for c in courses:

        title = c.get("title", "")
        link = "https://ocw.mit.edu" + c.get("url", "")

        results.append({
            "title": title,
            "summary": title,
            "pdf": link,
            "type": "course",
            "source": "mit_ocw"
        })

    return results