import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertCircle,
  Bot,
  Check,
  Database,
  History,
  FileUp,
  KeyRound,
  Loader2,
  LogOut,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  UserPlus,
  Users,
  X
} from "lucide-react";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import "./styles.css";

type User = { id: string; username: string; disabled: boolean; roles: string[]; knowledgeBaseIds: string[] };
type Role = { id: string; name: string; description: string; systemRole: boolean; knowledgeBaseIds: string[] };
type KnowledgeBase = { id: string; name: string; description: string };
type ChatSession = { id: string; userId: string; title: string; knowledgeBaseIds: string[]; createdAt: string };
type ChatRole = "user" | "assistant" | "system";
type ChatTurn = { id: string; role: ChatRole; content: string };
type ChatMessage = ChatTurn & { sessionId: string; createdAt: string };
type AuthMode = "login" | "register";
type AdminPage = "upload" | "users" | "roles" | "chat";

const apiBase = import.meta.env.VITE_API_BASE ?? "";
const pdfWorkerSrc = `${pdfWorkerUrl}?v=module-mime`;
const historyRounds = 10;
const sessionTitleMaxLength = 60;
const defaultDocText = "员工报销需要在费用发生后 30 天内提交发票、付款凭证和审批单。差旅费用需要关联出差申请。";

function sessionStorageKey(userId: string): string {
  return `rag.activeSession.${userId}`;
}

function rememberedSessionId(userId: string): string | null {
  try {
    return localStorage.getItem(sessionStorageKey(userId));
  } catch {
    return null;
  }
}

function rememberSession(userId: string, sessionId: string | null) {
  try {
    if (sessionId) localStorage.setItem(sessionStorageKey(userId), sessionId);
    else localStorage.removeItem(sessionStorageKey(userId));
  } catch {
    // Browsers can disable persistent storage; session switching still works in memory.
  }
}

function titleFromQuestion(question: string): string {
  return Array.from(question.trim().replace(/\s+/g, " ")).slice(0, 32).join("") || "新对话";
}

function formatSessionTime(createdAt: string): string {
  const value = new Date(createdAt);
  if (Number.isNaN(value.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(value);
}

async function request<T>(path: string, token: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method ?? (options.body ? "POST" : "GET"),
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  if (!response.ok) throw new Error(await readableError(response));
  return response.json();
}

async function readableError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return `${response.status} ${response.statusText}`;
  try {
    const body = JSON.parse(text);
    return body.message || body.error || body.detail || text;
  } catch {
    return text;
  }
}

function parseSseBlock(block: string): { event: string; data: string } | null {
  if (!block.trim()) return null;
  const event = block.match(/^event:\s*(.*)$/m)?.[1]?.trim() || "message";
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace(/^data:\s?/, ""))
    .join("\n");
  return { event, data };
}

function summarizeAgentEvent(event: string, data: string): string {
  try {
    const body = JSON.parse(data) as {
      name?: string;
      status?: string;
      summary?: string;
      type?: string;
      filename?: string;
      score?: number;
      capability_id?: string;
      selected_capabilities?: string[];
      steps?: Array<{ capability_id?: string }>;
      replan_count?: number;
    };
    if (event === "plan") {
      const selected = body.selected_capabilities?.join(", ") || "direct";
      const replans = body.replan_count ? `, replanned ${body.replan_count} time(s)` : "";
      return `Agent plan: ${selected}${replans}`;
    }
    if (event === "tool_result") {
      const status = body.status ? ` (${body.status})` : "";
      return `${body.name ?? "tool"}${status}: ${body.summary ?? data}`;
    }
    if (event === "citation") {
      if (body.type === "rag") return `citation: ${body.filename ?? "document"} score=${body.score ?? "-"}`;
      if (body.type === "sql") return `citation: ${body.summary ?? "SQL summary"}`;
      if (body.type === "java") return `citation: ${body.summary ?? body.capability_id ?? "Java service"}`;
    }
  } catch {
    return data;
  }
  return data;
}

function keepLatestRounds(messages: ChatTurn[], rounds = historyRounds): ChatTurn[] {
  if (rounds <= 0) return messages;
  let userTurnsSeen = 0;
  let start = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") {
      userTurnsSeen += 1;
      if (userTurnsSeen === rounds) {
        start = index;
        break;
      }
    }
  }
  return userTurnsSeen < rounds ? messages : messages.slice(start);
}

function fileExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function readableRatio(text: string): number {
  if (!text) return 0;
  const readable = text.match(/[\p{L}\p{N}\p{Script=Han}，。！？；：、（）《》“”"'\-.,!?;:()[\]\s]/gu)?.length ?? 0;
  return readable / text.length;
}

function isReadableExtract(text: string): boolean {
  const clean = text.trim();
  if (!clean) return false;
  const replacementCount = (clean.match(/\uFFFD/g) ?? []).length;
  const controlCount = (clean.match(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g) ?? []).length;
  if (replacementCount + controlCount > Math.max(3, clean.length * 0.08)) return false;
  return readableRatio(clean) >= 0.55;
}

function sanitizeExtractedText(text: string): string {
  return text
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ")
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter((line) => !/^Page\s+\d+$/i.test(line))
    .filter(isReadableExtract)
    .join("\n")
    .trim();
}

async function extractPdfText(file: File): Promise<string> {
  const pdfjsLib = await import("pdfjs-dist");
  pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;
  const data = new Uint8Array(await file.arrayBuffer());
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  const pages: string[] = [];
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const text = content.items
      .map((item) => ("str" in item ? item.str : ""))
      .filter(isReadableExtract)
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
    if (text) pages.push(text);
  }
  return pages.join("\n\n");
}

async function extractWordText(file: File): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
  return sanitizeExtractedText(result.value);
}

async function extractSpreadsheetText(file: File): Promise<string> {
  const XLSX = await import("xlsx");
  const workbook = XLSX.read(await file.arrayBuffer(), { type: "array" });
  return workbook.SheetNames.map((sheetName) => {
    const csv = XLSX.utils.sheet_to_csv(workbook.Sheets[sheetName]).trim();
    return csv ? `Sheet: ${sheetName}\n${csv}` : "";
  })
    .filter(Boolean)
    .join("\n\n");
}

async function extractDocumentText(file: File): Promise<string> {
  const extension = fileExtension(file.name);
  if (extension === "pdf") return sanitizeExtractedText(await extractPdfText(file));
  if (extension === "docx") return extractWordText(file);
  if (["xlsx", "xls", "ods"].includes(extension)) return extractSpreadsheetText(file);
  if (["txt", "md", "markdown", "csv", "tsv", "json", "log", "yml", "yaml", "xml", "html", "htm"].includes(extension)) {
    return sanitizeExtractedText(await file.text());
  }
  throw new Error(`暂不支持 ${extension || "未知"} 格式，请上传 PDF、Word、Excel、Markdown 或文本文件。`);
}

function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [adminPage, setAdminPage] = useState<AdminPage>("upload");
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [sessionHistoryOpen, setSessionHistoryOpen] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatTurn[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [docText, setDocText] = useState(defaultDocText);
  const [selectedKbId, setSelectedKbId] = useState("");
  const [loginForm, setLoginForm] = useState({ username: "admin", password: "admin123" });
  const [registerForm, setRegisterForm] = useState({ username: "", password: "" });
  const [newRole, setNewRole] = useState({ name: "", description: "" });
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState("");

  const isAdmin = user?.roles.includes("ADMIN") ?? false;
  const selectedKbIds = useMemo(() => kbs.map((kb) => kb.id), [kbs]);

  useEffect(() => {
    if (kbs.length > 0 && !selectedKbId) setSelectedKbId(kbs[0].id);
  }, [kbs, selectedKbId]);

  function pushEvent(message: string) {
    setEvents((old) => [message, ...old].slice(0, 12));
  }

  function appendAssistantToken(id: string, tokenText: string) {
    setChatMessages((old) => old.map((msg) => msg.id === id ? { ...msg, content: msg.content + tokenText } : msg));
  }

  async function hydrate(authToken: string, current: User) {
    const visibleKbs = await request<KnowledgeBase[]>("/api/knowledge-bases", authToken);
    const availableSessions = await request<ChatSession[]>("/api/chat/sessions", authToken);
    const rememberedId = rememberedSessionId(current.id);
    const restoredSession = availableSessions.find((item) => item.id === rememberedId) ?? availableSessions[0] ?? null;
    const history = restoredSession
      ? await request<ChatMessage[]>(`/api/chat/sessions/${restoredSession.id}/messages?rounds=${historyRounds}`, authToken)
      : [];
    setToken(authToken);
    setUser(current);
    setKbs(visibleKbs);
    setSessions(availableSessions);
    setSession(restoredSession);
    setChatMessages(keepLatestRounds(history));
    rememberSession(current.id, restoredSession?.id ?? null);
    if (current.roles.includes("ADMIN")) {
      const [adminUsers, adminRoles] = await Promise.all([
        request<User[]>("/api/admin/users", authToken),
        request<Role[]>("/api/admin/roles", authToken)
      ]);
      setUsers(adminUsers);
      setRoles(adminRoles);
    } else {
      setUsers([]);
      setRoles([]);
    }
  }

  async function login() {
    setBusy("login");
    setError("");
    setSuccess("");
    try {
      const data = await request<{ token: string; user: User }>("/api/auth/login", "", { body: loginForm });
      await hydrate(data.token, data.user);
      pushEvent("登录成功");
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function register() {
    setBusy("register");
    setError("");
    setSuccess("");
    try {
      await request<{ token: string; user: User }>("/api/auth/register", "", { body: registerForm });
      setLoginForm({ username: registerForm.username, password: "" });
      setRegisterForm({ username: "", password: "" });
      setAuthMode("login");
      setSuccess("注册成功，请使用新账号登录。");
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  function logout() {
    setToken("");
    setUser(null);
    setUsers([]);
    setRoles([]);
    setKbs([]);
    setSessions([]);
    setSession(null);
    setSessionHistoryOpen(false);
    setEditingSessionId(null);
    setEditingSessionTitle("");
    setQuestion("");
    setChatMessages([]);
    setEvents([]);
  }

  async function refreshAdminData() {
    if (!token || !user) return;
    setBusy("refresh");
    setError("");
    setSuccess("");
    try {
      await hydrate(token, user);
      pushEvent("管理数据已刷新");
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function createRole() {
    if (!newRole.name.trim()) return;
    setBusy("role");
    setError("");
    setSuccess("");
    try {
      await request<Role>("/api/admin/roles", token, { body: newRole });
      setNewRole({ name: "", description: "" });
      await refreshAdminData();
      pushEvent("角色已创建");
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function updateUserRoles(target: User, roleName: string, checked: boolean) {
    const roleIds = roles
      .filter((role) => checked ? target.roles.includes(role.name) || role.name === roleName : target.roles.includes(role.name) && role.name !== roleName)
      .map((role) => role.id);
    await request<User>(`/api/admin/users/${target.id}/roles`, token, { method: "PUT", body: { roleIds } });
    await refreshAdminData();
  }

  async function setUserDisabled(target: User, disabled: boolean) {
    await request<User>(`/api/admin/users/${target.id}/disabled`, token, { method: "PUT", body: { disabled } });
    await refreshAdminData();
  }

  async function resetPassword(target: User) {
    const password = resetPasswords[target.id] ?? "";
    setError("");
    setSuccess("");
    if (password.length < 6) {
      setError("新密码至少需要 6 位。");
      return;
    }
    try {
      await request<User>(`/api/admin/users/${target.id}/password`, token, { method: "PUT", body: { password } });
      setResetPasswords((old) => ({ ...old, [target.id]: "" }));
      setSuccess(`已重置 ${target.username} 的密码。`);
      pushEvent(`已重置 ${target.username} 的密码`);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    }
  }

  async function updateRoleKb(role: Role, kbId: string, checked: boolean) {
    const knowledgeBaseIds = checked
      ? Array.from(new Set([...role.knowledgeBaseIds, kbId]))
      : role.knowledgeBaseIds.filter((id) => id !== kbId);
    await request<Role>(`/api/admin/roles/${role.id}/knowledge-bases`, token, { method: "PUT", body: { knowledgeBaseIds } });
    await refreshAdminData();
  }

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("upload");
    setError("");
    setSuccess("");
    try {
      pushEvent(`开始解析文件：${file.name}`);
      const content = await extractDocumentText(file);
      if (!content.trim()) throw new Error("没有从文件中提取到可索引文本，扫描版 PDF 需要先 OCR。");
      setDocText(content);
      await uploadDocument(file.name, content);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function uploadDocument(filename = "employee-policy.txt", content = docText) {
    if (!selectedKbId) throw new Error("请选择知识库");
    if (!content.trim()) throw new Error("文档内容为空，无法上传");
    setBusy("upload");
    setError("");
    setSuccess("");
    try {
      const doc = await request<{ id: string; status: string; filename: string }>("/api/documents/upload", token, {
        body: { knowledgeBaseId: selectedKbId, filename, content }
      });
      pushEvent(`文档上传成功：${doc.filename}，状态 ${doc.status}`);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function createSession(firstQuestion: string): Promise<ChatSession> {
    if (!token) throw new Error("请先登录");
    const title = titleFromQuestion(firstQuestion);
    const body = isAdmin ? { title, knowledgeBaseIds: selectedKbIds } : { title };
    const next = await request<ChatSession>("/api/chat/sessions", token, { body });
    setSessions((old) => [next, ...old.filter((item) => item.id !== next.id)]);
    setSession(next);
    if (user) rememberSession(user.id, next.id);
    pushEvent("会话已创建");
    return next;
  }

  function startNewSession() {
    if (busy !== "") return;
    setSession(null);
    setChatMessages([]);
    setQuestion("");
    setEvents([]);
    setEditingSessionId(null);
    setEditingSessionTitle("");
    setSessionHistoryOpen(false);
    if (user) rememberSession(user.id, null);
  }

  async function switchSession(next: ChatSession) {
    if (!token || busy !== "" || next.id === session?.id) {
      setSessionHistoryOpen(false);
      return;
    }
    setBusy("history");
    setError("");
    setSuccess("");
    try {
      const history = await request<ChatMessage[]>(`/api/chat/sessions/${next.id}/messages?rounds=${historyRounds}`, token);
      setSession(next);
      setChatMessages(keepLatestRounds(history));
      setQuestion("");
      setEvents([]);
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionHistoryOpen(false);
      if (user) rememberSession(user.id, next.id);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  function beginRenameSession(target: ChatSession) {
    if (busy !== "") return;
    setEditingSessionId(target.id);
    setEditingSessionTitle(target.title);
  }

  function cancelRenameSession() {
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }

  async function renameSession(target: ChatSession) {
    if (!token || busy !== "") return;
    const title = editingSessionTitle.trim();
    const length = Array.from(title).length;
    if (length < 1 || length > sessionTitleMaxLength) {
      setError(`会话标题长度必须为 1 至 ${sessionTitleMaxLength} 个字符`);
      return;
    }
    setBusy("rename");
    setError("");
    try {
      const updated = await request<ChatSession>(`/api/chat/sessions/${target.id}`, token, {
        method: "PATCH",
        body: { title }
      });
      setSessions((old) => old.map((item) => item.id === updated.id ? updated : item));
      setSession((current) => current?.id === updated.id ? updated : current);
      cancelRenameSession();
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setBusy("");
    }
  }

  async function ask() {
    const prompt = question.trim();
    if (!prompt) return;
    setBusy("ask");
    setError("");
    setSuccess("");
    const userTurn: ChatTurn = { id: `user-${Date.now()}`, role: "user", content: prompt };
    const assistantId = `assistant-${Date.now()}`;
    setChatMessages((old) => keepLatestRounds([...old, userTurn, { id: assistantId, role: "assistant", content: "" }]));
    setQuestion("");
    try {
      const activeSession = session ?? await createSession(prompt);
      const response = await fetch(`${apiBase}/api/chat/sessions/${activeSession.id}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: prompt })
      });
      if (!response.ok) throw new Error(await readableError(response));
      const reader = response.body?.getReader();
      if (!reader) throw new Error("浏览器没有返回可读取的流");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const parsed = parseSseBlock(part);
          if (!parsed) continue;
          if (parsed.event === "tool") pushEvent(`Agent tool: ${parsed.data}`);
          if (parsed.event === "plan" || parsed.event === "tool_result" || parsed.event === "citation") {
            pushEvent(summarizeAgentEvent(parsed.event, parsed.data));
          }
          if (parsed.event === "token") appendAssistantToken(assistantId, parsed.data);
          if (parsed.event === "error") {
            setError(parsed.data);
            appendAssistantToken(assistantId, parsed.data);
          }
          if (parsed.event === "done") pushEvent("回答完成");
        }
      }
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(message);
      appendAssistantToken(assistantId, message);
    } finally {
      setBusy("");
    }
  }

  function handleQuestionKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (busy === "" && question.trim()) void ask();
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <div className="brand"><Database size={24} /> Enterprise RAG</div>
          <h1>{authMode === "login" ? "企业知识库登录" : "注册普通用户"}</h1>
          {error && <div className="notice"><AlertCircle size={18} /> {error}</div>}
          {success && <div className="notice success"><ShieldCheck size={18} /> {success}</div>}
          <form className="auth-form" onSubmit={(event) => { event.preventDefault(); authMode === "login" ? void login() : void register(); }}>
            {authMode === "login" ? (
              <>
                <input value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} placeholder="用户名" />
                <input value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} placeholder="密码" type="password" />
              </>
            ) : (
              <>
                <input value={registerForm.username} onChange={(e) => setRegisterForm({ ...registerForm, username: e.target.value })} placeholder="用户名" />
                <input value={registerForm.password} onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })} placeholder="至少 6 位密码" type="password" />
              </>
            )}
            <button disabled={busy !== ""}>
              {busy === authMode ? <Loader2 size={18} className="spin" /> : authMode === "login" ? <KeyRound size={18} /> : <UserPlus size={18} />}
              {authMode === "login" ? "立即登录" : "立即注册"}
            </button>
            <div className="auth-tabs">
              <button type="button" className={authMode === "login" ? "auth-tab active" : "auth-tab"} onClick={() => { setAuthMode("login"); setError(""); setSuccess(""); }}>登录</button>
              <span>|</span>
              <button type="button" className={authMode === "register" ? "auth-tab active" : "auth-tab"} onClick={() => { setAuthMode("register"); setError(""); setSuccess(""); }}>注册</button>
            </div>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className={isAdmin ? "shell" : "user-shell"}>
      {isAdmin && (
        <aside className="sidebar">
          <div className="brand"><Database size={22} /> Enterprise RAG</div>
          <button className={adminPage === "upload" ? "" : "ghost-button"} onClick={() => setAdminPage("upload")}><FileUp size={18} /> 文件上传</button>
          <button className={adminPage === "users" ? "" : "ghost-button"} onClick={() => setAdminPage("users")}><Users size={18} /> 用户管理</button>
          <button className={adminPage === "roles" ? "" : "ghost-button"} onClick={() => setAdminPage("roles")}><ShieldCheck size={18} /> 角色权限</button>
          <button className={adminPage === "chat" ? "" : "ghost-button"} onClick={() => setAdminPage("chat")}><MessageCircle size={18} /> 系统问答</button>
          <button className="ghost-button" onClick={refreshAdminData} disabled={busy !== ""}><RefreshCw size={18} /> 刷新数据</button>
          <button className="ghost-button" onClick={logout}><LogOut size={18} /> 退出登录</button>
          <input ref={fileInputRef} className="file-input" type="file" accept=".pdf,.docx,.xlsx,.xls,.ods,.txt,.md,.markdown,.csv,.tsv,.json,.log,.yml,.yaml,.xml,.html,.htm" onChange={handleFileSelected} />
        </aside>
      )}
      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{isAdmin ? pageTitle(adminPage) : "企业知识库问答"}</h1>
            <p>{user.username} · {user.roles.join(", ")}</p>
          </div>
          <div className="top-actions">
            <span><ShieldCheck size={16} /> RBAC</span>
            {!isAdmin && <button className="ghost-button" onClick={logout}><LogOut size={18} /> 退出</button>}
          </div>
        </header>

        {error && <div className="notice"><AlertCircle size={18} /> {error}</div>}
        {success && <div className="notice success"><ShieldCheck size={18} /> {success}</div>}

        {isAdmin && adminPage === "upload" && (
          <div className="grid">
            <section className="panel">
              <h2>知识库</h2>
              <select value={selectedKbId} onChange={(e) => setSelectedKbId(e.target.value)}>
                {kbs.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
              </select>
              {kbs.map((kb) => (
                <article key={kb.id} className="item">
                  <strong>{kb.name}</strong>
                  <p>{kb.description}</p>
                </article>
              ))}
            </section>
            <section className="panel">
              <h2>文档内容</h2>
              <textarea value={docText} onChange={(e) => setDocText(e.target.value)} />
              <div className="inline-actions">
                <button onClick={() => fileInputRef.current?.click()} disabled={busy !== ""}>{busy === "upload" ? <Loader2 size={18} className="spin" /> : <FileUp size={18} />} 选择并上传文件</button>
                <button onClick={() => uploadDocument()} disabled={busy !== ""}>{busy === "upload" ? <Loader2 size={18} className="spin" /> : <FileUp size={18} />} 上传文本内容</button>
              </div>
            </section>
            <section className="panel wide">
              <h2>Agent 时间线</h2>
              {events.map((event, index) => <p className="event" key={`${event}-${index}`}>{event}</p>)}
              {events.length === 0 && <p className="empty">操作进度会显示在这里。</p>}
            </section>
          </div>
        )}

        {isAdmin && adminPage === "users" && (
          <section className="panel">
            <h2><Users size={18} /> 用户管理</h2>
            <div className="table-list">
              {users.map((target) => (
                <article className="user-row" key={target.id}>
                  <div>
                    <strong>{target.username}</strong>
                    <p>{target.disabled ? "已禁用" : "可用"} · {target.roles.join(", ") || "无角色"}</p>
                  </div>
                  <div className="check-list">
                    {roles.map((role) => (
                      <label key={role.id}>
                        <input type="checkbox" checked={target.roles.includes(role.name)} onChange={(e) => updateUserRoles(target, role.name, e.target.checked)} />
                        {role.name}
                      </label>
                    ))}
                  </div>
                  <button className="secondary-button" onClick={() => setUserDisabled(target, !target.disabled)}>{target.disabled ? "启用" : "禁用"}</button>
                  <input value={resetPasswords[target.id] ?? ""} onChange={(e) => setResetPasswords({ ...resetPasswords, [target.id]: e.target.value })} placeholder="新密码" type="password" />
                  <button className="secondary-button" onClick={() => resetPassword(target)}>重置密码</button>
                </article>
              ))}
            </div>
          </section>
        )}

        {isAdmin && adminPage === "roles" && (
          <section className="panel">
            <h2>角色权限</h2>
            <div className="inline-form">
              <input value={newRole.name} onChange={(e) => setNewRole({ ...newRole, name: e.target.value })} placeholder="角色名" />
              <input value={newRole.description} onChange={(e) => setNewRole({ ...newRole, description: e.target.value })} placeholder="角色描述" />
              <button onClick={createRole} disabled={busy !== ""}>创建角色</button>
            </div>
            <div className="role-grid">
              {roles.map((role) => (
                <article className="item" key={role.id}>
                  <strong>{role.name}</strong>
                  <p>{role.description || "无描述"}</p>
                  <div className="check-list">
                    {kbs.map((kb) => (
                      <label key={kb.id}>
                        <input type="checkbox" checked={role.knowledgeBaseIds.includes(kb.id)} onChange={(e) => updateRoleKb(role, kb.id, e.target.checked)} />
                        {kb.name}
                      </label>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {(!isAdmin || adminPage === "chat") && (
          <div className="chat-only">
            <div className="chat-layout">
              <SessionHistory
                sessions={sessions}
                activeSessionId={session?.id ?? null}
                open={sessionHistoryOpen}
                busy={busy}
                editingSessionId={editingSessionId}
                editingSessionTitle={editingSessionTitle}
                setEditingSessionTitle={setEditingSessionTitle}
                newSession={startNewSession}
                switchSession={switchSession}
                beginRename={beginRenameSession}
                cancelRename={cancelRenameSession}
                saveRename={renameSession}
              />
              <ChatPanel
                messages={chatMessages}
                busy={busy}
                question={question}
                sessionTitle={session?.title ?? "新对话"}
                setQuestion={setQuestion}
                ask={ask}
                onKeyDown={handleQuestionKeyDown}
                toggleHistory={() => setSessionHistoryOpen((open) => !open)}
              />
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function pageTitle(page: AdminPage): string {
  if (page === "upload") return "文件上传";
  if (page === "users") return "用户管理";
  if (page === "roles") return "角色权限";
  return "系统问答";
}

function SessionHistory(props: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  open: boolean;
  busy: string;
  editingSessionId: string | null;
  editingSessionTitle: string;
  setEditingSessionTitle: (value: string) => void;
  newSession: () => void;
  switchSession: (session: ChatSession) => Promise<void>;
  beginRename: (session: ChatSession) => void;
  cancelRename: () => void;
  saveRename: (session: ChatSession) => Promise<void>;
}) {
  const disabled = props.busy !== "";
  return (
    <aside className={`session-history${props.open ? " open" : ""}`} aria-label="历史会话">
      <header className="session-history-header">
        <h2><History size={18} /> 历史会话</h2>
        <button className="icon-button" onClick={props.newSession} disabled={disabled} title="新对话" aria-label="新对话">
          <Plus size={18} />
        </button>
      </header>
      <div className="session-list">
        {props.sessions.length === 0 && <p className="empty">暂无历史会话</p>}
        {props.sessions.map((item) => {
          const editing = props.editingSessionId === item.id;
          return (
            <div className={`session-row${props.activeSessionId === item.id ? " active" : ""}`} key={item.id}>
              {editing ? (
                <div className="session-edit">
                  <input
                    autoFocus
                    maxLength={sessionTitleMaxLength}
                    value={props.editingSessionTitle}
                    onChange={(event) => props.setEditingSessionTitle(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.nativeEvent.isComposing) return;
                      if (event.key === "Enter") void props.saveRename(item);
                      if (event.key === "Escape") props.cancelRename();
                    }}
                    aria-label="会话标题"
                  />
                  <button className="icon-button" onClick={() => void props.saveRename(item)} disabled={disabled} title="保存标题" aria-label="保存标题"><Check size={16} /></button>
                  <button className="icon-button subtle" onClick={props.cancelRename} disabled={disabled} title="取消重命名" aria-label="取消重命名"><X size={16} /></button>
                </div>
              ) : (
                <>
                  <button className="session-select" onClick={() => void props.switchSession(item)} disabled={disabled} title={item.title}>
                    <strong>{item.title}</strong>
                    <span>{formatSessionTime(item.createdAt)}</span>
                  </button>
                  <button className="icon-button subtle session-rename" onClick={() => props.beginRename(item)} disabled={disabled} title="重命名会话" aria-label={`重命名 ${item.title}`}>
                    <Pencil size={15} />
                  </button>
                </>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function ChatPanel(props: {
  messages: ChatTurn[];
  busy: string;
  question: string;
  sessionTitle: string;
  setQuestion: (value: string) => void;
  ask: () => Promise<void>;
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  toggleHistory: () => void;
}) {
  return (
    <section className="panel chat">
      <header className="chat-header">
        <div>
          <h2><Bot size={18} /> RAG Chat</h2>
          <p>{props.sessionTitle}</p>
        </div>
        <button className="icon-button history-toggle" onClick={props.toggleHistory} disabled={props.busy !== ""} title="历史会话" aria-label="历史会话">
          <History size={18} />
        </button>
      </header>
      <div className="conversation">
        {props.messages.length === 0 && <p className="empty">输入问题后开始问答。系统会自动使用你有权限访问的知识库。</p>}
        {props.messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <span>{message.role === "user" ? "用户" : "系统"}</span>
            <p>{message.content || "正在生成回答..."}</p>
          </article>
        ))}
      </div>
      <div className="composer">
        <input value={props.question} onChange={(e) => props.setQuestion(e.target.value)} onKeyDown={props.onKeyDown} placeholder="输入问题，按 Enter 发送" />
        <button onClick={props.ask} disabled={props.busy !== ""}>{props.busy === "ask" ? <Loader2 size={18} className="spin" /> : <Send size={18} />}</button>
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
