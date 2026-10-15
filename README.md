# Advanced RAG Chatbot — Groq + FastAPI + MongoDB Atlas + ChromaDB

A starter project with:
- React + Vite frontend
- FastAPI backend
- Groq chat completions with function/tool calling
- MongoDB Atlas conversation history
- PDF upload, chunking, Sentence Transformers embeddings, ChromaDB retrieval
- Calculator, PDF library listing, general PDF search, and selected-PDF search tools

## Requirements
- Python 3.10 or newer (Python 3.11 recommended)
- Node.js 20 or newer
- MongoDB Atlas cluster and database user
- Groq API key

## 1. Configure MongoDB Atlas
1. Create a cluster in https://cloud.mongodb.com/
2. Create a database user.
3. In Network Access, allow your current IP address.
4. Select Connect → Drivers → Python and copy the connection string.
5. URL-encode special characters in the password if needed.

## 2. Configure the backend
Open a terminal in `backend`:

PowerShell:
```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and set `GROQ_API_KEY` and `MONGODB_URI`.
Do not commit `.env` or share it.

Set `AUTH_SECRET` to a random secret of at least 32 characters, and set
`ADMIN_EMAIL` plus a strong `ADMIN_PASSWORD`. The first login or registration
creates that administrator account. New registrations receive the `user` role.
Users can upload and search their own PDFs and access only their own conversation
history. Admins can change account roles and see/search every user's PDFs.

Optional Google and GitHub sign-in uses the same application JWT session as
password login. Create OAuth applications with these callback URLs:

- Google: `http://localhost:8000/api/auth/oauth/google/callback`
- GitHub: `http://localhost:8000/api/auth/oauth/github/callback`

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, and
`GITHUB_CLIENT_SECRET` in `backend/.env`. Set `OAUTH_REDIRECT_BASE_URL` to the
backend's public base URL and `OAUTH_FRONTEND_URL` to the frontend URL to return
to after sign-in. For example, if Vite runs at `http://127.0.0.1:5174`, set
`OAUTH_FRONTEND_URL=http://127.0.0.1:5174` and register the exact callback URLs
for the backend address you use. Social accounts are matched by verified email;
new social accounts are created with the standard `user` role. Keep provider
client secrets in `backend/.env` and never put them in frontend variables.

Generate a secret in PowerShell with:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For web search, set `TAVILY_API_KEY` in `backend/.env`. Search requests are sent
server-side to Tavily; without this key, web search is unavailable. PDF retrieval
combines dense embeddings and BM25 keyword search, fuses candidate ranks, then
reranks passages using vector similarity and query-term coverage. Retrieval is
filtered by account ownership and can additionally filter by exact filename,
PDF ID, or page. Tune `RAG_TOP_K`, `RAG_CANDIDATE_K`,
`RAG_LEXICAL_MAX_DOCUMENTS`, and the `RAG_RERANK_*_WEIGHT` settings in
`backend/.env`; changes take effect after restarting the backend. Relevant
earlier messages from the same account are retrieved for chat context.

Start the API:
```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --port 8000
```

API docs: http://localhost:8000/docs
Health check: http://localhost:8000/api/health

## 3. Configure the frontend
Open a second terminal and install the frontend dependencies:
```powershell
cd frontend
npm install --include=dev
npm run dev
```
Open the URL Vite prints, usually http://localhost:5173.

Alternatively, from the project root, install and start the frontend with:
```powershell
npm run frontend:install
npm run dev
```

## 4. Try it
- Ask: `Explain RAG in simple words`
- Ask: `Calculate 125 multiplied by 24`
- Upload a PDF using the paperclip button, then ask questions about it.

## Notes
- ChromaDB persists its local data under `backend/chroma_db`.
- MongoDB stores chat messages and uploaded-document metadata.
- PDF retrieval is scoped to the current local Chroma collection. This starter does not implement user authentication or per-user document access controls. Do not expose it publicly without adding authentication, authorization, rate limits, and upload restrictions.
- The frontend uses a browser-generated conversation ID stored in localStorage. This is convenient for local development, not a security boundary.
- If your Groq account does not support the configured model, change `GROQ_MODEL` in `backend/.env` to a model currently available to your account.
- First startup of Sentence Transformers may download the embedding model.
