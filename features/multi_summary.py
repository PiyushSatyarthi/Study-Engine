"""Multi-paper comparison (premium only). Compare up to 3 papers."""
import ollama

MODEL = "qwen2.5:3b"
MAX_PAPERS = 3


def compare_papers(papers: list[dict]) -> str:
    """
    papers: list of dicts with keys: title, summary
    Returns a comparison paragraph.
    """
    if len(papers) < 2:
        return "Need at least 2 papers to compare."
    if len(papers) > MAX_PAPERS:
        papers = papers[:MAX_PAPERS]

    papers_text = ""
    for i, p in enumerate(papers, 1):
        papers_text += f"Paper {i}: {p.get('title', 'Untitled')}\n"
        papers_text += f"Abstract: {p.get('summary', '')[:600]}\n\n"

    prompt = f"""Compare these {len(papers)} research papers briefly.

{papers_text}

In under 200 words cover:
1. What each paper studies
2. Key differences in approach or findings
3. Which would suit different use cases

Be direct and useful."""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": 300, "temperature": 0.3}
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error generating comparison: {e}"
