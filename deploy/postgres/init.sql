CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  disabled BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  system_role BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS role_knowledge_bases (
  role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, knowledge_base_id)
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
  filename TEXT NOT NULL,
  status TEXT NOT NULL,
  content_hash TEXT,
  chunk_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
  filename TEXT NOT NULL DEFAULT '',
  position INT NOT NULL,
  content TEXT NOT NULL,
  embedding vector(64),
  allowed_user_ids TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_session_knowledge_bases (
  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
  PRIMARY KEY (session_id, knowledge_base_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attendance_records (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  attendance_date DATE NOT NULL,
  clock_in TIME,
  clock_out TIME,
  status TEXT NOT NULL CHECK (status IN ('NORMAL', 'LATE', 'EARLY_LEAVE', 'ABSENT', 'LEAVE')),
  work_minutes INT NOT NULL DEFAULT 0 CHECK (work_minutes >= 0),
  overtime_minutes INT NOT NULL DEFAULT 0 CHECK (overtime_minutes >= 0),
  remark TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, attendance_date)
);

CREATE TABLE IF NOT EXISTS employee_work_logs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  log_date DATE NOT NULL,
  project_name TEXT NOT NULL,
  work_summary TEXT NOT NULL,
  work_hours NUMERIC(4, 1) NOT NULL CHECK (work_hours >= 0 AND work_hours <= 24),
  completion_status TEXT NOT NULL CHECK (completion_status IN ('COMPLETED', 'IN_PROGRESS', 'BLOCKED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, log_date)
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE roles ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE roles ADD COLUMN IF NOT EXISTS system_role BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE roles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INT NOT NULL DEFAULT 0;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS filename TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_kb_content_hash ON documents (knowledge_base_id, content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_document_chunks_acl ON document_chunks USING gin (allowed_user_ids);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles (role_id);
CREATE INDEX IF NOT EXISTS idx_role_kbs_kb ON role_knowledge_bases (knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance_records (user_id, attendance_date DESC);
CREATE INDEX IF NOT EXISTS idx_work_logs_user_date ON employee_work_logs (user_id, log_date DESC);

CREATE OR REPLACE VIEW agent_attendance_records AS
SELECT
  attendance.id,
  attendance.user_id,
  users.username,
  attendance.attendance_date,
  attendance.clock_in,
  attendance.clock_out,
  attendance.status,
  attendance.work_minutes,
  attendance.overtime_minutes,
  attendance.remark
FROM attendance_records attendance
JOIN users ON users.id = attendance.user_id;

CREATE OR REPLACE VIEW agent_employee_work_logs AS
SELECT
  logs.id,
  logs.user_id,
  users.username,
  logs.log_date,
  logs.project_name,
  logs.work_summary,
  logs.work_hours,
  logs.completion_status
FROM employee_work_logs logs
JOIN users ON users.id = logs.user_id;

CREATE OR REPLACE VIEW agent_chat_sessions AS
SELECT
  sessions.id,
  sessions.user_id,
  users.username,
  sessions.title,
  sessions.created_at
FROM chat_sessions sessions
JOIN users ON users.id = sessions.user_id;

CREATE OR REPLACE VIEW agent_chat_messages AS
SELECT
  messages.id,
  messages.session_id,
  sessions.user_id,
  users.username,
  messages.role,
  messages.created_at
FROM chat_messages messages
JOIN chat_sessions sessions ON sessions.id = messages.session_id
JOIN users ON users.id = sessions.user_id;
