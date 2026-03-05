import ollama

def summarize_text(text):

    if not text:
        return "No summary available."

    prompt = f"""
Explain the following research abstract in 1–2 clear paragraphs.

Abstract:
{text}
"""

    response = ollama.chat(
        model="llama3:8b-instruct-q4_K_M",
        messages=[{"role": "user", "content": prompt}]
    )

    return response["message"]["content"]