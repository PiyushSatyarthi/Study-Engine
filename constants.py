"""Shared constants used across multiple modules."""

# Grammar-only stopwords for search query tokenisation.
# Keep domain terms OUT of this set — words like "effect", "role", "impact"
# carry meaning in academic search queries.
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for",
    "and", "or", "is", "it", "its", "be", "by", "as", "with",
    "using", "via", "from", "into", "that",
    "this", "their", "which", "have", "has", "are", "was", "were",
    "not", "but", "based",
}

# Extended stopwords for assignment / question parsing.
# Includes question verbs and generic academic terms that add noise
# when extracting *topics* from a question stem.
QUESTION_STOPWORDS = STOPWORDS | {
    "study", "what", "how", "why", "does", "explain", "discuss", "define",
    "role", "impact", "effect", "process", "between",
}
