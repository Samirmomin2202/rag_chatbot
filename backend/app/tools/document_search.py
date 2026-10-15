from difflib import SequenceMatcher

from app.chroma_store import documents_collection
from app.database import list_documents
from app.rag.retriever import search_documents

def run_document_search(
    query: str,
    owner_id: str,
    is_admin: bool = False,
    document_id: str | None = None,
    filename: str | None = None,
    page: int | None = None,
) -> dict:
    return search_documents(
        query, owner_id=owner_id, is_admin=is_admin,
        document_id=document_id, filename=filename, page=page,
    )


def get_document_summary_context(
    filename: str, owner_id: str, is_admin: bool = False, max_chars: int = 18000,
) -> dict:
    """Return an uploaded PDF's chunks in document order for whole-file summaries."""
    accessible = list_documents(owner_id, is_admin=is_admin)
    if not accessible:
        return {"error": "No uploaded PDF documents are available to this account."}

    requested = filename.strip().casefold()
    exact = [doc for doc in accessible if doc.get("filename", "").casefold() == requested]
    if exact:
        document = exact[0]
    else:
        ranked = sorted(
            ((SequenceMatcher(None, requested, doc.get("filename", "").casefold()).ratio(), doc) for doc in accessible),
            key=lambda item: item[0], reverse=True,
        )
        if not ranked or ranked[0][0] < 0.72:
            return {"error": f"I couldn't find an accessible PDF named '{filename}'. Use the filename shown in Knowledge Files."}
        document = ranked[0][1]

    document_id = document["document_id"]
    chunks = documents_collection.get(
        where={"document_id": document_id},
        include=["documents", "metadatas"],
    )
    ordered = sorted(
        zip(chunks.get("ids", []), chunks.get("documents", []), chunks.get("metadatas", [])),
        key=lambda row: int(row[0].rsplit("-", 1)[-1]),
    )
    pages = []
    text_parts = []
    remaining = max_chars
    for _, text, metadata in ordered:
        page = (metadata or {}).get("page")
        if page is not None and page not in pages:
            pages.append(page)
        if remaining <= 0:
            break
        page_marker = f"\n[Page {page}]\n" if page is not None and (not text_parts or pages[-1] == page) else "\n"
        content = (page_marker + text)[:remaining]
        text_parts.append(content)
        remaining -= len(content)

    if not text_parts:
        return {"error": f"No extracted text is available for '{document['filename']}'."}
    return {
        "filename": document["filename"],
        "pages": pages,
        "text": "".join(text_parts),
        "truncated": remaining <= 0 and len(ordered) > len(text_parts),
    }
