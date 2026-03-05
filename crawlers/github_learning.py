import requests


def search_github_learning(query, max_results=10):

    url = "https://api.github.com/search/repositories"

    params = {
        "q": f"{query} tutorial OR course OR notes OR guide",
        "sort": "stars",
        "order": "desc",
        "per_page": max_results
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except:
        return []

    results = []

    for repo in data.get("items", []):

        title = repo["name"]
        summary = repo.get("description", "") or title
        link = repo["html_url"]

        results.append({
            "title": title,
            "summary": summary,
            "pdf": link,
            "type": "notes",
            "source": "github"
        })

    return results