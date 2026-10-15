import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    GROQ_INPUT_PRICE_PER_MILLION = float(os.getenv("GROQ_INPUT_PRICE_PER_MILLION", "0.15"))
    GROQ_OUTPUT_PRICE_PER_MILLION = float(os.getenv("GROQ_OUTPUT_PRICE_PER_MILLION", "0.60"))
    GROQ_VISION_INPUT_PRICE_PER_MILLION = float(os.getenv("GROQ_VISION_INPUT_PRICE_PER_MILLION", "0.80"))
    GROQ_VISION_OUTPUT_PRICE_PER_MILLION = float(os.getenv("GROQ_VISION_OUTPUT_PRICE_PER_MILLION", "4.00"))
    MONGODB_URI = os.getenv("MONGODB_URI", "")
    MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "advanced_rag_chatbot")
    CHROMA_PERSIST_DIRECTORY = os.getenv(
        "CHROMA_PERSIST_DIRECTORY", str(BASE_DIR / "chroma_db")
    )
    EMBEDDING_MODEL = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    FRONTEND_ORIGINS = [
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", FRONTEND_ORIGIN).split(",")
        if origin.strip()
    ]
    MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "15"))
    AUTH_SECRET = os.getenv("AUTH_SECRET", "")
    AUTH_TOKEN_HOURS = int(os.getenv("AUTH_TOKEN_HOURS", "12"))
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
    OAUTH_REDIRECT_BASE_URL = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    OAUTH_FRONTEND_URL = os.getenv("OAUTH_FRONTEND_URL", FRONTEND_ORIGIN)
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
    TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic")

settings = Settings()
