import chromadb
from app.config import settings

chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIRECTORY)
documents_collection = chroma_client.get_or_create_collection(
    name="knowledge_documents",
    metadata={"description": "Chunks extracted from uploaded PDF documents"},
)

def get_chroma_status():
    return {
        "collection": "knowledge_documents",
        "document_chunks": documents_collection.count(),
    }
