import requests


def search_pubmed(query, max_results=20):

    # Step 1: search PubMed for paper IDs
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json"
    }

    response = requests.get(search_url, params=params)
    data = response.json()

    ids = data["esearchresult"]["idlist"]

    if not ids:
        return []

    # Step 2: fetch details for those IDs
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json"
    }

    response = requests.get(fetch_url, params=params)
    data = response.json()

    papers = []

    for pid in ids:

        paper = data["result"][pid]

        papers.append({
            "title": paper.get("title", ""),
            "summary": paper.get("title", ""),
            "pdf": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "type": "paper",
            "source": "pubmed"
        })

    return papers