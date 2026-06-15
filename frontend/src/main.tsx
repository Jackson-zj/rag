import React, { useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertCircle, Bot, Database, FileUp, KeyRound, Loader2, MessagesSquare, Send, ShieldCheck } from "lucide-react";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import "./styles.css";

type User = { id: string; username: string; roles: string[]; knowledgeBaseIds: string[] };
type KnowledgeBase = { id: string; name: string; description: string };
type ChatSession = { id: string; title: string; knowledgeBaseIds: string[] };
type AuthContext = { token: string; user: User; kbs: KnowledgeBase[] };

const apiBase = import.meta.env.VITE_API_BASE ?? "";
const pdfWorkerSrc = `${pdfWorkerUrl}?v=module-mime`;
const defaultQuestion = "员工报销需要注意什么？";
const defaultDocText = "员工报销需要在费用发生后30天内提交发票、付款凭证和审批单。差旅费用需关联出差申请。";

async function api<T>(path: string, token: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!response.ok) {
    throw new Error(await readableError(response));
  }
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

function fileExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function readableRatio(text: string): number {
  if (!text) return 0;
  const readable = text.match(/[\p{L}\p{N}\p{Script=Han}，。！？；：、（）《》“”'"\-.,!?;:()[\]\s]/gu)?.length ?? 0;
  return readable / text.length;
}

function isReadableExtract(text: string): boolean {
  const clean = text.trim();
  if (!clean) return false;
  const replacementCount = (clean.match(/\uFFFD/g) ?? []).length;
  const controlCount = (clean.match(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g) ?? []).length;
  if (replacementCount + controlCount > Math.max(3, clean.length * 0.08)) return false;
  if (/(?:QE[\u0000-\u001F]?){3,}/.test(clean)) return false;
  return readableRatio(clean) >= 0.55;
}

function sanitizeExtractedText(text: string): string {
  return text
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, " ")
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter((line) => !/^Page\s+\d+$/i.test(line))
    .filter((line) => !/^[—\-–-]?\s*\d+\s*[—\-–-]?$/.test(line))
    .filter((line) => !/^第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?$/.test(line))
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
  const buffer = await file.arrayBuffer();
  const result = await mammoth.extractRawText({ arrayBuffer: buffer });
  return sanitizeExtractedText(result.value);
}

async function extractSpreadsheetText(file: File): Promise<string> {
  const XLSX = await import("xlsx");
  const buffer = await file.arrayBuffer();
  const workbook = XLSX.read(buffer, { type: "array" });
  return workbook.SheetNames.map((sheetName) => {
    const sheet = workbook.Sheets[sheetName];
    const csv = XLSX.utils.sheet_to_csv(sheet).trim();
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
  throw new Error(`暂不支持 ${extension || "未知"} 格式，请上传 PDF、Word(docx)、Excel、Markdown 或文本文件。`);
}

function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [question, setQuestion] = useState(defaultQuestion);
  const [answer, setAnswer] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [docText, setDocText] = useState(defaultDocText);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"login" | "upload" | "session" | "ask" | "">("");

  const selectedKbIds = useMemo(() => kbs.map((kb) => kb.id), [kbs]);

  function pushEvent(message: string) {
    setEvents((old) => [message, ...old].slice(0, 12));
  }

  async function ensureLogin(): Promise<AuthContext> {
    if (token && user && kbs.length > 0) {
      return { token, user, kbs };
    }
    const response = await fetch(`${apiBase}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "admin", password: "admin123" })
    });
    if (!response.ok) throw new Error(await readableError(response));
    const data = (await response.json()) as { token: string; user: User };
    const list = await api<KnowledgeBase[]>("/api/knowledge-bases", data.token);
    setToken(data.token);
    setUser(data.user);
    setKbs(list);
    pushEvent("登录成功，知识库已加载");
    return { token: data.token, user: data.user, kbs: list };
  }

  async function login() {
    setBusy("login");
    setError("");
    try {
      await ensureLogin();
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(`登录失败：${message}`);
      pushEvent(`登录失败：${message}`);
    } finally {
      setBusy("");
    }
  }

  function openFilePicker() {
    setError("");
    fileInputRef.current?.click();
  }

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      pushEvent(`开始解析文件：${file.name}`);
      const content = await extractDocumentText(file);
      if (!content.trim()) throw new Error("没有从文件中提取到可索引文本，扫描版 PDF 需要先 OCR。");
      setDocText(content);
      await uploadDocument(file.name, content);
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(`解析失败：${message}`);
      pushEvent(`解析失败：${message}`);
      setBusy("");
    }
  }

  async function uploadDocument(filename = "employee-policy.txt", content = docText) {
    setBusy("upload");
    setError("");
    try {
      const auth = await ensureLogin();
      const kb = auth.kbs[0];
      if (!kb) throw new Error("没有可用知识库");
      if (!content.trim()) throw new Error("文件内容为空，无法上传");
      pushEvent(`开始上传：${filename}`);
      const doc = await api<{ id: string; status: string; filename: string }>("/api/documents/upload", auth.token, {
        knowledgeBaseId: kb.id,
        filename,
        content
      });
      pushEvent(`文档上传成功：${doc.filename}，状态 ${doc.status}`);
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(`上传失败：${message}`);
      pushEvent(`上传失败：${message}`);
    } finally {
      setBusy("");
    }
  }

  async function createSessionWith(authToken = token, kbList = kbs): Promise<ChatSession> {
    const ids = kbList.map((kb) => kb.id);
    if (!authToken) throw new Error("请先登录");
    if (ids.length === 0) throw new Error("没有可用于会话的知识库");
    const next = await api<ChatSession>("/api/chat/sessions", authToken, {
      title: "企业制度问答",
      knowledgeBaseIds: ids
    });
    setSession(next);
    setAnswer("");
    pushEvent("会话创建成功，可以开始提问");
    return next;
  }

  async function createSession() {
    setBusy("session");
    setError("");
    try {
      const auth = await ensureLogin();
      await createSessionWith(auth.token, auth.kbs);
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(`新建会话失败：${message}`);
      pushEvent(`新建会话失败：${message}`);
    } finally {
      setBusy("");
    }
  }

  async function ask() {
    setBusy("ask");
    setError("");
    setAnswer("");
    try {
      const auth = await ensureLogin();
      const activeSession = session ?? await createSessionWith(auth.token, auth.kbs);
      if (!question.trim()) throw new Error("请输入问题");
      pushEvent("开始流式问答");
      const response = await fetch(`${apiBase}/api/chat/sessions/${activeSession.id}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
        body: JSON.stringify({ question })
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
          if (parsed.event === "tool") {
            pushEvent(`Agent 调用工具：${parsed.data}`);
          }
          if (parsed.event === "token") {
            setAnswer((old) => old + parsed.data);
          }
          if (parsed.event === "error") {
            setError(parsed.data);
            setAnswer(parsed.data);
            pushEvent(parsed.data);
          }
          if (parsed.event === "done") {
            pushEvent("回答完成");
          }
        }
      }
    } catch (ex) {
      const message = ex instanceof Error ? ex.message : String(ex);
      setError(`问答失败：${message}`);
      setAnswer(`问答失败：${message}`);
      pushEvent(`问答失败：${message}`);
    } finally {
      setBusy("");
    }
  }

  function handleQuestionKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (busy === "" && question.trim()) {
      void ask();
    }
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><Database size={22} /> Enterprise RAG</div>
        <button onClick={login} disabled={busy !== ""}>{busy === "login" ? <Loader2 size={18} className="spin" /> : <KeyRound size={18} />} 登录 demo</button>
        <button onClick={openFilePicker} disabled={busy !== ""}>{busy === "upload" ? <Loader2 size={18} className="spin" /> : <FileUp size={18} />} 选择并上传文件</button>
        <button onClick={() => uploadDocument()} disabled={busy !== ""}>{busy === "upload" ? <Loader2 size={18} className="spin" /> : <FileUp size={18} />} 上传文本内容</button>
        <button onClick={createSession} disabled={busy !== ""}>{busy === "session" ? <Loader2 size={18} className="spin" /> : <MessagesSquare size={18} />} 新建会话</button>
        <input
          ref={fileInputRef}
          className="file-input"
          type="file"
          accept=".pdf,.docx,.xlsx,.xls,.ods,.txt,.md,.markdown,.csv,.tsv,.json,.log,.yml,.yaml,.xml,.html,.htm"
          onChange={handleFileSelected}
        />
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>智能知识库工作台</h1>
            <p>{user ? `${user.username} · ${user.roles.join(", ")}` : "等待登录"}</p>
          </div>
          <span><ShieldCheck size={16} /> RBAC enabled</span>
        </header>

        {error && <div className="notice"><AlertCircle size={18} /> {error}</div>}

        <div className="grid">
          <section className="panel">
            <h2>知识库</h2>
            {kbs.map((kb) => (
              <article key={kb.id} className="item">
                <strong>{kb.name}</strong>
                <p>{kb.description}</p>
              </article>
            ))}
            {kbs.length === 0 && <p className="empty">点击登录或上传后会自动加载知识库。</p>}
          </section>

          <section className="panel">
            <h2>文档内容</h2>
            <textarea value={docText} onChange={(e) => setDocText(e.target.value)} />
          </section>

          <section className="panel chat">
            <h2><Bot size={18} /> RAG Chat</h2>
            <div className="answer">{answer || "上传文档后输入问题。未登录或未创建会话时，系统会自动补齐。"}</div>
            <div className="composer">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={handleQuestionKeyDown} />
              <button onClick={ask} disabled={busy !== ""}>{busy === "ask" ? <Loader2 size={18} className="spin" /> : <Send size={18} />}</button>
            </div>
          </section>

          <section className="panel">
            <h2>Agent Timeline</h2>
            {events.map((event, index) => <p className="event" key={`${event}-${index}`}>{event}</p>)}
            {events.length === 0 && <p className="empty">操作进度会显示在这里。</p>}
          </section>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
