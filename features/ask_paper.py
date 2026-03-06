"""Ask a paper feature (premium only). Q&A over paper abstract using local LLM."""
import ollama

MODEL = "qwen2.5:3b"


def ask_paper(abstract: str, question: str, title: str = "") -> str:
    if not abstract:
        return "No abstract available for this paper."

    prompt = f"""You are a research assistant. A user is asking a question about a specific paper.

Paper title: {title}

Abstract:
{abstract[:2000]}

User question: {question}

Answer clearly and concisely based only on what the abstract tells you.
If the abstract doesn't contain enough information to answer, say so.
Keep your answer under 150 words."""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 200, "temperature": 0.3}
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error generating answer: {e}"
