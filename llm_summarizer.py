import os
import requests

# ── LLM config ────────────────────────────────────────────────────────────────
# Mirrors assignment_analyzer.py — same env vars, same routing logic
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()  # "ollama" | "groq"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def _call_ollama(prompt: str) -> str:
    try:
        r = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": 120, "temperature": 0.3},
                "stream": False
            },
            timeout=120
        )
        return r.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[summarizer] Ollama call failed: {e}")
        return ""


def _call_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        print("[summarizer] GROQ_API_KEY not set — falling back to Ollama")
        return _call_ollama(prompt)
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
                "max_tokens": 120,
                "temperature": 0.3
            },
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[summarizer] Groq call failed: {e} — falling back to Ollama")
        return _call_ollama(prompt)


def summarize_text(text: str) -> str:
    if not text:
        return "No summary available."

    prompt = f"""Explain this research abstract simply.

Give a concise explanation in under 80 words.

Abstract:
{text}
"""

    if LLM_PROVIDER == "groq":
        result = _call_groq(prompt)
    else:
        result = _call_ollama(prompt)

    return result if result else "Could not generate summary. Please try again."