import requests
import xml.etree.ElementTree as ET


def search_pubmed(query, max_results=20):

    # Step 1: search PubMed for paper IDs
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json"
    }

    response = requests.get(search_url, params=params, timeout=10)
    data = response.json()

    ids = data["esearchresult"]["idlist"]

    if not ids:
        return []

    # Step 2: fetch full records with abstracts via efetch XML
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml"
    }

    response = requests.get(fetch_url, params=params, timeout=15)
    root = ET.fromstring(response.text)

    papers = []

    for article in root.findall(".//PubmedArticle"):

        title_el = article.find(".//ArticleTitle")
        title = title_el.text if title_el is not None and title_el.text else ""

        # Extract abstract (may have multiple AbstractText elements
        # for structured abstracts like BACKGROUND / METHODS / RESULTS)
        abstract_parts = []
        for abs_text in article.findall(".//Abstract/AbstractText"):
            label = abs_text.get("Label", "")
            # iter_text handles mixed content like <i>italic</i> inside text
            text = "".join(abs_text.itertext()) or ""
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        if not title or not pmid:
            continue

        papers.append({
            "title": title,
            "summary": abstract if abstract else title,
            "pdf": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "type": "paper",
            "source": "pubmed"
        })

    return papers
