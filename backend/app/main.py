from uuid import uuid4
import base64
import binascii
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.database import check_mongodb, get_history, get_conversation_image, get_latest_conversation_image, save_message, list_documents, list_conversations, delete_conversation, retrieve_related_memories, record_user_usage
from app.auth import router as auth_router, admin_router, current_user, admin_user
from app.chroma_store import get_chroma_status
from app.services.agent import generate_answer
from app.rag.ingest import ingest_pdf

app = FastAPI(title="Advanced RAG Chatbot API", version="1.0.0")
app.include_router(auth_router)
app.include_router(admin_router)

@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logging.exception("Unhandled API error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error. Check the backend terminal for the cause."})

class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    image: str | None = Field(default=None, max_length=6_000_000)
    conversation_id: str | None = None

@app.get("/")
def root():
    return {"message": "Advanced RAG Chatbot API is running"}

@app.get("/api/health")
def health():
    try:
        check_mongodb()
        mongodb = "connected"
    except Exception as exc:
        mongodb = f"disconnected ({type(exc).__name__})"
    try:
        chroma = get_chroma_status()
    except Exception as exc:
        chroma = {"status": f"unavailable ({type(exc).__name__})"}
    return {
        "status": "ok",
        "mongodb": mongodb,
        "chroma": chroma,
        "groq_configured": bool(settings.GROQ_API_KEY),
    }

@app.post("/api/chat")
def chat(request: ChatRequest, user: dict = Depends(current_user)):
    message = request.message.strip()
    if not message and not request.image:
        raise HTTPException(status_code=400, detail="Add a message or an image.")
    if request.image and not message:
        message = "Please describe this image."
    if request.image and not request.image.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")):
        raise HTTPException(status_code=400, detail="Use a PNG, JPEG, or WEBP image.")
    conversation_id = request.conversation_id or str(uuid4())
    try:
        history = get_history(conversation_id, user["user_id"], limit=12)
        save_message(conversation_id, user["user_id"], "user", message, image=request.image)
        history.append({"role": "user", "content": message, "image": request.image} if request.image else {"role": "user", "content": message})
        image_context = (
            {"content": message, "image": request.image}
            if request.image
            else get_latest_conversation_image(conversation_id, user["user_id"])
        )
        memories = retrieve_related_memories(message, user["user_id"], conversation_id)
        result = generate_answer(
            history,
            owner_id=user["user_id"],
            is_admin=user["role"] == "admin",
            memories=memories,
            reference_image=image_context,
        )
        answer = result["answer"]
        usage = result.get("usage", {})
        usage_total = record_user_usage(user["user_id"], usage) if usage else None
        save_message(conversation_id, user["user_id"], "assistant", answer)
        return {
            "conversation_id": conversation_id,
            "answer": answer,
            "tools_used": result["tools_used"],
            "usage": usage,
            "usage_total": usage_total,
        }
    except Exception as exc:
        print(f"Chat request failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Chat failed. Check backend terminal and environment settings.",
        ) from exc

@app.get("/api/conversations/{conversation_id}")
def conversation_history(conversation_id: str, user: dict = Depends(current_user)):
    try:
        return {
            "conversation_id": conversation_id,
            "messages": get_history(conversation_id, user["user_id"], limit=100, include_images=True),
        }
    except Exception as exc:
        print(f"History request failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Could not retrieve conversation history.") from exc

@app.get("/api/conversations/{conversation_id}/images/{message_id}")
def conversation_image(conversation_id: str, message_id: str, user: dict = Depends(current_user)):
    image = get_conversation_image(conversation_id, user["user_id"], message_id)
    if not image or "," not in image:
        raise HTTPException(status_code=404, detail="Image not found.")
    header, encoded = image.split(",", 1)
    media_type = header.removeprefix("data:").removesuffix(";base64")
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=404, detail="Image not found.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=404, detail="Image not found.")
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

@app.get("/api/conversations")
def conversations(user: dict = Depends(current_user)):
    try:
        return {"conversations": list_conversations(user["user_id"])}
    except Exception as exc:
        print(f"Conversation listing failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Could not list conversations.") from exc

@app.delete("/api/conversations/{conversation_id}")
def remove_conversation(conversation_id: str, user: dict = Depends(current_user)):
    try:
        deleted_count = delete_conversation(conversation_id, user["user_id"])
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return {"message": "Conversation deleted."}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Conversation deletion failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Could not delete conversation.") from exc

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...), user: dict = Depends(current_user)):
    filename = (file.filename or "upload.pdf").replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    content = await file.read()
    max_bytes = settings.MAX_PDF_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.MAX_PDF_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        result = ingest_pdf(
            filename,
            content,
            owner_id=user["user_id"],
            owner_name=user["display_name"],
        )
        return {"message": "PDF processed successfully.", **result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        print(f"PDF ingestion failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Could not process PDF. Check backend terminal.") from exc

@app.get("/api/documents")
def documents(user: dict = Depends(current_user)):
    try:
        return {"documents": list_documents(user["user_id"], is_admin=user["role"] == "admin")}
    except Exception as exc:
        print(f"Document listing failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="Could not list documents.") from exc

# Wrap the complete application so CORS headers are present on unexpected 500
# responses as well as successful responses and handled HTTP errors.
app = CORSMiddleware(
    app=app,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
