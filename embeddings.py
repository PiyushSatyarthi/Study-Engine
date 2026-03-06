import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"

def embed(text: str):
    r = requests.post(
        OLLAMA_URL,
        json={
            "model": "nomic-embed-text",
            "prompt": text
        }
    )
    return r.json()["embedding"]