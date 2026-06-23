# API Contract

## Business API

All protected APIs use `Authorization: Bearer <token>`.

### Authentication

- `POST /api/auth/register`: registers a normal user, assigns the default `USER` role, and returns a bearer token plus user profile.
- `POST /api/auth/login`: validates a BCrypt password hash and returns a bearer token plus user profile.
- `GET /api/me`: returns the current user, roles, disabled flag, and accessible knowledge base IDs.

### Admin User And Role Management

Admin-only APIs:

- `GET /api/admin/users`: lists users with roles and accessible knowledge base IDs.
- `PUT /api/admin/users/{id}/roles`: replaces a user's role assignments.
- `PUT /api/admin/users/{id}/disabled`: enables or disables a user. Disabled users cannot log in or continue using existing tokens.
- `PUT /api/admin/users/{id}/password`: resets a user's password with BCrypt hashing.
- `GET /api/admin/roles`: lists roles and their knowledge base permissions.
- `POST /api/admin/roles`: creates a role with a name and description.
- `PUT /api/admin/roles/{id}/knowledge-bases`: replaces the knowledge bases accessible to a role.

### Knowledge Bases And Documents

- `GET /api/knowledge-bases`: returns all knowledge bases for admins, or only role-authorized knowledge bases for normal users.
- `POST /api/knowledge-bases`: admin-only; creates a knowledge base and grants the admin role access.
- `POST /api/documents/upload`: admin-only; stores document metadata and calls the AI service for indexing.
- `GET /api/documents/{id}`: returns document status after knowledge-base permission checks.

### Chat

- `POST /api/chat/sessions`: creates a chat session. If `knowledgeBaseIds` is omitted, the backend uses all knowledge bases visible to the current user.
- `GET /api/chat/sessions`: lists the current user's chat sessions.
- `PATCH /api/chat/sessions/{id}`: renames the current user's session with `{"title":"..."}`. Titles are trimmed and must contain 1 to 60 characters.
- `GET /api/chat/sessions/{id}/messages`: lists messages for the current user's session.
- `GET /api/chat/sessions/{id}/messages?rounds=10`: lists the latest 10 user question rounds and their following assistant messages for the current user's session, returned in chronological order.
- `POST /api/chat/sessions/{id}/stream`: streams assistant tokens and tool events, and persists user/assistant messages.

## AI API

- `POST /ai/documents/parse`: parses and chunks raw document text.
- `POST /ai/documents/index`: chunks and indexes a document.
- `POST /ai/rag/search`: permission-aware vector retrieval. The primary permission boundary is `knowledge_base_ids`; `allowed_user_ids` is retained only as a legacy ACL compatibility layer.
- `POST /ai/chat/stream`: streams LangGraph Agent output.
  - `tool`: tool name when a tool starts.
  - `tool_result`: JSON summary with `name`, `status`, `summary`, `elapsed_ms`, and optional `data`.
  - `citation`: JSON citation summary for RAG chunks or SQL summaries.
  - `token`: final answer text token. Java only appends these events to the persisted assistant answer.
  - `error`: stream error.
  - `done`: stream completion marker.
- `POST /ai/agent/run`: runs the Agent and returns `answer`, `citations`, `tool_calls`, `tool_results`, and `route`.

### Agent Tools

- `conversation_memory`: loads recent session history from AI-service memory.
- `rag_search`: wraps the existing permission-aware RAG retrieval path.
- `sql_query`: read-only project metadata and employee-data SQL tool. It uses `AGENT_SQL_DATABASE_URL` or falls back to `VECTOR_DATABASE_URL`, only allows single-statement `SELECT` queries, only queries whitelisted tables/views, caps result size to 50 rows, and excludes sensitive fields.
  - The model produces a validated QueryPlan JSON object, never SQL. A generic compiler resolves registered dimensions, metrics, filters, grouping, ordering, and limit into parameterized SQL.
  - Dates, explicit usernames, and registered enum aliases are extracted before model planning and supplied as locked constraints; model output cannot remove or widen those filters.
  - Semantic configuration covers `attendance`, `employee_worklog`, `knowledge_base`, `document`, `chat_session`, and `chat_message`.
  - Invalid plans receive one sanitized repair attempt; missing/unavailable models use a rule-generated QueryPlan rather than legacy SQL templates.
  - Employee attendance queries read `agent_attendance_records`.
  - Attendance aliases `缺卡`, `未打卡`, `漏打卡`, and `忘记打卡` are locked to `ABSENT`; date ranges accept `到`, `至`, hyphen/dash, and tilde separators.
  - Daily work-log queries read `agent_employee_work_logs`.
  - The tool verifies `ADMIN` from PostgreSQL using the request's authenticated `user_id`; administrators can query all employees and normal users are restricted to themselves.
  - SQL citations and tool results expose only domain, planner, summary, row count, and scope. QueryPlan, SQL, and raw rows remain internal.
- `final_answer`: summarizes tool results into the final assistant response.
