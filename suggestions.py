"""
Search suggestions — generated from actual indexed topics in the DB,
not a hardcoded lookup table. Falls back to hardcoded if DB is empty.
"""
from db import resources


def get_suggestions(query: str, n: int = 3) -> list:
    """
    Find related topics by looking at what's actually indexed in the DB
    for the same broad subject area. Uses the topic field on resources.

    Much better than the old approach of appending 'applications' / 'deep learning'
    to whatever the first token was.
    """
    q = query.lower().strip()

    # Pull topics from DB that share meaningful tokens with the query
    # Exclude stopwords and the query itself
    stopwords = {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
        "is", "it", "its", "what", "how", "why", "does", "explain", "discuss",
        "define", "role", "impact", "effect", "process", "between", "with",
        "that", "this", "are", "was", "were", "have", "has", "using", "based"
    }
    tokens = [
        t.strip(".,;:()?!")
        for t in q.split()
        if len(t.strip(".,;:()?!")) > 3
        and t.strip(".,;:()?!") not in stopwords
    ]

    if not tokens:
        return []

    # Find distinct topics in DB that contain any of these tokens
    # Use a $or regex match on the topic field
    import re
    regex_parts = [{"topic": {"$regex": t, "$options": "i"}} for t in tokens]

    try:
        pipeline = [
            {"$match": {"$or": regex_parts}},
            {"$group": {"_id": "$topic", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20}
        ]
        results = list(resources.aggregate(pipeline))
        topics = [r["_id"] for r in results if r["_id"]]

        # Filter out topics that are too similar to the original query
        # and deduplicate near-duplicates
        seen_tokens = set(tokens)
        suggestions = []
        for t in topics:
            t_lower = t.lower()
            # Skip if it's basically the same as the query
            if t_lower == q:
                continue
            t_tokens = set(
                w.strip(".,;:()?!") for w in t_lower.split()
                if len(w.strip(".,;:()?!")) > 3 and w not in stopwords
            )
            # Skip if it shares ALL tokens with query (near-duplicate)
            if t_tokens and t_tokens.issubset(seen_tokens):
                continue
            suggestions.append(t)
            if len(suggestions) >= n:
                break

        if suggestions:
            return suggestions

    except Exception as e:
        print(f"[suggestions] DB query failed: {e}")

    # Hardcoded fallback for when DB has no indexed topics yet
    FALLBACK = {
        "machine learning": ["deep learning", "neural networks", "reinforcement learning"],
        "blockchain": ["smart contracts", "consensus algorithms", "DeFi protocols"],
        "genomics": ["CRISPR gene editing", "DNA sequencing", "epigenetics"],
        "quantum": ["quantum entanglement", "quantum error correction", "qubits"],
        "metabolism": ["metabolic pathways", "enzyme kinetics", "mitochondria"],
        "cybersecurity": ["cryptography", "network intrusion detection", "zero-day exploits"],
        "robotics": ["robot kinematics", "SLAM navigation", "reinforcement learning robotics"],
        "drug": ["molecular docking", "QSAR models", "clinical trials"],
        "climate": ["carbon capture", "renewable energy", "climate modeling"],
        "nlp": ["transformer models", "large language models", "sentiment analysis"],
        "neural": ["backpropagation", "convolutional networks", "attention mechanism"],
        "cancer": ["tumor microenvironment", "immunotherapy", "oncogenes"],
        "protein": ["protein folding", "molecular dynamics", "enzyme structure"],
    }
    for key, suggestions in FALLBACK.items():
        if key in q:
            return suggestions[:n]

    return []
