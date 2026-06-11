# API Contract

## Business API

- `POST /api/auth/login`: returns a bearer token and user roles.
- `GET /api/knowledge-bases`: returns knowledge bases visible to the current user.
- `POST /api/knowledge-bases`: creates a knowledge base owned by the current user.
- `POST /api/documents/upload`: stores document metadata and dispatches indexing.
- `GET /api/documents/{id}`: returns document status after permission check.
- `POST /api/chat/sessions`: creates a chat session scoped to visible knowledge bases.
- `GET /api/chat/sessions/{id}/messages`: lists session messages.
- `POST /api/chat/sessions/{id}/stream`: streams assistant tokens and tool events.

## AI API

- `POST /ai/documents/parse`: parses and chunks raw document text.
- `POST /ai/documents/index`: chunks and indexes a document.
- `POST /ai/rag/search`: permission-aware vector retrieval.
- `POST /ai/chat/stream`: streams agent output.
- `POST /ai/agent/run`: runs the RAG agent and returns final answer text.

