from app.chroma_store import documents_collection
from app.embeddings import embed_query
from app.search_utils import bm25_rank


def search_documents(
    query: str,
    owner_id: str,
    is_admin: bool = False,
    n_results: int = 5,
    document_id: str | None = None,
) -> dict:
    total = documents_collection.count()
    if total == 0:
        return {"results": [], "message": "No documents have been uploaded yet."}

    filters = []
    if not is_admin:
        filters.append({"owner_id": owner_id})
    if document_id:
        filters.append({"document_id": document_id})
    where = filters[0] if len(filters) == 1 else ({"$and": filters} if filters else None)
    options = {"where": where} if where else {}

    # Dense vector retrieval provides semantic matches.
    dense = documents_collection.query(
        query_embeddings=[embed_query(query)],
        n_results=min(20, total),
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
        }

    # BM25 lexical retrieval adds exact-name, acronym, and keyword matches.
    lexical_data = documents_collection.get(
        include=["documents", "metadatas"],
        limit=10000,
        **options,
    )
    lexical_ids = lexical_data.get("ids", [])
    lexical_docs = lexical_data.get("documents", [])
    lexical_metas = lexical_data.get("metadatas", [])
    for rank, (index, _score) in enumerate(bm25_rank(query, lexical_docs), start=1):
        item_id = lexical_ids[index]
        if item_id not in candidates:
            candidates[item_id] = {
                "text": lexical_docs[index],
                "metadata": lexical_metas[index] or {},
                "distance": None,
                "dense_rank": None,
                "lexical_rank": rank,
            }
        else:
            candidates[item_id]["lexical_rank"] = rank

    # Reciprocal rank fusion reranks the union of semantic and lexical results.
    def fused_score(item: dict) -> float:
        score = 0.0
        if item["dense_rank"] is not None:
            score += 0.55 / (60 + item["dense_rank"])
        if item["lexical_rank"] is not None:
            score += 0.45 / (60 + item["lexical_rank"])
        return score

    ranked = sorted(candidates.values(), key=fused_score, reverse=True)[:n_results]
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
