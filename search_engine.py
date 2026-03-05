import numpy as np
from db import resources
from embeddings import embed


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def search(query, limit=40, threshold=0.35):   # lowered threshold

    query_vector = np.array(embed(query))

    results = []

    for r in resources.find():

        vec = np.array(r["embedding"])

        score = cosine_similarity(query_vector, vec)

        if score < threshold:
            continue

        results.append((score, r))

    results.sort(reverse=True, key=lambda x: x[0])

    return [r[1] for r in results[:limit]]