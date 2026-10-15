from app.rag.retriever import search_documents

def run_document_search(
    query: str,
    owner_id: str,
    is_admin: bool = False,
    document_id: str | None = None,
) -> dict:
    return search_documents(query, owner_id=owner_id, is_admin=is_admin, document_id=document_id)
