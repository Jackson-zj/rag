# Architecture Notes

## Request Flow

1. User logs in through Spring Boot and receives a demo bearer token.
2. User uploads a document into a knowledge base.
3. Spring Boot validates RBAC and dispatches an indexing task to RabbitMQ.
4. FastAPI indexes chunks using deterministic local embeddings by default.
5. Chat requests include `user_id` and `knowledge_base_ids`.
6. FastAPI filters chunks by knowledge base and user ACL before ranking.
7. Agent flow calls the RAG search tool, writes short-term memory, and returns an answer.
8. Spring Boot streams tokens to the frontend as SSE events.

## Extension Points

- Replace deterministic embeddings with Qwen/OpenAI/DeepSeek embedding APIs.
- Persist AI chunks to PostgreSQL `document_chunks` with pgvector similarity search.
- Add reranking after vector recall.
- Add tenant isolation by introducing `tenant_id` on users, knowledge bases, documents, and chunks.
- Add Kubernetes manifests or Helm chart for production-style deployment.

