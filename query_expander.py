# query_expander.py

EXPANSIONS = {
    "metabolism": "metabolism biochemistry metabolic pathway enzymes",
    "machine learning": "machine learning neural network deep learning",
    "blockchain": "blockchain distributed ledger smart contracts",
    "quantum": "quantum computing qubits superposition",
    "genomics": "genomics DNA sequencing genome",
    "cybersecurity": "cybersecurity network security cryptography",
    "robotics": "robotics automation control systems",
}

DOMAIN_SYNONYMS = {
    "control": {
        "biology": "regulation homeostasis feedback",
        "cs": "control flow systems"
    }
}


def expand_query(query: str) -> str:
    """
    Expand query with domain-specific synonyms.
    Keeps original query terms + adds expansions.
    """
    q = query.lower().strip()
    extras = []

    for term, expansion in EXPANSIONS.items():
        if term in q:
            extras.append(expansion)

    if extras:
        return q + " " + " ".join(extras)

    return q