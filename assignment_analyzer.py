import os
import re
import time
import requests
from features.assignment_kb import find_similar_answer, store_answer, format_kb_result

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
    q = question.lower().strip().rstrip("?.")

    numerical_kw = (
        "calculate", "compute", "find the value", "solve", "how many", "how much",
        "what is the value", "determine the", "evaluate the expression"
    )
    # "define" with space, colon, or comma — e.g. "Define: X", "Define X and Y"
    # "what is X" as a short conceptual question also maps to definition
    definition_kw = (
        "define ", "define:", "define,",
        "what do you mean by", "what is meant by",
        "give the definition", "give a definition",
        "what is a ", "what is an ", "what are ",
    )
    essay_kw = (
        "discuss", "critically", "analyze", "analyse", "evaluate",
        "compare and contrast", "assess", "justify", "to what extent", "examine the"
    )
    explain_kw = (
        "explain", "describe the process", "how does", "how do", "why does",
        "why do", "what happens when", "describe how", "outline the",
        "describe the mechanism", "describe the structure"
    )
    # "what is the function/role/purpose/effect/significance of" → keep as factual
    _factual_what_is = re.compile(
        r'what is the (function|role|purpose|effect|significance|importance|use|mechanism)',
        re.IGNORECASE
    )

    for kw in numerical_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "numerical"
    for kw in definition_kw:
        if q.startswith(kw) or kw in q[:50]:
            return "definition"
    # "What is X?" / "What is X? Describe" — X is a concept/term with no article
    # Must NOT match "What is the function of X" (handled above as factual)
    if q.startswith("what is ") and not _factual_what_is.match(q):
        return "definition"
    for kw in essay_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "essay"
    for kw in explain_kw:
        if q.startswith(kw) or kw in q[:40]:
            return "explain"
    return "factual"


# ── Assignment header stripping ───────────────────────────────────────────────

# Lines matching these patterns are header/metadata noise, not questions
_NOISE_PATTERNS = [
    re.compile(r'^\s*(page\s*\d+|printed\s*pages?|school\s+of|department\s+of|'
               r'programme:|semester:|course\s*(title|code):|max\s*marks:|'
               r'session:|assignment[\s\-]*\d*[,:]|instructions?:|'
               r'all\s+questions\s+(are\s+)?compulsory|assume\s+missing|'
               r'btl\s+level|blooms?\s+taxonomy|course\s+outcome|'
               r'section\s+[a-z]\s*[\(\[]|unit\s+\d|co\d+:|'
               r'distribution\s+of\s+question|marks\s+among|'
               r'paper\s+setter|dr\.?\s+[a-z]|prof\.?\s+[a-z]|'
               r'\(dr\.?\s|\(prof\.?\s|'
               r'(\d+\s*[×x\*]\s*\d+\s*=\s*\d+)|marks\s*:\s*\d+)', re.IGNORECASE),
    re.compile(r'^\s*[\|\+][\s\|\+\-]+$'),  # table border rows
    re.compile(r'^\s*(k\d*|co\d+|unit\s*\d+|btl|bloom)\s*$', re.IGNORECASE),
]

_QUESTION_STARTERS = re.compile(
    r'(^|\s)(explain|define|what|describe|discuss|calculate|compute|'
    r'evaluate|analyze|analyse|illustrate|compare|list|name|state|'
    r'differentiate|enumerate|outline|justify|how|why|write)\b',
    re.IGNORECASE
)

# Matches academic table rows: "1 Explain Fluid mosaic model. Unit 1 CO1"
# Also handles: "2 What is cell? Describe Unit 1 CO1"
# Group 1 = row number, Group 2 = question text (everything before table code markers)
_TABLE_ROW_RE = re.compile(
    r'^\s*(\d{1,2})\s+'                          # leading question number (1–99)
    r'([A-Z].+?)'                                 # question text (lazy)
    r'(?:\s+(?:Unit\s+\d|CO\d+|BTL|Section\s+[A-Z]|K\d?)\b.*)?$',
    re.MULTILINE
)


def _extract_from_table_rows(text: str) -> str:
    """
    Handle the common Indian academic assignment table format:
        Q.No.  Question text            Unit  COs  K
        1      Explain Fluid mosaic model.  1   CO1  K2
        2      What is cell? Describe       1   CO1  K1

    Extracts only the clean question text, strips trailing table codes.
    Returns clean numbered lines, or "" if no table rows detected.
    """
    matches = _TABLE_ROW_RE.findall(text)
    if not matches:
        return ""

    lines = []
    for num, question in matches:
        q = question.strip()
        # Drop if it's still noise (e.g. "1 All questions are compulsory.")
        if any(p.search(q) for p in _NOISE_PATTERNS):
            continue
        # Must contain a real question word
        if not _QUESTION_STARTERS.search(q):
            continue
        lines.append(f"{num}. {q}")

    return "\n".join(lines)


def _strip_assignment_header(text: str) -> str:
    """
    Remove assignment metadata and noise from PDF-extracted assignment text.

    Stage 1 — Table pre-parser (preferred):
        Detects "N  Question text.  Unit X  COX" rows (Indian academic format)
        and returns only the clean question lines. This is much more reliable
        than asking the LLM to ignore surrounding noise.

    Stage 2 — Line filter (fallback):
        Walks line by line, drops known noise patterns, keeps lines that
        contain question words. Used when no table rows are detected.
    """
    # Stage 1: table row extraction
    table_result = _extract_from_table_rows(text)
    if table_result:
        return table_result

    # Stage 2: line-by-line noise filter
    lines = text.split('\n')
    cleaned = []
    found_first_question = False

    for line in lines:
        stripped = line.strip()
        if not stripped and not found_first_question:
            continue

        is_noise = any(p.search(stripped) for p in _NOISE_PATTERNS)
        has_question_word = bool(_QUESTION_STARTERS.search(stripped))
        looks_like_question = (
            has_question_word
            and len(stripped) > 15
            and not re.match(
                r'^(explain|describe|define|discuss)\s+the\s+(following|below)\s*:?\s*$',
                stripped, re.IGNORECASE
            )
        )

        if looks_like_question:
            found_first_question = True

        if found_first_question and not is_noise:
            cleaned.append(line)
        elif not found_first_question and not is_noise and len(stripped) > 20:
            cleaned.append(line)

    return '\n'.join(cleaned).strip()


# ── Question extraction ───────────────────────────────────────────────────────

def extract_questions(text: str) -> list:
    # Strip headers and noise before sending to LLM
    cleaned_text = _strip_assignment_header(text)
    if not cleaned_text:
        cleaned_text = text  # fallback: use original if stripping removed everything

    prompt = f"""You are extracting exam questions from a student assignment paper.

STRICT RULES — read carefully:
1. Extract ONLY actual questions that a student must answer.
2. IGNORE completely:
   - University/college/department names and headers
   - Course codes, course titles, max marks, session years
   - Instructions like "All questions are compulsory", "Assume missing data"
   - Section headers like "Section A", "Section B", "Unit 1", "Unit 2"
   - Table headers like "Q.No.", "BTL Level", "CO1", "CO2", "COs", "Marks"
   - Grading/marking schemes and distribution tables
   - Page numbers, "Printed Pages", professor names
   - Anything that is NOT a question requiring a student answer
3. A real question MUST contain a question word or instruction verb:
   Explain / Define / What / Describe / Discuss / Calculate / Evaluate /
   Illustrate / Compare / List / Name / State / Differentiate / How / Why
4. If the same question appears in both a table cell AND as a standalone line, extract it ONCE.
5. Extract each question SEPARATELY — do not combine multiple questions into one.

For each real question found:
- Assign sequential number (1, 2, 3...)
- Copy the question text EXACTLY, without table codes (Unit 1, CO1, K etc.)
- Classify type:
  [definition] → "Define X", "What is X?", "What are X?", "What is a/an X?"
  [explain]    → "Explain...", "How does...", "Why does...", "Describe the process of..."
  [essay]      → "Discuss...", "Critically analyze...", "Evaluate...", "Compare and contrast..."
  [numerical]  → "Calculate...", "Compute...", "Find the value...", "Solve..."
  [factual]    → "Name...", "List...", "State...", "What is the function/role of..."

Examples of what to EXTRACT:
1. [explain] Explain Fluid mosaic model.
2. [definition] What is cell? Describe.
3. [definition] What are different types of cells?
4. [numerical] Calculate the velocity given distance 100m and time 5s.

Examples of what to IGNORE (these are NOT questions):
- "School of Bioscience and Technology"
- "All questions are compulsory"
- "BTL Level"
- "Instructions: Assume missing data suitably"
- "Section A (8×2=12 Marks)"
- "Unit 1 CO1"
- "Q.No. Section A"
- "Distribution of question & marks"
- "Page 1 of 1"
- "(Dr Vineeta Yadav)"

Return ONLY the numbered question list. One question per line. No extra text.
If you find no real questions, return: NO_QUESTIONS_FOUND

Assignment text:
{cleaned_text[:3500]}

Questions:"""

    response = _call_llm(prompt, max_tokens=600)

    # Immediate failure signal
    if "NO_QUESTIONS_FOUND" in response or not response.strip():
        return []

    questions = []
    pattern = re.compile(r'^(\d+)\.\s+\[(\w+)\]\s+(.+)$', re.MULTILINE)

    for match in pattern.finditer(response):
        num, qtype, question = match.groups()
        question = question.strip()

        # Final noise guard: skip if extracted "question" looks like metadata
        if any(p.search(question) for p in _NOISE_PATTERNS):
            continue
        # Skip if no question word at all (likely a header that slipped through)
        if not _QUESTION_STARTERS.search(question) and len(question) < 60:
            continue

        qtype = qtype.lower().strip()
        if qtype not in ("factual", "essay", "explain", "numerical", "definition"):
            qtype = _infer_type(question)
        questions.append({"number": len(questions) + 1, "question": question, "type": qtype})

    # Fallback: line-split on numbered lines IF LLM returned nothing useful
    if not questions:
        lines = re.split(r'\n(?=\d+[\.\)])', cleaned_text.strip())
        for line in lines:
            clean = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            # Only keep lines that look like actual questions
            if (len(clean) > 15
                    and _QUESTION_STARTERS.search(clean)
                    and not any(p.search(clean) for p in _NOISE_PATTERNS)):
                questions.append({
                    "number": len(questions) + 1,
                    "question": clean,
                    "type": _infer_type(clean)
                })

    return questions


# ── Topic generation ──────────────────────────────────────────────────────────

def get_search_topics(questions: list, level: dict | None = None) -> list:
    q_text = "\n".join(f"{q['number']}. {q['question']}" for q in questions)

    prompt = f"""For each assignment question below, suggest 1-3 specific academic search topics.
Topics must be precise enough to find the EXACT concept, model, or theory being asked about.

Rules:
- For named models/theories: include the model name AND inventor/year if known
  e.g. "Fluid Mosaic Model" → "fluid mosaic model Singer Nicolson 1972, cell membrane protein lateral movement"
- For mechanisms: include the specific process and key components
  e.g. "DNA replication" → "DNA replication fork mechanism, DNA polymerase helicase primase"
- For diseases/conditions: include the condition and its molecular basis
  e.g. "insulin resistance" → "insulin resistance glucose transporter, type 2 diabetes pathophysiology"
- Always include the EXACT name of the concept as one topic
- Never use generic terms like "biology" or "chemistry" alone

Good examples:
- "Explain Fluid Mosaic Model" → "fluid mosaic model Singer Nicolson, cell membrane phospholipid proteins lateral movement"
- "Explain DNA replication" → "DNA replication fork mechanism, DNA polymerase helicase primase"
- "Discuss CRISPR-Cas9 gene therapy" → "CRISPR-Cas9 gene editing mechanism, CRISPR therapeutic applications"
- "How does the immune system respond to viruses?" → "innate immune response viral infection, T cell antiviral activation"
- "Define apoptosis" → "apoptosis programmed cell death, caspase apoptosis pathway"
- "What are different types of cells?" → "cell types eukaryotic prokaryotic classification, animal plant blood nerve cells biology"
- "List the types of bonds in chemistry" → "chemical bond types covalent ionic hydrogen, molecular bonding classification"

For "what are", "types of", "list", "name", "enumerate" questions:
  Search terms must target CLASSIFICATION and OVERVIEW papers, not narrow research papers.
  Include the subject name + "types classification" or "overview" or "biology textbook" style terms.

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
        base_topics = topic_map.get(q['number'], [q['question']])
        # Append level-specific suffix to first topic to bias search results
        if level and level.get('search_suffix'):
            base_topics = [base_topics[0] + ' ' + level['search_suffix']] + base_topics[1:]
        q['topics'] = base_topics

    return questions


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _score_paper_relevance(paper: dict, question: str, topics: list) -> float:
    """
    Score a paper against a question and its topics.

    Scores question tokens and each topic SEPARATELY, then takes the MAX.
    This stops unrelated topic tokens (e.g. "Singer Nicolson 1972") from
    inflating the denominator and hurting scores of genuinely relevant papers.

    Also applies a title-specificity gate: if a paper only matches very
    common words (cell, membrane, protein) but no specific term in its title,
    its score is halved — preventing tangential papers from passing.
    """
    title = paper.get("title", "").lower()
    summary = paper.get("summary", "").lower()
    combined = title + " " + summary

    STOPWORDS = {
        "a","an","the","of","in","on","at","to","for","and","or","is","it","its",
        "be","by","as","with","that","this","are","was","were","have","has","had",
        "not","but","from","into","what","how","why","does","when","where","which",
        "who","explain","discuss","describe","define","compare","list","role","impact",
        "effect","effects","process","between","used","using","based","given","also",
        "their","your","work","works","make","makes","give","gives","show",
    }
    # Words too generic to confirm title relevance on their own
    GENERIC = {
        "cell","cells","membrane","membranes","protein","proteins","model",
        "structure","function","analysis","study","role","effect","based",
        "human","tissue","biological","biology","method","methods",
    }

    def _tokenize(text: str) -> list:
        raw = re.split(r'[\s\-,]+', text.lower())
        return list(dict.fromkeys(
            t.strip(".,;:()") for t in raw
            if len(t.strip(".,;:()")) > 3 and t.strip(".,;:()") not in STOPWORDS
        ))

    def _match_ratio(tokens: list) -> float:
        if not tokens:
            return 0.0
        matches = sum(
            1 for t in tokens
            if re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', combined)
        )
        return matches / len(tokens)

    # Score against question alone and each topic independently
    segments = [question] + list(topics)
    seg_scores = [_match_ratio(_tokenize(s)) for s in segments if s]

    if not seg_scores:
        return 0.5

    best = max(seg_scores)

    # Title-specificity gate: require at least ONE non-generic token to match the title.
    # Prevents papers that only share "membrane" + "proteins" from passing.
    if best >= 0.25:
        all_query_tokens = _tokenize(question + " " + " ".join(topics))
        specific_tokens = [t for t in all_query_tokens if t not in GENERIC]
        has_specific_title_match = any(
            re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', title)
            for t in specific_tokens
        )
        if not has_specific_title_match:
            best = best * 0.5  # penalise: only generic words matched

    return best


def _filter_relevant_papers(papers: list, question: str, topics: list, min_score: float = 0.25):
    """
    Returns only papers that genuinely match the question.
    Does NOT fall back to low-scoring papers — returns empty if nothing passes.
    Caller is responsible for handling empty results.
    """
    scored = sorted(
        [(_score_paper_relevance(p, question, topics), p) for p in papers],
        key=lambda x: x[0], reverse=True
    )
    for score, p in scored:
        print(f"[assignment] relevance={score:.2f} | {p.get('title', '')[:60]}")

    relevant = [(s, p) for s, p in scored if s >= min_score]
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

    good = [(s, p) for s, p in scored if s >= 0.25]

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
        good = [(s, p) for s, p in scored if s >= 0.25]

        if len(good) >= min_relevant:
            print(f"[assignment] Gap filled — {len(good)} relevant papers")
            return [p for _, p in good[:6]]

        time.sleep(CRAWL_POLL_INTERVAL)

    # Timeout — return whatever passed relevance threshold, even if only 1.
    # If nothing passed, return empty — generate_answer will handle it cleanly
    # rather than hallucinating from irrelevant papers.
    print(f"[assignment] Timeout — {len(good)} relevant papers after crawl")
    return [p for _, p in good[:6]]


# ── Answer generation ─────────────────────────────────────────────────────────

def generate_answer(question: dict, papers: list, force_regenerate: bool = False, level: dict | None = None) -> dict:
    """
    Generate answer. Checks knowledge base first for similar questions.
    Set force_regenerate=True to skip KB and always call LLM
    (used when user presses the Regenerate button).
    """
    q_type = question.get('type', 'factual')
    topics = question.get('topics', [])

    # ── KB lookup (skip for numerical — no LLM involved anyway) ──
    if not force_regenerate and q_type != 'numerical':
        stored = find_similar_answer(question['question'])
        if stored:
            result = format_kb_result(stored, question['number'])
            result['type'] = q_type  # preserve classified type
            return result

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
            "answer": "⚠️ No research papers found for this topic in academic databases.",
            "sources": [],
            "confidence_label": "⚪ No papers",
            "papers_found": 0
        }

    relevant_papers, scores = _filter_relevant_papers(papers, question['question'], topics)

    # Hard gate — if nothing passes relevance filter, do NOT call LLM.
    # Small models hallucinate answers from general knowledge when given
    # irrelevant context. Better to return no-papers than a confident wrong answer.
    if not relevant_papers:
        return {
            "number": question['number'],
            "question": question['question'],
            "type": q_type,
            "answer": "⚠️ No research papers found for this topic in academic databases.",
            "sources": [],
            "confidence_label": "⚪ No papers",
            "papers_found": 0
        }

    # Confidence based on papers actually cited (max 4), not full retrieved count
    cited_papers = relevant_papers[:4]
    cited_scores = scores[:4]
    confidence_label = _compute_confidence(cited_papers, cited_scores)

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
        'CITATION RULES:\n'
        '- Cite papers by their exact title in quotes: According to \\"Title of Paper\\"...\n'
        '- NEVER use numbered references like (1), (2), [1], [2] — these are forbidden.\n'
        '- NEVER say "Paper 1", "Paper 2", "the first paper", or any number-based reference.\n'
        '- NEVER invent facts not found in the provided papers.\n'
        '- If multiple papers support a point, cite each by title, not by number.\n'
    )

    # Level-aware writing instruction — injected into every prompt
    level_instruction = level['answer_style'] if level else (
        "Write at undergraduate level. Use clear academic language."
    )

    # Concept-gap detection: check if papers cover the core terms from the question.
    # If coverage < 40%, the bot found tangentially related papers, not the specific
    # concept asked about. We still answer but tell the LLM to acknowledge the gap.
    q_core_tokens = set(re.split(r'[\s\-,]+', question['question'].lower()))
    q_core_tokens -= {
        "a","an","the","of","in","on","at","to","for","and","or","is","it",
        "what","how","why","explain","define","describe","discuss","evaluate",
        "list","name","state","give","?","."
    }
    q_core_tokens = {t.strip(".,?!") for t in q_core_tokens if len(t.strip(".,?!")) > 3}

    papers_text = " ".join(
        (p.get("title","") + " " + p.get("summary","")).lower()
        for p in cited_papers
    )
    concept_match_count = sum(
        1 for t in q_core_tokens
        if re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', papers_text)
    )
    concept_coverage = concept_match_count / len(q_core_tokens) if q_core_tokens else 1.0

    # If papers cover less than 40% of the core question terms, add a note
    gap_warning = (
        "⚠️ IMPORTANT: No paper directly covering this concept was found in the database.\n"
        "You MUST:\n"
        "1. State at the start that a direct source was not found.\n"
        "2. Describe ONLY what the provided papers actually say — nothing else.\n"
        "3. Do NOT invent citations, author names, journal names, or years.\n"
        "4. Do NOT use your training knowledge to fill gaps — this causes hallucination.\n"
        "5. If the papers truly cannot answer this question, say so and stop.\n\n"
        if concept_coverage < 0.4 else ""
    )

    if q_type == 'essay':
        prompt = f"""Write an essay answer using ONLY the research papers provided.

{gap_warning}{level_instruction}
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
Keep under 150 words.

{gap_warning}{level_instruction}
{cite_rule}

IMPORTANT formatting rules:
- If the question is about a MODEL or THEORY (e.g. Fluid Mosaic Model, Lock and Key):
  Use this structure: Definition → Key components → How it works → Significance
  Do NOT say "step by step" — models describe structure, not processes.
- If the question is about a PROCESS or MECHANISM (e.g. DNA replication, photosynthesis):
  Use this structure: Overview → Stages → Outcome
- If the question is about a CONCEPT (e.g. how immune system works):
  Use this structure: What it is → How it works → Why it matters

Question: {question['question']}

Research papers:
{context}

Explanation:"""

    elif q_type == 'definition':
        # "What is X? Describe" → wants more depth than a bare definition
        wants_description = re.search(
            r'\b(describe|elaborate|explain|detail|illustrate|discuss)\b',
            question['question'], re.IGNORECASE
        )
        def_word_limit = 180 if wants_description else 120
        def_extra = (
            "Since the question also asks to describe, add a 4th section:\n"
            "4. Structure/Function: Key structural or functional details (2-3 sentences)\n"
            if wants_description else ""
        )

        prompt = f"""Write a clear, precise definition using ONLY the research papers provided.

{gap_warning}{level_instruction}
{cite_rule}

Structure your answer as:
1. Definition: What is it? (1-2 sentences, cite the paper that defines it)
2. Key features: 2-3 bullet points of essential characteristics
3. Significance: Why does it matter? (1 sentence)
{def_extra}
Keep the entire answer under {def_word_limit} words. Do NOT use numbered citation markers.

Question: {question['question']}

Research papers:
{context}

Definition:"""

    else:  # factual
        # Detect if this is a "list" or "types of" question — needs more space
        q_lower = question['question'].lower()
        is_list_question = any(kw in q_lower for kw in (
            "types of", "different types", "kinds of", "examples of",
            "list", "name the", "what are", "enumerate", "classify"
        ))
        word_limit = 200 if is_list_question else 100
        list_instruction = (
            "List and briefly describe each type. Use this structure:\n"
            "- Type name: brief description (cite paper if relevant)\n"
            "Cover all major types mentioned in the papers."
            if is_list_question else
            "Answer directly. Cite the paper that supports each point."
        )

        prompt = f"""Answer the question using ONLY the research papers provided.
{gap_warning}{level_instruction}
{list_instruction}
Keep under {word_limit} words.

{cite_rule}

Question: {question['question']}

Research papers:
{context}

Answer:"""

    answer_text = _call_llm(prompt, max_tokens=600, temperature=0.2)

    result = {
        "number": question['number'],
        "question": question['question'],
        "type": q_type,
        "answer": answer_text,
        "sources": sources_used,
        "confidence_label": confidence_label,
        "papers_found": len(sources_used)   # cited count not retrieved
    }

    # Store in knowledge base for future users with similar questions
    store_answer(question['question'], topics, result)

    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def analyze_assignment(text: str, mode: str = "topics", level: dict | None = None) -> dict:
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

    questions = get_search_topics(questions, level=level)

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
        result = generate_answer(q, q.get('papers', []), level=level)
        q.update(result)

    return {"questions": questions, "mode": "answers", "total": len(questions)}