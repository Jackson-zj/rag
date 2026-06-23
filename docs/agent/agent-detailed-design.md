# Enterprise RAG Agent Detailed Design

## File Structure

- `ai-service/app/schemas.py`: Pydantic models and `AgentState`.
- `ai-service/app/agent.py`: LangGraph graph, route rules, SQL registry, SQL validation, tool wrappers, response builder, stream generator.
- `ai-service/app/main.py`: FastAPI routes, existing RAG/index/search/answer functions, compatibility exports.
- `backend-java/src/main/java/com/enterprise/rag/AiClient.java`: SSE passthrough for `tool_result` and `citation`.
- `frontend/src/main.tsx`: parse and display new tool/citation events in the existing timeline.

## Public Contracts

`/ai/agent/run` returns:

- `answer`: final answer text.
- `citations`: RAG citations plus SQL summary citations.
- `tool_calls`: ordered tool calls.
- `tool_results`: ordered status summaries with elapsed time.
- `route`: `rag`, `sql`, `mixed`, or `direct`.

`/ai/chat/stream` emits:

- `tool`: tool name.
- `tool_result`: JSON summary with status and elapsed time.
- `citation`: JSON RAG or SQL citation summary.
- `token`: final answer content.
- `error`, `done`: compatibility events.

## Agent Control Flow

- `load_memory`: reads recent in-memory conversation history.
- `route_intent`: deterministic rule router for metadata/content/direct questions.
- `sql_tool`: runs safe project metadata queries.
- `rag_tool`: calls existing `rag_search`.
- `compose_answer`: uses SQL summary, RAG answer generation, or mixed answer composition.
- `persist_memory`: appends user and assistant messages to AI-service memory.

## SQL Tool

- Config: `AGENT_SQL_DATABASE_URL`, default `VECTOR_DATABASE_URL`.
- Whitelist: `knowledge_bases`, `documents`, `chat_sessions`, `chat_messages`.
- Sensitive exclusions: no password hashes, token data, or full chat message content.
- Validation:
  - starts with `SELECT`;
  - no semicolon or multi-statement execution;
  - no write/DDL keywords;
  - every `FROM`/`JOIN` table is whitelisted;
  - `LIMIT` is capped at 50;
  - statement timeout is 5 seconds.

## Error Handling

- SQL connection missing returns a clear SQL tool summary instead of failing the whole Agent run.
- SQL validation/execution errors become `tool_result` status `error`.
- LangGraph import/compile failures fall back to the same manual node sequence.
- Existing model call failures still fall back to deterministic retrieval answers.

## Compatibility

- Existing route names and request payloads remain valid.
- Existing tests importing from `app.main` should continue working through re-exports/imports.
- Java persists only final assistant text, not intermediate tool events.

## Implementation Risks

- Circular imports between `agent.py` and `main.py` are avoided by importing `main` inside functions.
- Streamed model token support is simplified for Agent output in this pass to keep mixed SQL/RAG composition deterministic.
- Frontend JSON parsing for `tool_result`/`citation` must tolerate plain strings.
