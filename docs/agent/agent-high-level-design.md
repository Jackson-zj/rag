# Enterprise RAG Agent High-Level Design

## Architecture Overview

The system keeps the existing three-service shape:

- React frontend renders chat, admin tools, and a concise Agent timeline.
- Spring Boot authenticates users, calculates RBAC knowledge-base scope, owns sessions, proxies SSE, and persists final chat messages.
- FastAPI owns Agent routing, tool execution, citations, model fallback, and streamed answer generation.

## Module Boundaries

- `ai-service/app/main.py` remains the FastAPI entrypoint and preserves legacy exported functions used by tests.
- `ai-service/app/schemas.py` defines shared request, response, tool, and Agent state contracts.
- `ai-service/app/agent.py` contains LangGraph nodes, routing, SQL safety, tool execution, response assembly, and stream event generation.
- Java `AiClient` remains the SSE bridge and should pass through new Agent event names.
- Frontend keeps the current chat UI and maps new events into the existing timeline.

## Data Flow

1. Frontend sends a chat question to Spring Boot.
2. Spring Boot validates token and session ownership, then sends `user_id`, `session_id`, `question`, and approved `knowledge_base_ids` to FastAPI.
3. FastAPI loads memory, routes intent, executes `sql_query`, `rag_search`, both, or neither.
4. FastAPI composes a final answer and streams tool/citation/token events.
5. Spring Boot forwards events and saves only the final assistant message.
6. Frontend displays answer tokens and concise Agent tool trail.

## Major Decisions

- SQL tool is template-driven for MVP rather than unconstrained natural-language-to-SQL.
- Query-time `knowledge_base_ids` remains the primary permission boundary.
- SQL safety is enforced before execution and also limits result size.
- Direct/smalltalk questions do not call tools and explain Agent capabilities.

## Alternatives Considered

- Full LLM-generated SQL: deferred because it needs stronger schema governance and test coverage.
- External business DB connector: deferred because the first MVP should prove the Agent shell safely.
- Persisting tool calls in Java: deferred to avoid schema churn in the first Agent pass.

## Risks And Unknowns

- Existing source files contain mojibake strings; implementation should avoid broad text rewrites.
- SQL tests need fakes because local PostgreSQL may not be running.
- Model-based routing can be added later; rule routing is the deterministic fallback for this pass.

## High-Level Test Strategy

- Keep existing RAG tests green.
- Add focused AI tests for route selection and SQL validation.
- Add Java test for event passthrough.
- Use frontend `npm run build` as the UI regression check.
