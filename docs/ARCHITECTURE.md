# Architecture Notes

## Request Flow

1. A user registers or logs in through Spring Boot.
2. Spring Boot stores users, BCrypt password hashes, roles, role permissions, knowledge bases, documents, chat sessions, and messages in PostgreSQL.
3. The user receives a demo bearer token. Tokens remain in Java memory, but every protected request reloads the user from PostgreSQL so disabled users are rejected immediately.
4. Admins can upload documents and manage users, roles, and role-to-knowledge-base permissions.
5. Normal users only use the chat UI. They do not upload documents, view document lists, or choose knowledge bases manually.
6. Spring Boot calculates the current user's visible `knowledge_base_ids` from their roles.
7. Chat requests sent to FastAPI include `user_id`, `session_id`, `question`, and the backend-approved `knowledge_base_ids`.
8. FastAPI filters retrieval primarily by `knowledge_base_ids`. Empty `allowed_user_ids` means there is no extra legacy user ACL beyond the KB scope.
9. Spring Boot streams FastAPI SSE events to the frontend and persists user/assistant messages.

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

pgvector stores RAG chunks in `document_chunks`.

## Permission Model

- Permissions are knowledge-base scoped.
- A user's visible knowledge bases are the union of all knowledge bases granted to that user's roles.
- `ADMIN` users can access every knowledge base and use admin-only APIs.
- Normal users cannot upload documents or access admin APIs.
- Role permission changes do not require re-indexing documents because AI retrieval uses request-time `knowledge_base_ids`.

## Extension Points

- Persist bearer tokens or replace them with JWT/session storage.
- Replace deterministic embeddings with Qwen/OpenAI/DeepSeek embedding APIs.
- Add database integration tests with Testcontainers.
- Add tenant isolation by introducing `tenant_id` on users, roles, knowledge bases, documents, and chunks.
- Add Kubernetes manifests or Helm chart for production-style deployment.
