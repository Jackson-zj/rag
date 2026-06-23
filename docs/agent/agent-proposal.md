# Enterprise RAG Agent Proposal

## Goal

Upgrade the current Enterprise RAG MVP into a LangGraph-based Agent while preserving the existing frontend chat entrypoint, Java authentication/RBAC boundary, Spring SSE aggregation, and FastAPI RAG retrieval behavior.

## Non-Goals

- Do not connect to external business databases in this phase.
- Do not allow SQL write operations.
- Do not replace the existing Java authentication or RBAC model.
- Do not redesign the frontend as a new product surface.

## Users And Runtime Context

- Admin and normal users continue using the same React UI.
- Java remains the trusted boundary for auth, session ownership, and knowledge-base scope.
- FastAPI becomes the Agent runtime for routing, tool execution, model calls, and answer composition.
- PostgreSQL/pgvector remains the local persistence and vector backend when configured.

## Functional Requirements

- Wrap the existing RAG retrieval path as a `rag_search` tool.
- Add a read-only `sql_query` tool for this project's PostgreSQL metadata.
- Route user questions with LangGraph into RAG, SQL, mixed, or direct response paths.
- Stream `tool`, `tool_result`, `citation`, `token`, `error`, and `done` events.
- Keep `/api/chat/sessions/{id}/stream`, `/ai/chat/stream`, and `/ai/agent/run` compatible with existing callers.

## Inputs And Outputs

- Input: `user_id`, `session_id`, `question`, backend-approved `knowledge_base_ids`.
- Output: final answer, RAG citations, SQL summary citations, tool calls, tool results, and route name.
- Stream output: incremental SSE events for tool starts/results, citations, tokens, and completion.

## Dependencies And Constraints

- Use existing `langgraph==1.1.6`.
- Use `AGENT_SQL_DATABASE_URL`, defaulting to `VECTOR_DATABASE_URL`.
- SQL tool must only execute validated single-statement `SELECT` queries against a whitelist.
- SQL queries must have a maximum limit of 50 rows and a short timeout.

## Success Criteria

- Existing RAG behavior and tests continue to work.
- RAG questions route to `rag_search`.
- Metadata questions route to `sql_query`.
- Mixed metadata/content questions can call both tools.
- Java and frontend handle new stream events without breaking old token streaming.

## Acceptance Checks

- AI unit tests cover routing, SQL safety, and extended response shape.
- Java tests cover SSE passthrough for new events.
- Frontend build passes and displays concise tool trail events.
- Documentation describes Agent architecture and local configuration.

## Assumptions

- SQL MVP queries only project metadata tables and hides sensitive columns.
- The frontend displays concise tool summaries rather than raw SQL result tables.
- Java continues to persist only final user/assistant chat messages.

## Open Questions

- External business database support is intentionally deferred.
- Tool-level audit persistence can be added after the MVP stream contract is stable.
