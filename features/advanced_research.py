from __future__ import annotations

import math
import random
import string
from datetime import datetime, timezone

import requests

from db import resources, study_plans, users, saved
from embeddings import embed_query
from llm_client import call_llm
from search_engine import search


def _now_utc_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _paper_brief(p: dict) -> str:
    title = p.get("title", "Untitled")
    summary = (p.get("summary", "") or "")[:500]
    year = p.get("year")
    source = p.get("source", "")
    link = p.get("pdf", "")
    year_text = f" ({year})" if year else ""
    return f"- {title}{year_text} [{source}]\n  {summary}\n  {link}"


def build_citation_graph(link: str, max_refs: int = 8, max_citers: int = 8) -> dict:
    doc = resources.find_one({"pdf": link})
    if not doc:
        return {"error": "Paper not found in DB. Search it first with /study."}

    title = doc.get("title", "")
    if not title:
        return {"error": "Paper title missing."}

    search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": title, "limit": 1, "fields": "paperId,title,url"}

    try:
        r = requests.get(search_url, params=params, timeout=12)
        data = r.json()
    except Exception as e:
        return {"error": f"Citation API search failed: {e}"}

    items = data.get("data", [])
    if not items:
        return {"error": "Could not match this paper on Semantic Scholar."}

    paper_id = items[0].get("paperId")
    if not paper_id:
        return {"error": "Semantic Scholar did not return paper ID."}

    details_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
    detail_params = {
        "fields": "title,url,year,citationCount,references.title,references.url,citations.title,citations.url"
    }

    try:
        d = requests.get(details_url, params=detail_params, timeout=12)
        payload = d.json()
    except Exception as e:
        return {"error": f"Citation graph fetch failed: {e}"}

    refs = payload.get("references", [])[:max_refs]
    citers = payload.get("citations", [])[:max_citers]

    return {
        "title": payload.get("title", title),
        "url": payload.get("url", link),
        "year": payload.get("year"),
        "citation_count": payload.get("citationCount", 0),
        "references": [{"title": x.get("title", "Untitled"), "url": x.get("url", "")} for x in refs],
        "citations": [{"title": x.get("title", "Untitled"), "url": x.get("url", "")} for x in citers],
    }


def create_study_plan(user_id: int, topic: str, days: int, level: dict) -> dict:
    days = max(1, min(days, 30))
    papers, _ = search(topic, limit=min(20, max(8, days + 4)))

    if not papers:
        return {"error": "No papers found for this topic. Try /study first."}

    briefs = "\n".join(_paper_brief(p) for p in papers[:15])
    prompt = f"""You are creating a practical day-by-day research study plan.
Audience level: {level.get('short', 'Undergraduate')}.
Topic: {topic}
Duration: {days} days

Available resources:
{briefs}

Output rules:
- Return exactly {days} numbered days.
- Each day has: objective, 1-2 papers, and 1 actionable task.
- Keep each day compact (max 80 words).
- Prioritize logical progression from basics to advanced.

Return plain text only."""

    plan_text = call_llm(prompt, max_tokens=1200)
    if not plan_text:
        return {"error": "Could not generate plan right now."}

    study_plans.update_one(
        {"user_id": user_id, "topic": topic.lower().strip()},
        {
            "$set": {
                "user_id": user_id,
                "topic": topic.lower().strip(),
                "topic_display": topic,
                "days": days,
                "plan_text": plan_text,
                "updated_at": _now_utc_naive(),
            }
        },
        upsert=True,
    )

    return {"topic": topic, "days": days, "plan_text": plan_text}


def get_study_plan(user_id: int, topic: str | None = None) -> dict | None:
    q = {"user_id": user_id}
    if topic:
        q["topic"] = topic.lower().strip()
        return study_plans.find_one(q)
    return study_plans.find_one(q, sort=[("updated_at", -1)])


def generate_flashcards(doc: dict, level: dict, count: int = 8) -> str:
    abstract = (doc.get("summary") or "")[:2200]
    title = doc.get("title", "Untitled")
    prompt = f"""Create {count} flashcards for this paper.
Audience: {level.get('short', 'Undergraduate')}.

Paper title: {title}
Abstract:
{abstract}

Format strictly:
Q1: ...
A1: ...
Q2: ...
A2: ...

Make cards conceptual and exam-friendly. Plain text only."""

    cards = call_llm(prompt, max_tokens=900)
    return cards or "Could not generate flashcards right now."


def recommend_for_user(user_id: int, limit: int = 8) -> list:
    u = users.find_one({"user_id": user_id}) or {}
    history = [x.get("query", "") for x in u.get("search_history", [])[:8] if x.get("query")]
    saved_docs = list(saved.find({"user_id": user_id}, {"topic": 1}).limit(10))
    saved_topics = [x.get("topic", "") for x in saved_docs]

    basis = [t for t in history + saved_topics if t]
    if not basis:
        basis = ["machine learning", "study techniques"]

    query = ", ".join(basis[:4])
    results, _ = search(query, limit=limit * 2)

    seen = set()
    picked = []
    for r in results:
        pdf = r.get("pdf")
        if not pdf or pdf in seen:
            continue
        seen.add(pdf)
        picked.append(r)
        if len(picked) >= limit:
            break
    return picked


def generate_mindmap_from_papers(topic: str, papers: list, level: dict) -> str:
    snippets = "\n".join(_paper_brief(p) for p in papers[:10])
    prompt = f"""Create a concise Mermaid mindmap from these papers.
Topic: {topic}
Audience: {level.get('short', 'Undergraduate')}

{snippets}

Output ONLY Mermaid mindmap code using this format:
mindmap
  root((...))
    Branch
      Subtopic

No markdown fences."""
    graph = call_llm(prompt, max_tokens=900)
    if not graph:
        return "mindmap\n  root((Mindmap generation failed))"
    if not graph.strip().startswith("mindmap"):
        return "mindmap\n  root((" + topic[:40] + "))"
    return graph


def detect_overlap(text: str, limit: int = 5) -> list:
    q_vec = embed_query(text)
    if not q_vec:
        return []

    results = []
    try:
        pipe = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": q_vec,
                    "numCandidates": 80,
                    "limit": 20,
                }
            },
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {"$project": {"title": 1, "pdf": 1, "summary": 1, "score": 1, "embedding": 1}},
        ]
        results = list(resources.aggregate(pipe))
    except Exception:
        # Fallback to text search when vector index is unavailable.
        results = list(resources.find({"$text": {"$search": text[:120]}}, {"score": {"$meta": "textScore"}}).limit(20))

    out = []
    for r in results:
        score = float(r.get("score", 0.0))
        emb = r.get("embedding")
        if emb and q_vec:
            score = _cosine(q_vec, emb)
        out.append({
            "title": r.get("title", "Untitled"),
            "pdf": r.get("pdf", ""),
            "score": max(0.0, min(1.0, score)),
            "snippet": (r.get("summary", "") or "")[:220],
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def find_research_gaps(topic: str, level: dict) -> str:
    papers, _ = search(topic, limit=15)
    if not papers:
        return "No papers found for this topic yet."

    abstracts = "\n\n".join(f"{p.get('title','')}\n{(p.get('summary','') or '')[:450]}" for p in papers[:12])
    prompt = f"""Analyze these papers and identify research gaps.
Topic: {topic}
Audience: {level.get('short', 'Undergraduate')}

{abstracts}

Return:
1) 5 concrete gaps
2) Why each gap matters
3) 3 project ideas students can pursue
Keep under 500 words."""
    return call_llm(prompt, max_tokens=1000) or "Could not generate gaps right now."


def generate_literature_review(topic: str, level: dict) -> str:
    papers, _ = search(topic, limit=18)
    if not papers:
        return "No papers found for this topic yet."

    paper_block = "\n\n".join(_paper_brief(p) for p in papers[:15])
    prompt = f"""Write a structured literature review on: {topic}
Audience: {level.get('short', 'Undergraduate')}

Sources:
{paper_block}

Structure:
- Introduction
- Thematic clusters (at least 3)
- Methods used across studies
- Contradictions and limitations
- Future research directions
- Conclusion

Include in-text citation tags like [1], [2] that map to the given sources order.
Keep 700-1000 words."""
    return call_llm(prompt, max_tokens=1700) or "Could not generate literature review right now."


def generate_share_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))
