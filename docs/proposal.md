# Unified Capability Registry Proposal

## Goal

Replace the fixed RAG/SQL intent router with a model-driven, two-stage capability selection and planning flow while preserving deterministic authorization and execution.

## Non-Goals

- Runtime capability administration.
- Write tools, approvals, or idempotent mutations.
- Redis or database schema changes.

## Users And Runtime Context

Authenticated users continue to chat through the React UI and Spring Boot SSE endpoint. FastAPI owns capability planning and execution. PostgreSQL, the existing Java API, and the RAG index remain the systems of record.

## Functional Requirements

- Register `rag.search.v1`, `sql.query.v1`, and `document.status.v1` in a validated JSON registry.
- Use the configured model to select capabilities, build a bounded plan, evaluate results, and replan at most once.
- Inject identity and authorization context server-side.
- Preserve the current deterministic router when no model is available or planning fails.
- Expose safe capability metadata and plan summaries through JSON and SSE.

## Dependencies And Constraints

- Keep the existing OpenAI-compatible model client and Text2SQL safety pipeline.
- Java HTTP tools use a configured backend service alias and shared internal token.
- A plan has at most three steps, five total executions, and no duplicate capability/argument pair.

## Success Criteria

- Existing RAG and SQL behavior remains compatible.
- A model-generated plan can query a document's status through Java.
- Invalid capability IDs, unsafe context arguments, and unauthorized document access fail closed.
- Python and Java tests plus the frontend production build pass.

## Assumptions

- Capability definitions ship with the application.
- All v1 capabilities are read-only.
- Planning summaries are observable; private model reasoning is not.

## Open Questions

None.
