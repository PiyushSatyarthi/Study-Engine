import requests


def search_doab(query, max_results=20):

    url = "https://directory.doabooks.org/rest/search"

    params = {
        "query": query,
        "page": 1,
        "pageSize": max_results
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except Exception as e:
        print("DOAB request error:", e)
        return []

    results = []

    # handle different API formats
    if isinstance(data, dict):
        books = data.get("results", [])
    elif isinstance(data, list):
        books = data
    else:
        books = []

    for book in books:

        if not isinstance(book, dict):
            continue

        title = book.get("title", "")

        pdf_link = None

        links = book.get("links", [])

        for link in links:

            if isinstance(link, dict) and "url" in link:

                if "pdf" in link["url"].lower():
                    pdf_link = link["url"]
                    break

        if not pdf_link:
            continue

        results.append({
            "title": title,
            "summary": title,
            "pdf": pdf_link,
            "type": "book",
            "source": "doab"
        })

    return results