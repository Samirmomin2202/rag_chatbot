import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pymongo.errors import ServerSelectionTimeoutError

from app.config import settings
from app.database import (
    create_user,
    find_user_by_email,
    find_user_by_id,
    list_users,
    set_user_role,
    assign_legacy_conversations,
    get_user_usage,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/api/admin", tags=["administration"])
bearer = HTTPBearer(auto_error=False)
PBKDF2_ROUNDS = 310_000


class Registration(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=128)


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RoleUpdate(BaseModel):
    role: str


def _auth_secret() -> bytes:
    secret = settings.AUTH_SECRET
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="Set AUTH_SECRET to a random value of at least 32 characters in backend/.env.")
    return secret.encode("utf-8")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"{base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_text, digest_text = stored.split("$", 1)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(actual, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _issue_token(user: dict) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({
        "sub": user["user_id"],
        "iat": now,
        "exp": now + settings.AUTH_TOKEN_HOURS * 3600,
    }, separators=(",", ":")).encode())
    content = f"{header}.{payload}"
    signature = _b64(hmac.new(_auth_secret(), content.encode(), hashlib.sha256).digest())
    return f"{content}.{signature}"


def _decode_token(token: str) -> dict:
    try:
        header, payload, signature = token.split(".")
        content = f"{header}.{payload}"
        expected = _b64(hmac.new(_auth_secret(), content.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if decoded.get("exp", 0) <= time.time() or not decoded.get("sub"):
            raise ValueError("expired token")
        return decoded
    except HTTPException:
        raise
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired login. Please sign in again.")


def _public_user(user: dict) -> dict:
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


def _email(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@(?:localhost|[^\s@]+\.[^\s@]+)", value):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return value


def _ensure_admin():
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return
    email = _email(settings.ADMIN_EMAIL)
    existing = find_user_by_email(email)
    if existing:
        assign_legacy_conversations(existing["user_id"])
        return
    try:
        create_user({
            "user_id": str(uuid4()),
            "email": email,
            "display_name": "Administrator",
            "password_hash": _hash_password(settings.ADMIN_PASSWORD),
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        admin = find_user_by_email(email)
        assign_legacy_conversations(admin["user_id"])
    except Exception:
        # A simultaneous first login may have inserted this unique email already.
        if not find_user_by_email(email):
            raise


def _raise_database_unavailable(exc: Exception):
    raise HTTPException(
        status_code=503,
        detail=(
            "Cannot connect to MongoDB Atlas. Check that the cluster is active, "
            "this computer's current public IP is in Atlas Network Access, and "
            "outbound TCP port 27017 is allowed."
        ),
    ) from exc


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    claims = _decode_token(credentials.credentials)
    try:
        user = find_user_by_id(claims["sub"])
    except ServerSelectionTimeoutError as exc:
        _raise_database_unavailable(exc)
    if not user:
        raise HTTPException(status_code=401, detail="Account not found. Please sign in again.")
    return _public_user(user)


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required for this action.")
    return user


def _auth_response(user: dict) -> dict:
    return {"access_token": _issue_token(user), "token_type": "bearer", "user": _public_user(user)}


@router.post("/register")
def register(body: Registration):
    _auth_secret()
    try:
        _ensure_admin()
    except ServerSelectionTimeoutError as exc:
        _raise_database_unavailable(exc)
    email = _email(body.email)
    if find_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = {
        "user_id": str(uuid4()),
        "email": email,
        "display_name": body.display_name.strip(),
        "password_hash": _hash_password(body.password),
        "role": "user",
        "created_at": datetime.now(timezone.utc),
    }
    try:
        create_user(user)
    except Exception:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return _auth_response(user)


@router.post("/login")
def login(body: Login):
    _auth_secret()
    try:
        _ensure_admin()
        user = find_user_by_email(_email(body.email))
    except ServerSelectionTimeoutError as exc:
        _raise_database_unavailable(exc)
    if not user or not _verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return _auth_response(user)


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"user": user}


@router.get("/usage")
def usage(user: dict = Depends(current_user)):
    return {"usage": get_user_usage(user["user_id"])}


@admin_router.get("/users")
def users(_: dict = Depends(admin_user)):
    return {"users": list_users()}


@admin_router.patch("/users/{user_id}/role")
def update_role(user_id: str, body: RoleUpdate, actor: dict = Depends(admin_user)):
    if body.role not in {"user", "admin"}:
        raise HTTPException(status_code=422, detail="Role must be 'user' or 'admin'.")
    if actor["user_id"] == user_id and body.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own administrator role.")
    if not find_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found.")
    set_user_role(user_id, body.role)
    return {"message": "Role updated.", "user_id": user_id, "role": body.role}
