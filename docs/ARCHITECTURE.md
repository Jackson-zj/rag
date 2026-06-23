# Architecture Notes

## Request Flow

1. A user registers or logs in through Spring Boot.
2. Spring Boot stores users, BCrypt password hashes, roles, role permissions, knowledge bases, documents, chat sessions, and messages in PostgreSQL.
3. The user receives a demo bearer token. Tokens remain in Java memory, but every protected request reloads the user from PostgreSQL so disabled users are rejected immediately.
4. After login, the frontend loads the current user's latest chat session and requests `messages?rounds=10`, so the chat panel resumes with the latest 10 user question rounds instead of an empty window.
5. Admins can upload documents and manage users, roles, and role-to-knowledge-base permissions.
6. Normal users only use the chat UI. They do not upload documents, view document lists, or choose knowledge bases manually.
7. Spring Boot calculates the current user's visible `knowledge_base_ids` from their roles.
8. Chat requests sent to FastAPI include `user_id`, `session_id`, `question`, and the backend-approved `knowledge_base_ids`.
9. FastAPI runs a LangGraph Agent. Structured questions traverse semantic retrieval, deterministic entity extraction, QueryPlan planning, locked-constraint merge/validation, policy injection, SQL compilation, execution, and answer composition; RAG and mixed routes remain available.
10. FastAPI filters retrieval primarily by `knowledge_base_ids`. Empty `allowed_user_ids` means there is no extra legacy user ACL beyond the KB scope.
11. Spring Boot streams FastAPI SSE events to the frontend and persists user/assistant messages. Tool events and citations are displayed in the UI timeline but are not appended to the saved assistant answer.

## Storage

PostgreSQL stores business data:

- `users`
- `roles`
- `user_roles`
- `role_knowledge_bases`
- `knowledge_bases`
- `documents`
- `chat_sessions`
- `chat_session_knowledge_bases`
- `chat_messages`
- `attendance_records`
- `employee_work_logs`

pgvector stores RAG chunks in `document_chunks`.
The Agent reads employee and chat metadata through safe ownership views: `agent_attendance_records`, `agent_employee_work_logs`, `agent_chat_sessions`, and `agent_chat_messages`. Message content and authentication fields are not exposed.

## Agent Tools

- `conversation_memory`: recent AI-service chat memory.
- `rag_search`: permission-aware vector retrieval over `document_chunks`.
- `sql_query`: hybrid Text2SQL tool driven by the versioned semantic registry. Code extracts date, username, and enum constraints before planning, sends those locked filters to the model, merges them authoritatively into QueryPlan, injects policy, compiles parameterized SQL, revalidates the `SELECT`, and keeps QueryPlan/SQL/rows out of SSE metadata.
- `final_answer`: composes the final response from tool evidence.

## Permission Model

- Permissions are knowledge-base scoped.
- A user's visible knowledge bases are the union of all knowledge bases granted to that user's roles.
- `ADMIN` users can access every knowledge base and use admin-only APIs.
- Normal users cannot upload documents or access admin APIs.
- Chat history is user-scoped: session lists and message reads are filtered through the current authenticated user, and users cannot read another user's session messages.
- Employee SQL scope is database-verified: `ADMIN` users can query all attendance/work-log rows, while other users receive a mandatory `user_id` predicate and cannot target another employee.
- Knowledge-base plans receive the Java-approved `knowledge_base_ids`; session and message plans receive the current user's ID unless the database confirms `ADMIN`.
- Role permission changes do not require re-indexing documents because AI retrieval uses request-time `knowledge_base_ids`.

## Extension Points

- Persist bearer tokens or replace them with JWT/session storage.
- Replace deterministic embeddings with Qwen/OpenAI/DeepSeek embedding APIs.
- Add database integration tests with Testcontainers.
- Add tenant isolation by introducing `tenant_id` on users, roles, knowledge bases, documents, and chunks.
- Add Kubernetes manifests or Helm chart for production-style deployment.
