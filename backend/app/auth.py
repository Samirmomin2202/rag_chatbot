import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
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
    find_user_by_oauth_identity,
    set_user_oauth_identity,
    update_user_details,
    delete_user_data,
)
from app.chroma_store import documents_collection as chroma_documents

router = APIRouter(prefix="/api/auth", tags=["authentication"])
admin_router = APIRouter(prefix="/api/admin", tags=["administration"])
bearer = HTTPBearer(auto_error=False)
PBKDF2_ROUNDS = 310_000
OAUTH_STATE_COOKIE = "advanced-rag-oauth-state"
OAUTH_PROVIDERS = {
    "google": {
        "client_id": "GOOGLE_CLIENT_ID",
        "client_secret": "GOOGLE_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "client_id": "GITHUB_CLIENT_ID",
        "client_secret": "GITHUB_CLIENT_SECRET",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}


class Registration(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=128)


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RoleUpdate(BaseModel):
    role: str


class UserDetailsUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)


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


def _oauth_credentials(provider: str):
    config = OAUTH_PROVIDERS[provider]
    client_id = getattr(settings, config["client_id"])
    client_secret = getattr(settings, config["client_secret"])
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail=f"{provider.title()} sign-in is not configured on the server.")
    return config, client_id, client_secret


@router.get("/oauth/providers")
def oauth_providers():
    return {"providers": {
        provider: bool(getattr(settings, config["client_id"]) and getattr(settings, config["client_secret"]))
        for provider, config in OAUTH_PROVIDERS.items()
    }}


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str):
    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Sign-in provider not found.")
    config, client_id, _ = _oauth_credentials(provider)
    state = secrets.token_urlsafe(32)
    callback = f"{settings.OAUTH_REDIRECT_BASE_URL.rstrip('/')}/api/auth/oauth/{provider}/callback"
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": callback,
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
    })
    response = RedirectResponse(f"{config['authorize_url']}?{query}", status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE, f"{provider}:{state}", max_age=600, httponly=True,
        secure=settings.OAUTH_REDIRECT_BASE_URL.startswith("https://"),
        samesite="lax", path=f"/api/auth/oauth/{provider}/callback",
    )
    return response


def _google_profile(access_token: str):
    response = httpx.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}, timeout=15,
    )
    response.raise_for_status()
    profile = response.json()
    if not profile.get("sub") or not profile.get("email") or profile.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="Google did not provide a verified email address.")
    return str(profile["sub"]), profile["email"], profile.get("name") or profile["email"].split("@", 1)[0]


def _github_profile(access_token: str):
    headers = {
        "Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    profile_response = httpx.get("https://api.github.com/user", headers=headers, timeout=15)
    profile_response.raise_for_status()
    profile = profile_response.json()
    email_response = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15)
    email_response.raise_for_status()
    email = next((item["email"] for item in email_response.json() if item.get("primary") and item.get("verified")), None)
    if not profile.get("id") or not email:
        raise HTTPException(status_code=401, detail="GitHub did not provide a verified primary email address.")
    return str(profile["id"]), email, profile.get("name") or profile.get("login") or email.split("@", 1)[0]


def _frontend_oauth_redirect(provider: str, token: str | None = None, error: str | None = None):
    fragment = urlencode({"access_token": token} if token else {"oauth_error": error or "Sign-in failed."})
    response = RedirectResponse(f"{settings.OAUTH_FRONTEND_URL.rstrip('/')}/#{fragment}", status_code=303)
    response.delete_cookie(OAUTH_STATE_COOKIE, path=f"/api/auth/oauth/{provider}/callback")
    return response


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, request: Request, code: str = "", state: str = ""):
    if provider not in OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Sign-in provider not found.")
    try:
        cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
        if not state or not hmac.compare_digest(cookie_state, f"{provider}:{state}"):
            raise HTTPException(status_code=400, detail="Sign-in expired or state validation failed. Please try again.")
        if not code:
            raise HTTPException(status_code=400, detail="The provider did not return an authorization code.")
        config, client_id, client_secret = _oauth_credentials(provider)
        callback = f"{settings.OAUTH_REDIRECT_BASE_URL.rstrip('/')}/api/auth/oauth/{provider}/callback"
        token_response = httpx.post(config["token_url"], data={
            "client_id": client_id, "client_secret": client_secret, "code": code,
            "redirect_uri": callback, "grant_type": "authorization_code",
        }, headers={"Accept": "application/json"}, timeout=15)
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=401, detail="The provider did not issue an access token.")
        provider_id, email, name = _google_profile(access_token) if provider == "google" else _github_profile(access_token)
        email = _email(email)
        _ensure_admin()
        user = find_user_by_oauth_identity(provider, provider_id)
        if not user:
            user = find_user_by_email(email)
            if not user:
                user = {
                    "user_id": str(uuid4()), "email": email, "display_name": name[:80],
                    "role": "user", "created_at": datetime.now(timezone.utc),
                }
                create_user(user)
            set_user_oauth_identity(user["user_id"], provider, provider_id)
            user = find_user_by_id(user["user_id"])
        return _frontend_oauth_redirect(provider, token=_issue_token(user))
    except HTTPException as exc:
        return _frontend_oauth_redirect(provider, error=exc.detail)
    except ServerSelectionTimeoutError as exc:
        try:
            _raise_database_unavailable(exc)
        except HTTPException as db_exc:
            return _frontend_oauth_redirect(provider, error=db_exc.detail)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logging.warning("%s OAuth failed: %s", provider.title(), type(exc).__name__)
        return _frontend_oauth_redirect(provider, error=f"Could not sign in with {provider.title()}. Please try again.")


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
    target = find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.get("role") == "admin" and body.role != "admin" and sum(user.get("role") == "admin" for user in list_users()) <= 1:
        raise HTTPException(status_code=400, detail="Promote another administrator before demoting the last admin account.")
    set_user_role(user_id, body.role)
    return {"message": "Role updated.", "user_id": user_id, "role": body.role}


@admin_router.patch("/users/{user_id}")
def edit_user(user_id: str, body: UserDetailsUpdate, _: dict = Depends(admin_user)):
    existing = find_user_by_id(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found.")
    email = _email(body.email)
    duplicate = find_user_by_email(email)
    if duplicate and duplicate["user_id"] != user_id:
        raise HTTPException(status_code=409, detail="Another account already uses that email.")
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Name cannot be empty.")
    update_user_details(user_id, display_name, email)
    return {"message": "User details updated.", "user_id": user_id}


@admin_router.delete("/users/{user_id}")
def remove_user(user_id: str, actor: dict = Depends(admin_user)):
    if actor["user_id"] == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own administrator account.")
    target = find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.get("role") == "admin" and sum(user.get("role") == "admin" for user in list_users()) <= 1:
        raise HTTPException(status_code=400, detail="Promote another administrator before deleting the last admin account.")
    try:
        chroma_documents.delete(where={"owner_id": user_id})
        deleted = delete_user_data(user_id)
    except Exception as exc:
        logging.exception("Could not fully delete user %s", user_id)
        raise HTTPException(status_code=500, detail="Could not delete the account and its stored data.") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"message": "User and associated data deleted.", "user_id": user_id}
