from app.database import list_documents


def list_uploaded_documents(owner_id: str, is_admin: bool = False) -> dict:
    documents = list_documents(owner_id, is_admin=is_admin)
    return {
        "documents": [
            {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "chunks": document.get("chunks", 0),
                "uploaded_by": document.get("uploaded_by"),
            }
            for document in documents
        ]
    }
