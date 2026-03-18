import os
import time
import requests

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Reusable HTTP sessions — avoids TCP/TLS handshake per request
_ollama_session = requests.Session()
_groq_session = requests.Session()
_groq_session.headers.update({
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
})


def call_llm(prompt: str, max_tokens: int = 200, temperature: float = 0.3) -> str:
    if LLM_PROVIDER == "groq":
        return _call_groq(prompt, max_tokens, temperature)
    return _call_ollama(prompt, max_tokens, temperature)


def _call_ollama(prompt: str, max_tokens: int, temperature: float) -> str:
    try:
        r = _ollama_session.post(
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
        print(f"[llm] Ollama call failed: {e}")
        return ""


def _call_groq(prompt: str, max_tokens: int, temperature: float) -> str:
    if not GROQ_API_KEY:
        print("[llm] GROQ_API_KEY not set — falling back to Ollama")
        return _call_ollama(prompt, max_tokens, temperature)

    for attempt in range(3):
        try:
            r = _groq_session.post(
                GROQ_API_URL,
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature
                },
                timeout=30
            )
            if r.status_code == 429:
                retry_after = int(r.headers.get("retry-after", 5))
                print(f"[llm] Groq rate limited — waiting {retry_after}s (attempt {attempt + 1})")
                time.sleep(retry_after)
                continue
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[llm] Groq call failed: {e} — falling back to Ollama")
            return _call_ollama(prompt, max_tokens, temperature)

    print("[llm] Groq rate limit exhausted — falling back to Ollama")
    return _call_ollama(prompt, max_tokens, temperature)
