# embeddings.py

import requests
import time

OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
MODEL = "nomic-embed-text"

# nomic-embed-text supports up to 8192 tokens
MAX_CHARS = 2000


def embed(text: str, retries: int = 3) -> list[float]:
    """
    Generate embedding with retry logic.
    Prefixes text with 'search_document:' as nomic-embed-text
    is trained with this prefix for better retrieval accuracy.
    """
    text = "search_document: " + text[:MAX_CHARS]

    for attempt in range(retries):
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": MODEL, "prompt": text},
                timeout=30
            )
            data = r.json()

            if "embedding" in data:
                return data["embedding"]

            print(f"Embedding error (attempt {attempt+1}):", data)

        except Exception as e:
            print(f"Embedding request failed (attempt {attempt+1}):", e)
            time.sleep(1)

    return [0.0] * 768


def embed_query(query: str) -> list[float]:
    """
    Queries should use a different prefix from documents.
    This is how nomic-embed-text was trained.
    """
    text = "search_query: " + query[:500]

    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": text},
            timeout=30
        )
        data = r.json()
        return data.get("embedding", [0.0] * 768)
    except Exception as e:
        print("Query embedding error:", e)
        return [0.0] * 768