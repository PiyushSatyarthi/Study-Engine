"""
Search suggestions — generated from actual indexed topics in the DB,
not a hardcoded lookup table. Falls back to hardcoded if DB is empty.
"""
import re
from db import resources
from constants import QUESTION_STOPWORDS as STOPWORDS


def get_suggestions(query: str, n: int = 3) -> list:
    """
    Find related topics by looking at what's actually indexed in the DB
    for the same broad subject area. Uses the topic field on resources.

    Requires topics to share at least 2 meaningful tokens with the query
    (or all tokens if query has only 1). This prevents cross-domain pollution
    like "cell" in a physics query matching biology topics.
    """
    q = query.lower().strip()

    tokens = [
        t.strip(".,;:()?!")
        for t in q.split()
        if len(t.strip(".,;:()?!")) > 3
        and t.strip(".,;:()?!") not in STOPWORDS
    ]

    if not tokens:
        return []

    # Require topics match at least 2 tokens (or all if query has only 1)
    min_overlap = min(2, len(tokens))

    # Find distinct topics in DB that contain any of these tokens
    regex_parts = [{"topic": {"$regex": t, "$options": "i"}} for t in tokens]

    try:
        pipeline = [
            {"$match": {"$or": regex_parts}},
            {"$group": {"_id": "$topic", "count": {"$sum": 1}}},
            {"$limit": 50}
        ]
        results = list(resources.aggregate(pipeline))
        topics = [r["_id"] for r in results if r["_id"]]

        seen_tokens = set(tokens)
        suggestions = []
        scored = []

        for t in topics:
            t_lower = t.lower()
            if t_lower == q:
                continue
            t_tokens = set(
                w.strip(".,;:()?!") for w in t_lower.split()
                if len(w.strip(".,;:()?!")) > 3 and w not in STOPWORDS
            )
            # Skip if it shares ALL tokens with query (near-duplicate)
            if t_tokens and t_tokens.issubset(seen_tokens):
                continue
            # Count how many query tokens appear in this topic
            overlap = sum(1 for tok in tokens if tok in t_lower)
            if overlap >= min_overlap:
                scored.append((overlap, t))

        # Sort by overlap descending — topics sharing more tokens rank higher
        scored.sort(key=lambda x: x[0], reverse=True)
        suggestions = [t for _, t in scored[:n]]

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
