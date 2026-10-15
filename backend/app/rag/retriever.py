import re

from app.chroma_store import documents_collection
from app.embeddings import embed_query
from app.search_utils import bm25_rank
from app.config import settings


def search_documents(
    query: str,
    owner_id: str,
    is_admin: bool = False,
    n_results: int | None = None,
    document_id: str | None = None,
    filename: str | None = None,
    page: int | None = None,
) -> dict:
    n_results = max(1, min(20, n_results or settings.RAG_TOP_K))
    total = documents_collection.count()
    if total == 0:
        return {"results": [], "message": "No documents have been uploaded yet."}

    filters = []
    if not is_admin:
        filters.append({"owner_id": owner_id})
    if document_id:
        filters.append({"document_id": document_id})
    if filename:
        filters.append({"filename": filename})
    if page is not None:
        filters.append({"page": page})
    where = filters[0] if len(filters) == 1 else ({"$and": filters} if filters else None)
    options = {"where": where} if where else {}

    # Dense vector retrieval provides semantic matches.
    dense = documents_collection.query(
        query_embeddings=[embed_query(query)],
        n_results=min(settings.RAG_CANDIDATE_K, total),
        include=["documents", "metadatas", "distances"],
        **options,
    )
    dense_ids = dense.get("ids", [[]])[0]
    dense_docs = dense.get("documents", [[]])[0]
    dense_metas = dense.get("metadatas", [[]])[0]
    dense_distances = dense.get("distances", [[]])[0]
    candidates = {}
    for rank, (item_id, text, metadata, distance) in enumerate(
        zip(dense_ids, dense_docs, dense_metas, dense_distances), start=1
    ):
        candidates[item_id] = {
            "text": text,
            "metadata": metadata or {},
            "distance": distance,
            "dense_rank": rank,
            "lexical_rank": None,
            "bm25_score": 0.0,
        }

    # BM25 lexical retrieval adds exact-name, acronym, and keyword matches.
    lexical_data = documents_collection.get(
        include=["documents", "metadatas"],
        limit=settings.RAG_LEXICAL_MAX_DOCUMENTS,
        **options,
    )
    lexical_ids = lexical_data.get("ids", [])
    lexical_docs = lexical_data.get("documents", [])
    lexical_metas = lexical_data.get("metadatas", [])
    lexical_ranked = bm25_rank(query, lexical_docs)[:settings.RAG_CANDIDATE_K]
    for rank, (index, score) in enumerate(lexical_ranked, start=1):
        item_id = lexical_ids[index]
        if item_id not in candidates:
            candidates[item_id] = {
                "text": lexical_docs[index],
                "metadata": lexical_metas[index] or {},
                "distance": None,
                "dense_rank": None,
                "lexical_rank": rank,
                "bm25_score": score,
            }
        else:
            candidates[item_id]["lexical_rank"] = rank
            candidates[item_id]["bm25_score"] = score

    # Fuse independent search ranks, then rerank by lexical strength, vector
    # similarity and direct query-term coverage.
    def fused_score(item: dict) -> float:
        score = 0.0
        if item["dense_rank"] is not None:
            score += 0.55 / (60 + item["dense_rank"])
        if item["lexical_rank"] is not None:
            score += 0.45 / (60 + item["lexical_rank"])
        return score

    max_fusion = max((fused_score(item) for item in candidates.values()), default=1.0) or 1.0
    max_bm25 = max((item["bm25_score"] for item in candidates.values()), default=1.0) or 1.0
    query_terms = set(re.findall(r"[\w]+", query.lower()))
    fusion_weight = settings.RAG_RERANK_FUSION_WEIGHT
    bm25_weight = settings.RAG_RERANK_BM25_WEIGHT
    semantic_weight = settings.RAG_RERANK_SEMANTIC_WEIGHT
    term_weight = settings.RAG_RERANK_TERM_WEIGHT
    weight_total = max(fusion_weight + bm25_weight + semantic_weight + term_weight, 1e-9)

    def rerank_score(item: dict) -> float:
        dense_similarity = 0.0
        if item["distance"] is not None:
            # Chroma's default L2 distance on normalized embeddings ranges 0..2
            # for the useful similarity range.
            dense_similarity = max(0.0, min(1.0, 1.0 - float(item["distance"]) / 2.0))
        text_terms = set(re.findall(r"[\w]+", item["text"].lower()))
        term_coverage = len(query_terms & text_terms) / max(len(query_terms), 1)
        phrase_match = 1.0 if query.strip() and query.lower() in item["text"].lower() else 0.0
        term_relevance = min(1.0, term_coverage * 0.8 + phrase_match * 0.2)
        return (
            fusion_weight * fused_score(item) / max_fusion
            + bm25_weight * item["bm25_score"] / max_bm25
            + semantic_weight * dense_similarity
            + term_weight * term_relevance
        ) / weight_total

    ranked = sorted(candidates.values(), key=rerank_score, reverse=True)[:n_results]
    return {
        "results": [
            {
                "text": item["text"],
                "filename": item["metadata"].get("filename", "unknown"),
                "page": item["metadata"].get("page"),
                "distance": item["distance"],
            }
            for item in ranked
        ]
    }
