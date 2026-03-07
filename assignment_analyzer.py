import os
import re
import time
import requests

# ── LLM config ────────────────────────────────────────────────────────────────
# Set LLM_PROVIDER=groq in .env to use Groq instead of Ollama
# Groq is ~50x faster and free up to 14400 req/day
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()  # "ollama" | "groq"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Crawl settings
CRAWL_WAIT_TIMEOUT = 120
CRAWL_POLL_INTERVAL = 8


# ── LLM call (Ollama or Groq) ─────────────────────────────────────────────────

def _call_llm(prompt: str, max_tokens: int = 800, temperature: float = 0.3) -> str:
    if LLM_PROVIDER == "groq":
        return _call_groq(prompt, max_tokens, temperature)
    return _call_ollama(prompt, max_tokens, temperature)


def _call_ollama(prompt: str, max_tokens: int, temperature: float) -> str:
    try:
        r = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": max_tokens, "temperature": temperature},
                "stream": False
            },
            timeout=180
        )
        return r.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[assignment] Ollama call failed: {e}")
        return ""


def _call_groq(prompt: str, max_tokens: int, temperature: float) -> str:
    if not GROQ_API_KEY:
        print("[assignment] GROQ_API_KEY not set — falling back to Ollama")
        return _call_ollama(prompt, max_tokens, temperature)
    try:
        r = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[assignment] Groq call failed: {e} — falling back to Ollama")
        return _call_ollama(prompt, max_tokens, temperature)


# ── Question type inference ───────────────────────────────────────────────────

def _infer_type(question: str) -> str:
    q = question.lower().strip()
    numerical_kw = ("calculate", "compute", "find the value", "solve", "how many", "how much",
                    "what is the value", "determine the", "evaluate the expression")
    definition_kw = ("define ", "what do you mean by", "what is meant by", "give the definition")
    essay_kw = ("discuss", "critically", "analyze", "analyse", "evaluate", "compare and contrast",
                "assess", "justify", "to what extent", "examine the")
    explain_kw = ("explain", "describe the process", "how does", "how do", "why does",
                  "why do", "what happens when", "describe how", "outline the")

    for kw in numerical_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "numerical"
    for kw in definition_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "definition"
    for kw in essay_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "essay"
    for kw in explain_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "explain"
    return "factual"


# ── Question extraction ───────────────────────────────────────────────────────

def extract_questions(text: str) -> list:
    prompt = f"""You are analyzing a student assignment. Extract every question from the text below.

For each question:
1. Assign a number (1, 2, 3...)
2. Copy the question EXACTLY as written
3. Classify type using EXACTLY one label:
   - factual    → "What is...", "Name...", "List...", "State..."
   - essay      → "Discuss...", "Critically analyze...", "Evaluate...", "Compare and contrast..."
   - explain    → "Explain how/why...", "Describe the process of...", "How does... work?"
   - numerical  → "Calculate...", "Find the value...", "Compute...", "Solve..."
   - definition → "Define...", "What do you mean by...", "What is meant by..."

Examples:
1. [factual] What is the function of mitochondria?
2. [essay] Discuss the impact of CRISPR-Cas9 on gene therapy.
3. [explain] Explain the process of DNA replication and the enzymes involved.
4. [numerical] Calculate the velocity given distance 100m and time 5s.
5. [definition] Define insulin resistance.
6. [explain] How does the immune system respond to viral infections?

Return ONLY the numbered list. One question per line. No extra text.

Assignment text:
{text[:3000]}

Extract all questions:"""

    response = _call_llm(prompt, max_tokens=600)
    questions = []
    pattern = re.compile(r'^(\d+)\.\s+\[(\w+)\]\s+(.+)$', re.MULTILINE)

    for match in pattern.finditer(response):
        num, qtype, question = match.groups()
        qtype = qtype.lower().strip()
        if qtype not in ("factual", "essay", "explain", "numerical", "definition"):
            qtype = _infer_type(question)
        questions.append({"number": int(num), "question": question.strip(), "type": qtype})

    if not questions:
        lines = re.split(r'\n(?=\d+[\.\)])', text.strip())
        for i, line in enumerate(lines, 1):
            clean = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            if len(clean) > 10:
                questions.append({"number": i, "question": clean, "type": _infer_type(clean)})

    return questions


# ── Topic generation ──────────────────────────────────────────────────────────

def get_search_topics(questions: list) -> list:
    q_text = "\n".join(f"{q['number']}. {q['question']}" for q in questions)

    prompt = f"""For each assignment question below, suggest 1-3 specific academic search topics.
Topics must be precise and searchable — not generic subject names.

Good examples:
- "What is the role of mitochondria in cellular respiration?" → "mitochondria ATP synthesis, oxidative phosphorylation"
- "Explain DNA replication" → "DNA replication enzymes, DNA polymerase mechanism, replication fork"
- "Discuss CRISPR-Cas9 gene therapy" → "CRISPR-Cas9 gene editing, CRISPR therapeutic applications"
- "How does the immune system respond to viruses?" → "innate immune response viral infection, T cell activation antiviral"

Return ONLY in this exact format, one line per question:
1. topic1, topic2
2. topic1, topic2, topic3

Questions:
{q_text}

Topics:"""

    response = _call_llm(prompt, max_tokens=400)
    topic_map = {}

    for line in response.strip().split('\n'):
        match = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
        if match:
            num = int(match.group(1))
            topics = [t.strip() for t in match.group(2).split(',') if t.strip()]
            topic_map[num] = topics[:3]

    for q in questions:
        q['topics'] = topic_map.get(q['number'], [q['question']])

    return questions


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _score_paper_relevance(paper: dict, question: str, topics: list) -> float:
    title = paper.get('title', '').lower()
    summary = paper.get('summary', '').lower()
    combined = title + " " + summary

    all_text = question.lower() + " " + " ".join(topics).lower()
    raw_tokens = re.split(r'[\s\-,]+', all_text)
    stopwords = {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
        "is", "it", "its", "be", "by", "as", "with", "that", "this", "are",
        "what", "how", "why", "does", "do", "explain", "discuss", "describe",
        "define", "role", "impact", "effect", "effects", "process", "between"
    }
    tokens = list(dict.fromkeys(
        t.strip(".,;:()") for t in raw_tokens
        if len(t.strip(".,;:()")) > 3 and t.strip(".,;:()") not in stopwords
    ))

    if not tokens:
        return 0.5

    matches = sum(
        1 for t in tokens
        if re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', combined)
    )
    return matches / len(tokens)


def _filter_relevant_papers(papers: list, question: str, topics: list, min_score: float = 0.15):
    scored = sorted(
        [(_score_paper_relevance(p, question, topics), p) for p in papers],
        key=lambda x: x[0], reverse=True
    )
    for score, p in scored:
        print(f"[assignment] relevance={score:.2f} | {p.get('title', '')[:60]}")

    relevant = [(s, p) for s, p in scored if s >= min_score]
    if not relevant:
        relevant = scored[:2]

    return [p for _, p in relevant], [s for s, _ in relevant]


def _compute_confidence(papers: list, scores: list) -> str:
    if not papers or not scores:
        return "⚪ No papers"
    avg = sum(scores) / len(scores)
    if len(papers) >= 3 and avg >= 0.3:
        return "🟢 High"
    elif len(papers) >= 2 and avg >= 0.15:
        return "🟡 Medium"
    else:
        return "🔴 Low"


# ── Paper gathering ───────────────────────────────────────────────────────────

def _gather_relevant_papers(question: str, topics: list, min_relevant: int = 2) -> list:
    from search_engine import search as engine_search
    from crawler_worker import index_topic

    all_candidates = {}

    for topic in topics:
        results, _ = engine_search(topic, limit=8)
        for r in results:
            all_candidates[r['pdf']] = r

    results, _ = engine_search(question, limit=8)
    for r in results:
        all_candidates[r['pdf']] = r

    candidates = list(all_candidates.values())
    print(f"[assignment] {len(candidates)} candidates before relevance filter")

    scored = sorted(
        [(_score_paper_relevance(p, question, topics), p) for p in candidates],
        key=lambda x: x[0], reverse=True
    )

    for score, p in scored[:6]:
        print(f"[assignment]   {score:.2f} | {p.get('title', '')[:60]}")

    good = [(s, p) for s, p in scored if s >= 0.2]

    if len(good) >= min_relevant:
        return [p for _, p in good[:6]]

    primary = topics[0] if topics else question
    print(f"[assignment] Crawling '{primary}' for gap fill...")

    try:
        index_topic(primary)
    except Exception as e:
        print(f"[assignment] Crawl error: {e}")

    deadline = time.time() + CRAWL_WAIT_TIMEOUT
    while time.time() < deadline:
        new_results, _ = engine_search(primary, limit=10)
        for r in new_results:
            all_candidates[r['pdf']] = r

        scored = sorted(
            [(_score_paper_relevance(p, question, topics), p)
             for p in all_candidates.values()],
            key=lambda x: x[0], reverse=True
        )
        good = [(s, p) for s, p in scored if s >= 0.2]

        if len(good) >= min_relevant:
            print(f"[assignment] Gap filled — {len(good)} relevant papers")
            return [p for _, p in good[:6]]

        time.sleep(CRAWL_POLL_INTERVAL)

    print(f"[assignment] Timeout — using top {min(3, len(scored))} by score")
    return [p for _, p in scored[:3]]


# ── Answer generation ─────────────────────────────────────────────────────────

def generate_answer(question: dict, papers: list) -> dict:
    q_type = question.get('type', 'factual')
    topics = question.get('topics', [])

    if q_type == 'numerical':
        return {
            "number": question['number'],
            "question": question['question'],
            "type": q_type,
            "answer": (
                "⚠️ This is a calculation question — I can't solve numerical problems.\n\n"
                "Relevant theory topics: " + ", ".join(topics)
            ),
            "sources": [],
            "confidence_label": "⚪ N/A",
            "papers_found": 0
        }

    if not papers:
        return {
            "number": question['number'],
            "question": question['question'],
            "type": q_type,
            "answer": (
                "⚠️ Could not find relevant research papers for this question "
                "even after searching academic databases.\n\n"
                "Try: /study " + (topics[0] if topics else question['question'])
            ),
            "sources": [],
            "confidence_label": "⚪ No papers",
            "papers_found": 0
        }

    relevant_papers, scores = _filter_relevant_papers(papers, question['question'], topics)
    confidence_label = _compute_confidence(relevant_papers, scores)

    context_parts = []
    sources_used = []

    for paper in relevant_papers[:4]:
        title = paper.get('title', '')
        summary = paper.get('summary', '')[:400]
        source = paper.get('source', '')
        pdf = paper.get('pdf', '')
        context_parts.append(f'Title: "{title}"\nSource: {source}\n{summary}')
        sources_used.append({"title": title, "source": source, "link": pdf})

    context = "\n\n".join(context_parts)

    cite_rule = (
        'IMPORTANT: Cite papers by their exact title in quotes — '
        'e.g. "According to \\"Mitochondria and Cellular Respiration\\"..."\n'
        'NEVER say "Paper 1", "Paper 2", or refer to papers by number.\n'
        'NEVER invent information not found in the papers provided.\n'
    )

    if q_type == 'essay':
        prompt = f"""Write an essay answer using ONLY the research papers provided.

{cite_rule}
Structure:
- Introduction (1-2 sentences)
- 2-3 key arguments citing paper titles
- Conclusion (1 sentence)

Question: {question['question']}

Research papers:
{context}

Essay answer:"""

    elif q_type == 'explain':
        prompt = f"""Explain clearly using ONLY the research papers provided.
Cover the mechanism or process step by step. Keep under 120 words.

{cite_rule}

Question: {question['question']}

Research papers:
{context}

Explanation:"""

    elif q_type == 'definition':
        prompt = f"""Define precisely using the research papers provided.
Keep under 60 words. Include field and significance.

{cite_rule}

Question: {question['question']}

Research papers:
{context}

Definition:"""

    else:  # factual
        prompt = f"""Answer directly and concisely using ONLY the research papers provided.
Keep under 80 words.

{cite_rule}

Question: {question['question']}

Research papers:
{context}

Answer:"""

    answer_text = _call_llm(prompt, max_tokens=450, temperature=0.2)

    return {
        "number": question['number'],
        "question": question['question'],
        "type": q_type,
        "answer": answer_text,
        "sources": sources_used,
        "confidence_label": confidence_label,
        "papers_found": len(relevant_papers)
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze_assignment(text: str, mode: str = "topics") -> dict:
    """
    mode = "topics"  → extract + classify questions + suggest topics (fast, ~20s)
    mode = "answers" → full pipeline: search, crawl if needed, generate answers
    """
    questions = extract_questions(text)

    if not questions:
        return {
            "error": "Could not find any questions in the text. Make sure questions are clearly numbered or separated.",
            "questions": [], "total": 0
        }

    questions = get_search_topics(questions)

    if mode == "topics":
        return {"questions": questions, "mode": "topics", "total": len(questions)}

    for q in questions:
        print(f"\n[assignment] === Q{q['number']}: {q['question'][:60]} ===")
        q['papers'] = _gather_relevant_papers(
            question=q['question'],
            topics=q.get('topics', []),
            min_relevant=2
        )
        print(f"[assignment] Final papers for Q{q['number']}: {len(q['papers'])}")

    for q in questions:
        result = generate_answer(q, q.get('papers', []))
        q.update(result)

    return {"questions": questions, "mode": "answers", "total": len(questions)}