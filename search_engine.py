from db import resources
from embeddings import embed, embed_query
from functools import lru_cache
from constants import STOPWORDS
import re

VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.5
RRF_K = 60

DOMAIN_BOOST = {
    "pubmed": 1.3,
    "semantic_scholar": 1.15,
    "arxiv": 1.0,
    "mit_ocw": 0.9,
    "github": 0.8,
    "doab": 0.85
}

# Only crawl for more if fewer than this many results AND relevance is also poor
MIN_RESULTS_THRESHOLD = 5


@lru_cache(maxsize=200)
def get_query_embedding(query: str):
    return tuple(embed_query(query))


def vector_search(query: str, limit: int = 40):
    try:
        query_vector = get_query_embedding(query)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": list(query_vector),
                    "numCandidates": 120,
                    "limit": limit
                }
            },
            {
                "$addFields": {
                    "vector_score": {"$meta": "vectorSearchScore"}
                }
            }
        ]
        results = list(resources.aggregate(pipeline))
        print(f"[search] Vector search returned {len(results)} results")
        return results
    except Exception as e:
        print(f"[search] Vector search failed (Atlas vector index missing?): {e}")
        return []


def keyword_search(query: str, limit: int = 40):
    try:
        results = list(
            resources.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}}
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        print(f"[search] Keyword search returned {len(results)} results")
        return results
    except Exception as e:
        print(f"[search] Keyword search failed: {e}")
        return []


def fallback_search(query: str, limit: int = 40):
    """Regex fallback when both vector and keyword return nothing."""
    raw = re.split(r'[\s\-]+', query.lower())
    tokens = list(dict.fromkeys(
        t.strip(".,;:()") for t in raw
        if t.strip(".,;:()") and t.strip(".,;:()") not in STOPWORDS and len(t.strip(".,;:()")) > 3
    ))
    if not tokens:
        return []
    conditions = []
    for token in tokens:
        conditions.append({"title": {"$regex": token, "$options": "i"}})
        conditions.append({"summary": {"$regex": token, "$options": "i"}})
    results = list(resources.find({"$or": conditions}).limit(limit))
    print(f"[search] Fallback regex search returned {len(results)} results")
    return results


def hybrid_rank(vector_results, keyword_results, limit: int = 20):
    scores = {}
    combined = {}

    for rank, r in enumerate(vector_results):
        key = r["pdf"]
        combined[key] = r
        rrf = VECTOR_WEIGHT * (1.0 / (RRF_K + rank + 1))
        if "vector_score" in r:
            rrf += 0.1 * float(r["vector_score"])
        scores[key] = scores.get(key, 0) + rrf

    for rank, r in enumerate(keyword_results):
        key = r["pdf"]
        combined[key] = r
        rrf = KEYWORD_WEIGHT * (1.0 / (RRF_K + rank + 1))
        scores[key] = scores.get(key, 0) + rrf

    for key, r in combined.items():
        boost = DOMAIN_BOOST.get(r.get("source", "").lower(), 1.0)
        scores[key] = scores[key] * boost

    ranked = sorted(
        combined.values(),
        key=lambda r: scores.get(r["pdf"], 0),
        reverse=True
    )
    return ranked[:limit]


def score_result(r: dict, tokens: list[str]) -> float:
    """
    Score a single result against query tokens.
    Uses word-boundary matching to avoid 'metabolic' matching 'meta'.
    Weighs title matches more than summary matches.
    """
    title = r.get("title", "").lower()
    summary = r.get("summary", "").lower()

    title_score = 0.0
    summary_score = 0.0

    for token in tokens:
        # Check full word match (e.g. 'gut' shouldn't match 'gutsiest')
        # Simple approach: check token surrounded by non-alpha or at string boundaries
        pattern = r'(?<![a-z])' + re.escape(token) + r'(?![a-z])'
        if re.search(pattern, title):
            title_score += 1.0        # title match worth full point
        elif re.search(pattern, summary):
            summary_score += 0.6      # summary match worth 0.6

    total = title_score + summary_score
    return total / len(tokens)


def dynamic_threshold(tokens: list[str]) -> float:
    """
    Stricter threshold for longer queries, but capped so very long
    queries don't become impossible to satisfy.
    - 1 token:  0.3
    - 2 tokens: 0.4
    - 3 tokens: 0.5
    - 4+ tokens: 0.55 (capped — long queries have diminishing returns)
    """
    n = len(tokens)
    if n <= 1:
        return 0.3
    elif n == 2:
        return 0.4
    elif n == 3:
        return 0.5
    else:
        return 0.55  # capped: 4+ token queries shouldn't need 60%+ match


def relevance_filter(results, query: str):
    """
    Scores each result against query tokens using word-boundary matching.
    Applies a dynamic threshold based on query length.
    Returns (filtered_results, needs_crawl).
    """
    # Split on spaces AND hyphens so "liquid-liquid" becomes ["liquid", "liquid"]
    raw_tokens = re.split(r'[\s\-]+', query.lower())
    # Deduplicate while preserving order, drop stopwords and short tokens
    seen = set()
    tokens = []
    for t in raw_tokens:
        t = t.strip(".,;:()")
        if t and t not in STOPWORDS and len(t) > 3 and t not in seen:
            seen.add(t)
            tokens.append(t)

    if not tokens:
        return results, False

    threshold = dynamic_threshold(tokens)
    print(f"[search] Relevance threshold: {threshold:.1f} for {len(tokens)} tokens: {tokens}")

    scored = [(score_result(r, tokens), r) for r in results]

    # Sort by score descending for logging
    scored.sort(key=lambda x: x[0], reverse=True)

    # Log top results for debugging
    for score, r in scored[:5]:
        print(f"[search]   {score:.2f} | {r.get('title','')[:60]}")

    filtered = [r for score, r in scored if score >= threshold]

    if not filtered:
        print(f"[search] No results passed threshold {threshold:.1f} — needs crawl")
        return [], True

    top_score = scored[0][0]
    low_relevance = top_score < 0.5
    low_count = len(filtered) < MIN_RESULTS_THRESHOLD
    needs_crawl = low_relevance and low_count

    print(f"[search] needs_crawl={needs_crawl} (top_score={top_score:.2f}, passed={len(filtered)})")

    return filtered, needs_crawl



def search_related(query: str, current_pdf: str, limit: int = 5):
    """
    Find related papers using a clean short query (topic field from DB).
    Uses lenient single-token matching — just needs 1 key term to match.
    """
    print(f"[search] Related query: '{query}'")

    if not query:
        return []

    vector_results = vector_search(query, limit=20)
    keyword_results = keyword_search(query, limit=20)

    if not vector_results and not keyword_results:
        candidates = fallback_search(query, limit=20)
    else:
        candidates = hybrid_rank(vector_results, keyword_results, limit=20)

    # Remove the paper itself from results
    candidates = [r for r in candidates if r.get("pdf") != current_pdf]

    # Get meaningful tokens from the topic query
    raw = re.split(r'[\s\-]+', query.lower())
    tokens = list(dict.fromkeys(
        t.strip(".,;:()") for t in raw
        if t.strip(".,;:()") and t.strip(".,;:()") not in STOPWORDS and len(t.strip(".,;:()")) > 3
    ))

    if not tokens:
        return candidates[:limit]

    # Require at least 1 token match — very lenient, just confirms relevance
    scored = []
    for r in candidates:
        text = (r.get("title", "") + " " + r.get("summary", "")).lower()
        match = any(
            re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', text)
            for t in tokens
        )
        if match:
            scored.append(r)

    print(f"[search] Related papers found: {len(scored[:limit])}")
    return scored[:limit]



def search(query: str, limit: int = 20):
    """
    Returns (results, needs_crawl).
    needs_crawl=True means the bot should trigger on-demand indexing.
    """
    print(f"[search] Query: '{query}'")

    total_docs = resources.count_documents({})
    print(f"[search] Total docs in DB: {total_docs}")

    if total_docs == 0:
        print("[search] DB empty — crawler hasn't run yet")
        return [], True

    vector_results = vector_search(query, limit=40)
    keyword_results = keyword_search(query, limit=40)

    if not vector_results and not keyword_results:
        print("[search] Both searches empty — trying fallback")
        fallback = fallback_search(query, limit=limit)
        if fallback:
            filtered, needs_crawl = relevance_filter(fallback, query)
            return (filtered or fallback)[:limit], True
        return [], True

    ranked = hybrid_rank(vector_results, keyword_results, limit=limit * 2)
    filtered, needs_crawl = relevance_filter(ranked, query)

    # If nothing passed relevance filter, return empty so bot crawls instead of showing junk
    if not filtered:
        print(f"[search] Relevance filter rejected all results — returning empty for crawl")
        return [], True

    print(f"[search] Final results: {len(filtered[:limit])}")
    return filtered[:limit], needs_crawl