import os
import requests

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def _call_llm(prompt: str, max_tokens: int = 200) -> str:
    if LLM_PROVIDER == "groq":
        return _call_groq(prompt, max_tokens)
    return _call_ollama(prompt, max_tokens)


def _call_ollama(prompt: str, max_tokens: int) -> str:
    try:
        r = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": max_tokens, "temperature": 0.3},
                "stream": False
            },
            timeout=120
        )
        return r.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[summarizer] Ollama call failed: {e}")
        return ""


def _call_groq(prompt: str, max_tokens: int) -> str:
    if not GROQ_API_KEY:
        print("[summarizer] GROQ_API_KEY not set — falling back to Ollama")
        return _call_ollama(prompt, max_tokens)
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
                "temperature": 0.3
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[summarizer] Groq call failed: {e} — falling back to Ollama")
        return _call_ollama(prompt, max_tokens)


def summarize_text(text: str, level: dict | None = None) -> str:
    """
    Summarize a paper abstract.
    level: education level dict from users.get_education_level().
    If None, uses default undergraduate style.
    """
    if not text:
        return "No summary available."

    if level is None:
        style = "Explain clearly for an undergraduate student familiar with the basics of the field."
    else:
        style = level["summary_style"]

    prompt = f"""{style}

Summarize this research paper abstract in under 100 words.
Focus on: what the paper studies, what they found, and why it matters.

Abstract:
{text}
"""
    result = _call_llm(prompt, max_tokens=150)
    return result if result else "Could not generate summary. Please try again."


def ask_paper(abstract: str, question: str, title: str = "", level: dict | None = None) -> str:
    """Answer a question about a paper. Adjusts depth and language for education level."""
    if not abstract:
        return "No abstract available for this paper."

    if level is None:
        style = "Answer clearly for an undergraduate student."
    else:
        style = level["answer_style"]

    word_limit = {
        "highschool": 100,
        "undergraduate": 150,
        "postgraduate": 200,
        "phd": 250
    }.get(level["short"].lower().split("/")[0].strip() if level else "undergraduate", 150)

    prompt = f"""You are a research assistant. A user is asking a question about a specific paper.

{style}

Paper title: {title}

Abstract:
{abstract[:2000]}

User question: {question}

Answer based only on what the abstract tells you.
If the abstract doesn't contain enough to answer, say so clearly.
Keep under {word_limit} words."""

    result = _call_llm(prompt, max_tokens=word_limit * 2)
    return result if result else "Could not generate answer. Please try again."


def compare_papers(papers: list, level: dict | None = None) -> str:
    """Compare 2-3 papers. Adjusts depth and terminology for education level."""
    if len(papers) < 2:
        return "Need at least 2 papers to compare."

    papers = papers[:3]

    if level is None:
        style = "Write for an undergraduate student. Use clear academic language."
        word_limit = 200
    else:
        style = level["answer_style"]
        word_limit = {"highschool": 150, "undergraduate": 200,
                      "postgraduate": 280, "phd": 350}.get(
            level["short"].lower().split("/")[0].strip(), 200
        )

    papers_text = ""
    for i, p in enumerate(papers, 1):
        papers_text += f"Paper {i}: {p.get('title', 'Untitled')}\n"
        papers_text += f"Abstract: {p.get('summary', '')[:600]}\n\n"

    prompt = f"""Compare these {len(papers)} research papers.

{style}

{papers_text}
Cover in under {word_limit} words:
1. What each paper studies and its main finding
2. Key differences in approach, method, or conclusions
3. Which paper suits which use case or reader

Be direct and useful."""

    result = _call_llm(prompt, max_tokens=word_limit * 2)
    return result if result else "Could not generate comparison. Please try again."


MAX_PAPERS = 3