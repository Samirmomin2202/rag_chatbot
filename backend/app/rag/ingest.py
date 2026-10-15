import re
from io import BytesIO
from uuid import uuid4
from pypdf import PdfReader

from app.chroma_store import documents_collection
from app.embeddings import embed_texts
from app.database import save_document_metadata

def split_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks

def ingest_pdf(filename: str, file_bytes: bytes, owner_id: str, owner_name: str) -> dict:
    reader = PdfReader(BytesIO(file_bytes))
    page_texts = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append((page_number, text))
    all_chunks = []
    for page_number, text in page_texts:
        for chunk in split_text(text):
            all_chunks.append((page_number, chunk))
    if not all_chunks:
        raise ValueError("No extractable text found. The PDF may be scanned; OCR is not included.")
    document_id = str(uuid4())
    texts = [item[1] for item in all_chunks]
    vectors = embed_texts(texts)
    ids = [f"{document_id}-{i}" for i in range(len(texts))]
    metadatas = [
        {
            "document_id": document_id,
            "filename": filename,
            "page": page,
            "owner_id": owner_id,
            "uploaded_by": owner_name,
        }
        for page, _ in all_chunks
    ]
    documents_collection.add(
        ids=ids,
        documents=texts,
        embeddings=vectors,
        metadatas=metadatas,
    )
    save_document_metadata(document_id, filename, len(texts), owner_id, owner_name)
    return {
        "document_id": document_id,
        "filename": filename,
        "chunks": len(texts),
        "pages_with_text": len(page_texts),
    }
