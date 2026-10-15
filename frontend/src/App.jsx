import { useEffect, useRef, useState } from "react";
import {
  Bot, Calculator, FileSearch, MessageSquare, Plus, Send, Copy, Check, ImagePlus, X,
  Sparkles, Wrench, Paperclip, FileText, CheckCircle2, Shield, LogOut, Users, Sun, Moon, Activity
} from "lucide-react";
import {
  fetchConversation, fetchConversationImage, sendChatMessage, uploadPdf, getDocuments, getConversations,
  login, register, getCurrentUser, saveAuthSession, clearAuthSession, getUsers, updateUserRole, getUsage
} from "./api";

const STORAGE_KEY = "advanced-rag-conversation-id";
const formatTokens = value => new Intl.NumberFormat().format(value || 0);
const formatCost = value => `$${Number(value || 0).toFixed(6)}`;
const suggestions = [
  { icon: Calculator, title: "Calculate something", prompt: "Calculate 125 multiplied by 24." },
  { icon: FileSearch, title: "Ask about a PDF", prompt: "Summarize the main points in my uploaded PDF." },
  { icon: Sparkles, title: "Explore RAG", prompt: "Explain retrieval-augmented generation simply." },
];

function renderAssistantContent(content) {
  const normalized = content.replace(
    /^\*?Source:\s*extracted from\s+\*\*(.+?)\*\*,\s*page\s*(\d+)\.\*?$/gim,
    "Source: $1 · page $2"
  ).replace(/<br\s*\/?>/gi, "\n");

  const inline = (text, keyPrefix) => text.split(/(\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*\*.*?\*\*|__.*?__|\*[^*\n]+\*|`[^`]+`)/g).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (link) return <a key={key} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) return <em key={key}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key}>{part.slice(1, -1)}</code>;
    return <span key={key}>{part.replace(/\*/g, "")}</span>;
  });

  const lines = normalized.replace(/\r/g, "").split("\n");
  const blocks = [];
  const renderCodeBlock = (code, language, key) => <CodeBlock key={key} code={code} language={language} />;
  const isTableRow = line => /^\s*\|.*\|\s*$/.test(line);
  const isTableDivider = line => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableCells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim());
  const parseCompactTableRows = text => {
    const rows = text.split(/\s*\|\|\s*/).map(row => row.trim()).filter(Boolean).map(row => tableCells(row));
    if (rows.length < 2 || rows.some(row => row.length < 2 || row.length !== rows[0].length)) return null;
    return rows;
  };

  for (let index = 0; index < lines.length;) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }

    const fence = line.match(/^(```+|~~~+)\s*([\w.+#-]*)\s*$/);
    if (fence) {
      const marker = fence[1][0];
      const codeLines = [];
      index += 1;
      while (index < lines.length && !new RegExp(`^\\s*${marker}{3,}\\s*$`).test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(renderCodeBlock(codeLines.join("\n"), fence[2], `code-${index}`));
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const Tag = heading[1].length <= 2 ? "h2" : "h3";
      blocks.push(<Tag key={`heading-${index}`}>{inline(heading[2], `heading-${index}`)}</Tag>);
      index += 1;
      continue;
    }

    if (isTableRow(line)) {
      const rows = [];
      while (index < lines.length && isTableRow(lines[index].trim())) {
        const row = lines[index].trim();
        if (!isTableDivider(row)) rows.push(tableCells(row));
        index += 1;
      }
      // Some answers put all table records into one paragraph and use `||`
      // between records. Attach those rows to the preceding Markdown header.
      let compactStart = index;
      while (compactStart < lines.length && !lines[compactStart].trim()) compactStart += 1;
      let compactEnd = compactStart;
      while (compactEnd < lines.length && lines[compactEnd].trim() && !/^(#{1,4})\s+/.test(lines[compactEnd].trim())) compactEnd += 1;
      const compactRows = compactStart < lines.length
        ? parseCompactTableRows(lines.slice(compactStart, compactEnd).join(" "))
        : null;
      if (compactRows) {
        rows.push(...compactRows);
        index = compactEnd;
      }
      if (rows.length) {
        const headers = rows[0];
        blocks.push(<div className="answer-table-wrap" key={`table-${index}`}><table className="answer-table">
          <thead><tr>{headers.map((cell, i) => <th key={i}>{inline(cell, `th-${index}-${i}`)}</th>)}</tr></thead>
          <tbody>{rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, i) => <td key={i}>{inline(row[i] || "", `td-${index}-${rowIndex}-${i}`)}</td>)}</tr>)}</tbody>
        </table></div>);
      }
      continue;
    }

    const listMatch = line.match(/^\s*([-*+]\s+|\d+[.)]\s+)/);
    if (listMatch) {
      const ordered = /^\d/.test(listMatch[1]);
      const items = [];
      while (index < lines.length && /^\s*([-*+]\s+|\d+[.)]\s+)/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*+]\s+|\d+[.)]\s+)/, "").trim());
        index += 1;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={`list-${index}`}>{items.map((item, i) => <li key={i}>{inline(item, `list-${index}-${i}`)}</li>)}</List>);
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+/.test(lines[index].trim()) && !isTableRow(lines[index].trim()) && !/^\s*([-*+]\s+|\d+[.)]\s+)/.test(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(" "), `paragraph-${index}`)}</p>);
  }
  return blocks;
}

function CodeBlock({ code, language }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { /* Clipboard access can be unavailable outside a secure browser context. */ }
  }

  return <section className="code-block">
    <header className="code-block-header">
      <span className="code-language">{language || "Code"}</span>
      <button className="copy-code-button" type="button" onClick={copyCode} aria-label={copied ? "Code copied" : "Copy code"}>
        {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy"}
      </button>
    </header>
    <pre><code>{code}</code></pre>
  </section>;
}

function MessageImage({ image, conversationId, messageId }) {
  const imageRef = useRef(null);
  const [src, setSrc] = useState(() => image?.startsWith("data:image/") ? image : "");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (image || !conversationId || !messageId || !imageRef.current) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      fetchConversationImage(conversationId, messageId).then(setSrc).catch(() => setFailed(true));
    }, { rootMargin: "300px" });
    observer.observe(imageRef.current);
    return () => observer.disconnect();
  }, [image, conversationId, messageId]);

  useEffect(() => () => {
    if (src.startsWith("blob:")) URL.revokeObjectURL(src);
  }, [src]);

  if (!src) return <div ref={imageRef} className="message-image-placeholder">{failed ? "Image unavailable" : "Image · loads when visible"}</div>;
  return <img className="message-image" src={src} alt="Image attached to this message" loading="lazy" />;
}

function AuthScreen({ onSuccess, theme, onToggleTheme }) {
  const [isRegister, setIsRegister] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event) {
    event.preventDefault(); setError(""); setPending(true);
    try {
      const result = isRegister ? await register(displayName, email, password) : await login(email, password);
      onSuccess(result);
    } catch (err) { setError(err.message || "Could not sign in."); }
    finally { setPending(false); }
  }

  return <main className="auth-page">
    <form className="auth-card" onSubmit={submit}>
      <button type="button" className="theme-toggle auth-theme-toggle" onClick={onToggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
        {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}{theme === "dark" ? "Light mode" : "Dark mode"}
      </button>
      <div className="auth-brand"><div className="brand-icon"><Bot size={23} /></div><span>NEURALDESK WORKSPACE</span></div>
      <h1>{isRegister ? "Create your account" : "Welcome back"}</h1>
      <p>Sign in to access your conversations and workspace.</p>
      {isRegister && <label>Name<input required autoComplete="name" maxLength={80} value={displayName} onChange={event => setDisplayName(event.target.value)} /></label>}
      <label>Email<input required type="email" autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} /></label>
      <label>Password<input required type="password" autoComplete={isRegister ? "new-password" : "current-password"} minLength={isRegister ? 10 : 1} value={password} onChange={event => setPassword(event.target.value)} /></label>
      {error && <div className="error-banner auth-error">{error}</div>}
      <button className="auth-submit" disabled={pending}>{pending ? "Please wait..." : isRegister ? "Create account" : "Sign in"}</button>
      <button type="button" className="auth-switch" onClick={() => { setIsRegister(!isRegister); setError(""); }}>
        {isRegister ? "Already have an account? Sign in" : "New here? Create an account"}
      </button>
      {isRegister && <small>New accounts receive the User role. An administrator can change roles.</small>}
    </form>
  </main>;
}

function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("advanced-rag-theme") || "light");
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("advanced-rag-auth-user") || "null"); } catch { return null; }
  });
  const [authReady, setAuthReady] = useState(false);
  const [conversationId, setConversationId] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [imageAttachment, setImageAttachment] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [documents, setDocuments] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [activeView, setActiveView] = useState("chat");
  const [users, setUsers] = useState([]);
  const [usage, setUsage] = useState({ input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost_usd: 0, requests: 0 });
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [specificDocumentId, setSpecificDocumentId] = useState("");
  const [specificQuery, setSpecificQuery] = useState("");
  const fileInput = useRef(null);
  const imageInput = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("advanced-rag-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!localStorage.getItem("advanced-rag-auth-token")) { setAuthReady(true); return; }
    getCurrentUser().then(result => setUser(result.user)).catch(() => {
      clearAuthSession(); setUser(null);
    }).finally(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    const expire = () => { clearAuthSession(); setUser(null); };
    window.addEventListener("auth-expired", expire);
    return () => window.removeEventListener("auth-expired", expire);
  }, []);

  useEffect(() => {
    if (!user) return;
    if (!conversationId) return;
    fetchConversation(conversationId).then(data => {
      setMessages(data.messages.map((item, index) => ({
        id: `${index}-${item.role}`, role: item.role, content: item.content,
        image: item.image || null, hasImage: item.has_image || false, messageId: item.message_id || null
      })));
    }).catch(() => {});
  }, [conversationId, user]);

  useEffect(() => {
    if (!user) return;
    getDocuments().then(setDocuments).catch(() => {});
    getUsage().then(setUsage).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (documents.length && !documents.some(doc => doc.document_id === specificDocumentId)) {
      setSpecificDocumentId(documents[0].document_id);
    }
  }, [documents, specificDocumentId]);

  async function refreshConversations() {
    try { setConversations(await getConversations()); } catch { /* API may be offline */ }
  }

  useEffect(() => { if (user) refreshConversations(); }, [user]);

  useEffect(() => {
    if (user?.role === "admin" && activeView === "users") {
      getUsers().then(setUsers).catch(err => setError(err.message));
    }
  }, [user, activeView]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSend(event) {
    event?.preventDefault();
    const question = input.trim();
    if ((!question && !imageAttachment) || loading) return;
    const sentImage = imageAttachment;
    setInput(""); setImageAttachment(null); setError(""); setNotice(""); setLoading(true);
    setMessages(current => [...current, {
      id: crypto.randomUUID(), role: "user", content: question, image: sentImage
    }]);
    try {
      const result = await sendChatMessage(question, conversationId || null, sentImage);
      if (result.usage_total) setUsage(result.usage_total);
      if (user.role === "admin" && activeView === "users") getUsers().then(setUsers).catch(() => {});
      if (!conversationId && result.conversation_id) {
        setConversationId(result.conversation_id);
        localStorage.setItem(STORAGE_KEY, result.conversation_id);
      }
      setMessages(current => [...current, {
        id: crypto.randomUUID(), role: "assistant",
        content: result.answer, tools: result.tools_used || []
      }]);
      refreshConversations();
    } catch (err) {
      setError(err.message || "Unable to contact the server.");
    } finally { setLoading(false); }
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(""); setNotice(""); setUploading(true);
    try {
      const result = await uploadPdf(file);
      setNotice(`${result.filename} uploaded. Indexed ${result.chunks} text chunks from ${result.pages_with_text} pages.`);
      setDocuments(await getDocuments());
    } catch (err) {
      setError(err.message || "PDF upload failed.");
    } finally { setUploading(false); }
  }

  function handleImageSelect(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Choose a PNG, JPEG, or WEBP image.");
      return;
    }
    if (file.size > 4 * 1024 * 1024) {
      setError("Images must be 4 MB or smaller.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => { setImageAttachment(reader.result); setError(""); };
    reader.onerror = () => setError("Could not read that image.");
    reader.readAsDataURL(file);
  }

  async function handleRoleChange(userId, role) {
    try {
      await updateUserRole(userId, role);
      setUsers(await getUsers());
    } catch (err) { setError(err.message || "Could not update role."); }
  }

  function finishAuthentication(result) {
    saveAuthSession(result.access_token, result.user);
    setUser(result.user);
    setMessages([]); setConversationId(""); setImageAttachment(null); localStorage.removeItem(STORAGE_KEY);
  }

  function logout() {
    clearAuthSession(); localStorage.removeItem(STORAGE_KEY);
    setUser(null); setConversationId(""); setMessages([]); setInput(""); setImageAttachment(null); setDocuments([]); setActiveView("chat");
  }

  function startNewChat() {
    localStorage.removeItem(STORAGE_KEY);
    setConversationId(""); setMessages([]); setInput(""); setImageAttachment(null); setError(""); setNotice("");
  }

  if (!authReady) return <main className="auth-page"><p>Loading your workspace...</p></main>;
  if (!user) return <AuthScreen onSuccess={finishAuthentication} theme={theme} onToggleTheme={() => setTheme(current => current === "dark" ? "light" : "dark")} />;

  function openConversation(id) {
    setConversationId(id);
    localStorage.setItem(STORAGE_KEY, id);
    setMessages([]); setInput(""); setImageAttachment(null); setError(""); setNotice("");
  }

  function startCalculatorPrompt() {
    setActiveView("tools");
  }

  function tryTool(prompt) {
    setActiveView("chat");
    setInput(prompt);
    requestAnimationFrame(() => document.querySelector(".composer textarea")?.focus());
  }

  function askAboutDocument() {
    const filename = selectedDocument?.filename;
    setSelectedDocument(null);
    if (filename) tryTool(`Summarize ${filename} and explain its key points.`);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon"><Bot size={23} /></div>
          <div><h2>NeuralDesk</h2><span>RAG AI WORKSPACE</span></div>
        </div>
        <button className="new-chat" onClick={startNewChat}><Plus size={18} />New conversation</button>
        <div className="sidebar-label">YOUR WORKSPACE</div>
        <button className={`nav-item${activeView === "chat" ? " active" : ""}`} aria-current={activeView === "chat" ? "page" : undefined} onClick={() => setActiveView("chat")}><MessageSquare size={17} />AI Assistant</button>
        <button className="nav-item nav-button" onClick={() => fileInput.current?.click()}><FileSearch size={17} />Upload knowledge PDF</button>
        <button className={`nav-item nav-button${activeView === "tools" ? " active" : ""}`} aria-current={activeView === "tools" ? "page" : undefined} onClick={startCalculatorPrompt}><Wrench size={17} />Tools</button>
        <button className={`nav-item nav-button${activeView === "usage" ? " active" : ""}`} aria-current={activeView === "usage" ? "page" : undefined} onClick={() => setActiveView("usage")}><Activity size={17} />Usage & cost</button>
        {user.role === "admin" && <button className={`nav-item nav-button${activeView === "users" ? " active" : ""}`} aria-current={activeView === "users" ? "page" : undefined} onClick={() => setActiveView("users")}><Users size={17} />Manage users</button>}
        <div className="conversation-list">
          <div className="sidebar-label">PAST CONVERSATIONS ({conversations.length})</div>
          {conversations.map((conversation, index) => <button
            className={`conversation-item${conversation.conversation_id === conversationId ? " selected" : ""}`}
            aria-current={conversation.conversation_id === conversationId ? "page" : undefined}
            key={conversation.conversation_id}
            onClick={() => openConversation(conversation.conversation_id)}
            title={conversation.title || "Conversation"}
          >
            <MessageSquare size={14} />
            <span>{conversation.title || `Conversation ${index + 1}`}</span>
          </button>)}
          {conversations.length === 0 && <p className="empty-docs">Your saved chats will appear here.</p>}
        </div>
        <div className="document-list">
          <div className="sidebar-label">KNOWLEDGE FILES ({documents.length})</div>
          {documents.map(doc => <button className="document-item" key={doc.document_id} onClick={() => setSelectedDocument(doc)} title={`${doc.filename} · ${doc.chunks} indexed text chunks`}><FileText size={14} /><span>{doc.filename}</span></button>)}
          {documents.length === 0 && <p className="empty-docs">No PDFs uploaded yet.</p>}
        </div>
        <input ref={fileInput} type="file" accept=".pdf,application/pdf" hidden onChange={handleUpload} />
        <div className="sidebar-bottom"><div className="status-dot" /><div><strong>{user.display_name}</strong><span>{user.role === "admin" ? "Administrator" : "User"} · {user.email}</span></div><button className="logout-button" title="Sign out" aria-label="Sign out" onClick={logout}><LogOut size={15} /></button></div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div><span className="eyebrow">WORKSPACE / {activeView === "tools" ? "TOOLS" : activeView === "users" ? "ACCESS" : activeView === "usage" ? "USAGE" : "CHAT"}</span><h1>{activeView === "tools" ? "Available tools" : activeView === "users" ? "Manage users" : activeView === "usage" ? "Token usage & estimated cost" : "AI Assistant"}</h1></div>
          <div className="topbar-actions">
            <button type="button" className="theme-toggle" onClick={() => setTheme(current => current === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}{theme === "dark" ? "Light mode" : "Dark mode"}
            </button>
            <div className="model-badge"><Shield size={14} />{user.role === "admin" ? "Administrator" : "User"}</div>
          </div>
        </header>

        <section className="chat-area">
          {activeView === "users" && user.role === "admin" ? (
            <div className="admin-workspace">
              <p>New accounts start as users. Assign administrator access only to people who need to manage accounts and access every user's PDFs. Usage totals are tracked since token reporting was enabled.</p>
              <div className="user-table">
                <div className="user-row user-header usage-user-row"><span>Name</span><span>Email</span><span>Role</span><span>Tokens used</span><span>Est. cost</span></div>
                {users.map(account => <div className="user-row usage-user-row" key={account.user_id}>
                  <span>{account.display_name}</span><span>{account.email}</span>
                  <select aria-label={`Role for ${account.email}`} value={account.role} onChange={event => handleRoleChange(account.user_id, event.target.value)}>
                    <option value="user">User</option><option value="admin">Admin</option>
                  </select>
                  <span>{formatTokens(account.usage?.total_tokens)}</span><span>{formatCost(account.usage?.estimated_cost_usd)}</span>
                </div>)}
                {users.length === 0 && <p className="empty-docs">No accounts found.</p>}
              </div>
            </div>
          ) : activeView === "usage" ? (
            <div className="usage-workspace">
              <p className="tools-intro">Your account’s model usage. Costs are estimates based on configured per-million-token rates; provider billing may differ. Totals start from when usage tracking was enabled.</p>
              <div className="usage-summary-grid">
                <article className="usage-stat"><span>Total tokens</span><strong>{formatTokens(usage.total_tokens)}</strong><small>Input + output</small></article>
                <article className="usage-stat"><span>Input tokens</span><strong>{formatTokens(usage.input_tokens)}</strong><small>Sent to the models</small></article>
                <article className="usage-stat"><span>Output tokens</span><strong>{formatTokens(usage.output_tokens)}</strong><small>Generated by the models</small></article>
                <article className="usage-stat"><span>Estimated cost</span><strong>{formatCost(usage.estimated_cost_usd)}</strong><small>Across {formatTokens(usage.requests)} requests</small></article>
              </div>
            </div>
          ) : activeView === "tools" ? (
            <div className="tools-workspace">
              <p className="tools-intro">Choose a tool to see how it works. Selecting one prepares a prompt or opens the upload flow.</p>
              <div className="tools-grid">
                <article className="tool-card">
                  <div className="tool-card-icon"><Calculator size={20} /></div>
                  <h2>Calculator</h2>
                  <p>Add, subtract, multiply, or divide numbers. The assistant runs the calculation and explains the result.</p>
                  <span className="tool-example">Example: 250 multiplied by 12</span>
                  <button onClick={() => tryTool("Calculate 250 multiplied by 12.")}>Try calculator</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><FileSearch size={20} /></div>
                  <h2>Search your PDFs</h2>
                  <p>Find relevant passages in documents you uploaded. Answers can include the source file and page.</p>
                  <span className="tool-example">Example: Find the main responsibilities in my resume</span>
                  <button onClick={() => tryTool("Search my uploaded PDFs for the main responsibilities listed in my resume.")}>Try PDF search</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><FileText size={20} /></div>
                  <h2>List my PDFs</h2>
                  <p>Ask which documents are available in your private library.</p>
                  <span className="tool-example">Shows only files you can access</span>
                  <button onClick={() => tryTool("List the PDF documents available to me.")}>Show my PDFs</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><Sparkles size={20} /></div>
                  <h2>Web search</h2>
                  <p>Search public web sources for recent or external information and get linked citations.</p>
                  <span className="tool-example">Requires a Tavily API key in backend/.env</span>
                  <button onClick={() => tryTool("Search the web for the latest information about ")}>Try web search</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><MessageSquare size={20} /></div>
                  <h2>Conversation memory</h2>
                  <p>Bring relevant details from your previous conversations into a new answer.</p>
                  <span className="tool-example">Memory is private to your account</span>
                  <button onClick={() => tryTool("What have we discussed before about ")}>Use conversation memory</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><FileSearch size={20} /></div>
                  <h2>Search a specific PDF</h2>
                  <p>Choose one file and search its contents for a specific detail.</p>
                  <select className="tool-select" aria-label="Choose a PDF to search" value={specificDocumentId} onChange={event => setSpecificDocumentId(event.target.value)}>
                    {documents.length === 0 && <option value="">No PDFs available</option>}
                    {documents.map(doc => <option key={doc.document_id} value={doc.document_id}>{doc.filename}</option>)}
                  </select>
                  <input className="tool-query" aria-label="What to find in the PDF" placeholder="What should I look for?" value={specificQuery} onChange={event => setSpecificQuery(event.target.value)} />
                  <button disabled={!specificDocumentId || !specificQuery.trim()} onClick={() => {
                    const selected = documents.find(doc => doc.document_id === specificDocumentId);
                    if (selected) tryTool(`Search uploaded PDF document ID ${selected.document_id} named "${selected.filename}" for: ${specificQuery.trim()}`);
                    setSpecificQuery("");
                  }}>Search this PDF</button>
                </article>
                <article className="tool-card">
                  <div className="tool-card-icon"><FileText size={20} /></div>
                  <h2>Upload a PDF</h2>
                  <p>Add a private PDF to your knowledge files. Only you and administrators can see or search it.</p>
                  <span className="tool-example">PDF files up to the configured size limit</span>
                  <button onClick={() => fileInput.current?.click()}>Choose a PDF</button>
                </article>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon"><Sparkles size={27} /></div>
              <span className="eyebrow">YOUR AI WORKSPACE</span>
              <h2>What can I help you<br />figure out today?</h2>
              <p>Ask a question, upload a PDF, or let the assistant use its available tools.</p>
              <div className="suggestion-grid">
                {suggestions.map(item => {
                  const Icon = item.icon;
                  return <button className="suggestion-card" key={item.title} onClick={() => setInput(item.prompt)}>
                    <Icon size={20} /><strong>{item.title}</strong><span>{item.prompt}</span>
                  </button>;
                })}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map(message => <article className={`message ${message.role}`} key={message.id}>
                <div className="avatar">{message.role === "assistant" ? <Bot size={19} /> : "Y"}</div>
                <div className="message-body">
                  <div className="message-author">{message.role === "assistant" ? "AI Assistant" : "You"}</div>
                  <div className="message-content">
                    {(message.image || message.hasImage) && <MessageImage image={message.image} conversationId={conversationId} messageId={message.messageId} />}
                    {message.role === "assistant" ? renderAssistantContent(message.content) : message.content}
                  </div>
                </div>
              </article>)}
              {loading && <div className="loading-line"><span className="loading-dot" />Assistant is thinking...</div>}
              <div ref={bottomRef} />
            </div>
          )}
        </section>

        {selectedDocument && <div className="modal-backdrop" onClick={() => setSelectedDocument(null)}>
          <section className="document-dialog" role="dialog" aria-modal="true" aria-labelledby="document-dialog-title" onClick={event => event.stopPropagation()}>
            <div className="tool-card-icon"><FileText size={20} /></div>
            <h2 id="document-dialog-title">{selectedDocument.filename}</h2>
            <p>{selectedDocument.chunks} searchable text chunks</p>
            {selectedDocument.uploaded_by && <p>Uploaded by {selectedDocument.uploaded_by}</p>}
            <div className="document-dialog-actions">
              <button className="auth-switch" onClick={() => setSelectedDocument(null)}>Close</button>
              <button className="auth-submit" onClick={askAboutDocument}>Ask about this PDF</button>
            </div>
          </section>
        </div>}

        {(error || notice) && <div className={error ? "error-banner" : "notice-banner"}>{error || <><CheckCircle2 size={16} />{notice}</>}</div>}
        {uploading && <div className="upload-status">Processing PDF and creating embeddings. First run may take a few minutes...</div>}

        {activeView === "chat" && <form className="composer" onSubmit={handleSend}>
          {imageAttachment && <div className="image-attachment-preview">
            <img src={imageAttachment} alt="Selected image preview" />
            <button type="button" onClick={() => setImageAttachment(null)} aria-label="Remove attached image"><X size={15} /></button>
          </div>}
          <textarea value={input} onChange={event => setInput(event.target.value)}
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault(); handleSend();
              }
            }}
            placeholder="Ask anything... (Shift + Enter for a new line)" rows={2} maxLength={4000} disabled={loading} />
          <div className="composer-footer">
            <div className="composer-tools">
              <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={handleImageSelect} />
              <button type="button" className="attach-button image-attach-button" onClick={() => imageInput.current?.click()} disabled={loading}>
                <ImagePlus size={15} />Add image
              </button>
              <button type="button" className="attach-button" onClick={() => fileInput.current?.click()} disabled={uploading}>
                <Paperclip size={15} />{uploading ? "Uploading..." : "Upload PDF"}
              </button>
              <span>Verify important information.</span>
            </div>
            <button type="submit" className="send-button" disabled={(!input.trim() && !imageAttachment) || loading}><Send size={17} />Send</button>
          </div>
        </form>}
        <footer className="page-footer">Powered by Groq · MongoDB Atlas · ChromaDB</footer>
      </main>
    </div>
  );
}

export default App;
