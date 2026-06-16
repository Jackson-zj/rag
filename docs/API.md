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
- `GET /api/chat/sessions/{id}/messages`: lists messages for the current user's session. Optional `rounds` limits the response to the latest N user question rounds and their following messages.
- `POST /api/chat/sessions/{id}/stream`: streams assistant tokens and tool events, and persists user/assistant messages.

## AI API

- `POST /ai/documents/parse`: parses and chunks raw document text.
- `POST /ai/documents/index`: chunks and indexes a document.
- `POST /ai/rag/search`: permission-aware vector retrieval. The primary permission boundary is `knowledge_base_ids`; `allowed_user_ids` is retained only as a legacy ACL compatibility layer.
- `POST /ai/chat/stream`: streams agent output.
- `POST /ai/agent/run`: runs the RAG agent and returns final answer text.
