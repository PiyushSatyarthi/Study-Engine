import os
import requests

# Same env variable — both embeddings and summaries go to the same Ollama server
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
CHAT_URL = f"{OLLAMA_HOST}/api/chat"

MODEL = "qwen2.5:3b"


def summarize_text(text: str) -> str:
    if not text:
        return "No summary available."

    prompt = f"""Explain this research abstract simply.

Give a concise explanation in under 80 words.

Abstract:
{text}
"""

    try:
        r = requests.post(
            CHAT_URL,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "options": {
                    "num_predict": 120,
                    "temperature": 0.3
                },
                "stream": False   # get full response at once
            },
            timeout=120   # summaries can take up to 2 min on slow hardware
        )

        data = r.json()
        return data["message"]["content"]

    except Exception as e:
        print(f"Summary generation error: {e}")
        return "Could not generate summary. Please try again."