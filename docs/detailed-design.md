# Unified Capability Registry Detailed Design

## AI Modules

- `capabilities.py`: registry models/loading, enabled filtering, selection and plan contracts, JSON Schema validation, execution dispatch, and normalized results.
- `capability-registry.json`: the three read-only definitions and executor aliases.
- `agent.py`: LangGraph orchestration, legacy fallback, result evaluation, response composition, and SSE plan events.
- `model_client.py`: continues to provide strict JSON completion; planner prompts require compact JSON without reasoning traces.

## Contracts

- Selection: `mode`, up to three `capability_ids`, and a short `summary`.
- Plan: one to three ordered steps containing `step_id`, `capability_id`, and `arguments`.
- Result: capability ID/name, `ok|error`, summary, safe data, citations, and elapsed time.
- Reserved arguments (`user_id`, `knowledge_base_ids`, `token`, authorization headers, URLs) are rejected before execution.

## Execution

- RAG accepts a query and bounded `top_k`; user and knowledge-base scope are injected.
- SQL accepts no trusted model parameters and runs the original question through the existing safe pipeline.
- Java document status accepts `document_id`; the HTTP executor resolves `backend-java`, applies configured headers, and calls the fixed path template.
- Evaluation sees result summaries, not raw credentials or executor configuration, and returns `complete`, `replan`, or `clarify`.

## Java Internal API

`GET /internal/agent/documents/{documentId}` requires `X-Agent-Service-Token` and `X-Acting-User-Id`. It rejects missing configuration, bad tokens, unknown/disabled users, missing documents, and knowledge-base ACL violations.

## Configuration

- `JAVA_TOOL_BASE_URL`
- `AGENT_INTERNAL_TOKEN`

The Java capability is omitted from the enabled catalog unless both are present.

## Compatibility And Errors

- Existing `route`, tool calls/results, citations, and SSE events remain.
- New metadata is optional and additive.
- Planning failures use the existing deterministic RAG/SQL path; executor failures are surfaced to evaluation and may trigger one replan.

## Verification

Run Python unit tests, Maven tests with JDK 17, and `npm run build`; review the final diff and update progress notes.
