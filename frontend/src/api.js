const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TOKEN_KEY = "advanced-rag-auth-token";

export function saveAuthSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem("advanced-rag-auth-user", JSON.stringify(user));
}

export function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("advanced-rag-auth-user");
}

async function request(path, options = {}, authenticated = true) {
  const headers = new Headers(options.headers || {});
  const token = localStorage.getItem(TOKEN_KEY);
  if (authenticated && token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && authenticated) {
      window.dispatchEvent(new CustomEvent("auth-expired"));
    }
    throw new Error(data.detail || "Request failed.");
  }
  return data;
}

export async function login(email, password) {
  return request("/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }, false);
}

export async function register(displayName, email, password) {
  return request("/api/auth/register", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName, email, password }),
  }, false);
}

export async function getCurrentUser() {
  return request("/api/auth/me");
}

export async function getUsers() {
  const data = await request("/api/admin/users");
  return data.users || [];
}

export async function getUsage() {
  const data = await request("/api/auth/usage");
  return data.usage || {};
}

export async function updateUserRole(userId, role) {
  return request(`/api/admin/users/${encodeURIComponent(userId)}/role`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
}

export async function sendChatMessage(message, conversationId, image = null) {
  return request("/api/chat", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId || null, image }),
  });
}

export async function fetchConversation(conversationId) {
  return request(`/api/conversations/${encodeURIComponent(conversationId)}`);
}

export async function fetchConversationImage(conversationId, messageId) {
  const headers = new Headers();
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(conversationId)}/images/${encodeURIComponent(messageId)}`, { headers });
  if (!response.ok) throw new Error("Could not load this image.");
  return URL.createObjectURL(await response.blob());
}

export async function getConversations() {
  const data = await request("/api/conversations");
  return data.conversations || [];
}

export async function uploadPdf(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/documents/upload", { method: "POST", body: form });
}

export async function getDocuments() {
  const data = await request("/api/documents");
  return data.documents || [];
}
