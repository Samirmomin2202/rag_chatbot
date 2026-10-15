import math
import re
from collections import Counter


def bm25_rank(query: str, texts: list[str]) -> list[tuple[int, float]]:
    """Return document indexes ordered by BM25 relevance."""
    query_terms = re.findall(r"[\w]+", query.lower())
    if not query_terms or not texts:
        return []
    tokenized = [re.findall(r"[\w]+", text.lower()) for text in texts]
    lengths = [len(tokens) for tokens in tokenized]
    average_length = sum(lengths) / max(len(lengths), 1)
    frequencies = [Counter(tokens) for tokens in tokenized]
    document_frequency = Counter(term for counts in frequencies for term in counts)
    scores = []
    for index, counts in enumerate(frequencies):
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            idf = math.log(1 + (len(texts) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * lengths[index] / max(average_length, 1))
            score += idf * frequency * 2.5 / denominator
        if score > 0:
            scores.append((index, score))
    return sorted(scores, key=lambda item: item[1], reverse=True)
