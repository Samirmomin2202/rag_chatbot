from datetime import datetime, timezone
from pymongo import MongoClient
from bson import ObjectId
from pymongo.server_api import ServerApi
from app.config import settings
from app.search_utils import bm25_rank

mongo_client = None
database = None
messages_collection = None
documents_collection = None
users_collection = None

def get_database():
    global mongo_client, database, messages_collection, documents_collection, users_collection
    if not settings.MONGODB_URI:
        raise RuntimeError("MONGODB_URI is missing. Configure backend/.env")
    if database is None:
        mongo_client = MongoClient(
            settings.MONGODB_URI,
            server_api=ServerApi("1"),
            serverSelectionTimeoutMS=10000,
        )
        database = mongo_client[settings.MONGODB_DATABASE]
        messages_collection = database["messages"]
        documents_collection = database["documents"]
        users_collection = database["users"]
        messages_collection.create_index([("conversation_id", 1), ("created_at", 1)])
        messages_collection.create_index([("owner_id", 1), ("role", 1), ("created_at", -1)])
        documents_collection.create_index([("document_id", 1)], unique=True)
        users_collection.create_index([("email", 1)], unique=True)
        users_collection.create_index([("user_id", 1)], unique=True)
    return database

def check_mongodb():
    get_database()
    mongo_client.admin.command("ping")
    return True

def save_message(conversation_id: str, owner_id: str, role: str, content: str, image: str | None = None):
    get_database()
    message = {
        "conversation_id": conversation_id,
        "owner_id": owner_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc),
    }
    if image:
        message["image"] = image
    messages_collection.insert_one(message)

def get_history(conversation_id: str, owner_id: str, limit: int = 12, include_images: bool = False):
    get_database()
    projection = {"_id": 0, "role": 1, "content": 1}
    if include_images:
        projection["_id"] = 1
        projection["image"] = 1
    docs = list(
        messages_collection.find(
            {"conversation_id": conversation_id, "owner_id": owner_id},
            projection,
        ).sort("created_at", -1).limit(limit)
    )
    docs.reverse()
    if include_images:
        return [
            {"role": d["role"], "content": d["content"], "message_id": str(d["_id"]), "has_image": bool(d.get("image"))}
            for d in docs
        ]
    return [{"role": d["role"], "content": d["content"]} for d in docs]

def get_conversation_image(conversation_id: str, owner_id: str, message_id: str):
    get_database()
    try:
        object_id = ObjectId(message_id)
    except Exception:
        return None
    message = messages_collection.find_one(
        {"_id": object_id, "conversation_id": conversation_id, "owner_id": owner_id},
        {"_id": 0, "image": 1},
    )
    return message.get("image") if message else None

def list_conversations(owner_id: str, limit: int = 50):
    get_database()
    return list(messages_collection.aggregate([
        {"$match": {"owner_id": owner_id}},
        {"$sort": {"created_at": 1}},
        {"$group": {
            "_id": "$conversation_id",
            "title": {"$first": {
                "$cond": [{"$eq": ["$role", "user"]}, "$content", ""]
            }},
            "updated_at": {"$max": "$created_at"},
            "message_count": {"$sum": 1},
        }},
        {"$sort": {"updated_at": -1}},
        {"$limit": limit},
        {"$project": {
            "_id": 0,
            "conversation_id": "$_id",
            "title": 1,
            "updated_at": 1,
            "message_count": 1,
        }},
    ]))

def retrieve_related_memories(query: str, owner_id: str, exclude_conversation_id: str, limit: int = 3):
    get_database()
    candidates = list(messages_collection.find(
        {
            "owner_id": owner_id,
            "role": "user",
            "conversation_id": {"$ne": exclude_conversation_id},
        },
        {"_id": 0, "conversation_id": 1, "content": 1},
    ).sort("created_at", -1).limit(300))
    ranked = bm25_rank(query, [item.get("content", "") for item in candidates])
    memories = []
    seen_conversations = set()
    for index, _score in ranked:
        candidate = candidates[index]
        conversation_id = candidate["conversation_id"]
        if conversation_id in seen_conversations:
            continue
        seen_conversations.add(conversation_id)
        messages = get_history(conversation_id, owner_id, limit=100)
        question_index = next(
            (i for i, message in enumerate(messages) if message["role"] == "user" and message["content"] == candidate["content"]),
            None,
        )
        if question_index is None:
            continue
        answer = ""
        if question_index + 1 < len(messages) and messages[question_index + 1]["role"] == "assistant":
            answer = messages[question_index + 1]["content"][:1200]
        memories.append({"question": candidate["content"][:500], "answer": answer})
        if len(memories) >= limit:
            break
    return memories

def find_user_by_email(email: str):
    get_database()
    return users_collection.find_one({"email": email})

def find_user_by_id(user_id: str):
    get_database()
    return users_collection.find_one({"user_id": user_id})

def create_user(user: dict):
    get_database()
    users_collection.insert_one(user)

def list_users():
    get_database()
    return list(users_collection.find(
        {}, {"_id": 0, "user_id": 1, "email": 1, "display_name": 1, "role": 1, "created_at": 1, "usage": 1}
    ).sort("created_at", 1).limit(500))

def get_user_usage(user_id: str):
    get_database()
    user = users_collection.find_one({"user_id": user_id}, {"_id": 0, "usage": 1}) or {}
    usage = user.get("usage", {})
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "total_tokens": int(usage.get("total_tokens", 0)),
        "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
        "requests": int(usage.get("requests", 0)),
    }

def record_user_usage(user_id: str, usage: dict):
    get_database()
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {
            "usage.input_tokens": int(usage.get("input_tokens", 0)),
            "usage.output_tokens": int(usage.get("output_tokens", 0)),
            "usage.total_tokens": int(usage.get("total_tokens", 0)),
            "usage.estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
            "usage.requests": 1,
        }},
    )
    return get_user_usage(user_id)

def set_user_role(user_id: str, role: str):
    get_database()
    return users_collection.update_one({"user_id": user_id}, {"$set": {"role": role}})

def assign_legacy_conversations(owner_id: str):
    """Keep pre-login local conversations available to the initial admin."""
    get_database()
    messages_collection.update_many(
        {"owner_id": {"$exists": False}},
        {"$set": {"owner_id": owner_id}},
    )

def save_document_metadata(document_id: str, filename: str, chunks: int, owner_id: str, owner_name: str):
    get_database()
    documents_collection.update_one(
        {"document_id": document_id},
        {"$set": {
            "document_id": document_id,
            "filename": filename,
            "chunks": chunks,
            "owner_id": owner_id,
            "uploaded_by": owner_name,
            "uploaded_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

def list_documents(owner_id: str, is_admin: bool = False):
    get_database()
    query = {} if is_admin else {"owner_id": owner_id}
    return list(documents_collection.find(
        query, {"_id": 0, "document_id": 1, "filename": 1, "chunks": 1, "uploaded_at": 1, "uploaded_by": 1}
    ).sort("uploaded_at", -1).limit(100))
