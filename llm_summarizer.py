import ollama

MODEL = "qwen2.5:3b"   # much faster than llama3 8b


def summarize_text(text):

    if not text:
        return "No summary available."

    prompt = f"""
Explain this research abstract simply.

Give a concise explanation in under 80 words.

Abstract:
{text}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        options={
            "num_predict": 120,
            "temperature": 0.3
        }
    )

    return response["message"]["content"]