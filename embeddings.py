import os
import requests
import time

# Read from env — falls back to localhost for local dev
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
EMBED_URL = f"{OLLAMA_HOST}/api/embeddings"
GENERATE_URL = f"{OLLAMA_HOST}/api/generate"

EMBED_MODEL = "nomic-embed-text"
MAX_CHARS = 2000

# Reusable HTTP session — avoids TCP handshake per embedding call
_session = requests.Session()


def embed(text: str, retries: int = 3) -> list[float] | None:
    """
    Generate embedding with retry logic.
    Uses search_document: prefix as nomic-embed-text is trained asymmetrically.
    """
    text = "search_document: " + text[:MAX_CHARS]

    for attempt in range(retries):
        try:
            r = _session.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=30
            )
            data = r.json()

            if "embedding" in data:
                return data["embedding"]

            print(f"Embedding error (attempt {attempt + 1}):", data)

        except Exception as e:
            print(f"Embedding request failed (attempt {attempt + 1}): {e}")
            time.sleep(1)

    return None


def embed_query(query: str) -> list[float] | None:
    """
    Queries use a different prefix from documents.
    This matches how nomic-embed-text was trained.
    """
    text = "search_query: " + query[:500]

    for attempt in range(3):
        try:
            r = _session.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=30
            )
            data = r.json()
            if "embedding" in data:
                return data["embedding"]
        except Exception as e:
            print(f"Query embedding error (attempt {attempt + 1}): {e}")
            time.sleep(1)

    return None
