"""Search suggestions (free feature). Suggests related topics after a search."""

TOPIC_EXPANSIONS = {
    "machine learning": ["deep learning", "neural networks", "reinforcement learning"],
    "blockchain": ["smart contracts", "consensus algorithms", "DeFi"],
    "genomics": ["CRISPR gene editing", "DNA sequencing", "epigenetics"],
    "quantum computing": ["quantum entanglement", "quantum error correction", "qubits"],
    "metabolism": ["metabolic pathways", "enzyme kinetics", "mitochondria"],
    "cybersecurity": ["cryptography", "network intrusion detection", "zero-day exploits"],
    "robotics": ["robot kinematics", "SLAM navigation", "reinforcement learning robotics"],
    "drug discovery": ["molecular docking", "QSAR models", "clinical trials"],
    "climate": ["carbon capture", "renewable energy", "climate modeling"],
    "NLP": ["transformer models", "large language models", "sentiment analysis"],
}


def get_suggestions(query: str, n: int = 3) -> list[str]:
    """
    Returns n topic suggestions based on the query.
    Uses keyword matching with fallback to token-based suggestions.
    """
    q = query.lower()

    # Direct match
    for key, suggestions in TOPIC_EXPANSIONS.items():
        if key in q:
            return suggestions[:n]

    # Token match — find any expansion key appearing in the query
    tokens = q.split()
    for token in tokens:
        for key, suggestions in TOPIC_EXPANSIONS.items():
            if token in key or key in token:
                return suggestions[:n]

    # Generic fallback based on first meaningful token
    meaningful = [t for t in tokens if len(t) > 4]
    if meaningful:
        base = meaningful[0]
        return [
            f"{base} applications",
            f"{base} recent advances",
            f"{base} deep learning",
        ][:n]

    return []
