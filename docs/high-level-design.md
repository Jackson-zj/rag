# Unified Capability Registry High-Level Design

## Architecture

The FastAPI service loads a versioned capability registry and filters disabled capabilities. The Agent sends a compact catalog to the model, sends full schemas only for selected capabilities, validates the resulting plan, and dispatches each step through a fixed executor map.

```text
Chat -> select capabilities -> build plan -> execute -> evaluate -> optional replan -> answer
                                      |-> RAG handler
                                      |-> safe Text2SQL pipeline
                                      |-> allowlisted Java HTTP handler
```

## Boundaries

- The model chooses capabilities and arguments but never supplies identity, ACLs, URLs, or credentials.
- The capability registry describes public semantics and executor aliases; secrets stay in environment variables.
- `semantic-registry.json` remains private to the SQL executor.
- Spring Boot reconstructs the acting user from `X-Acting-User-Id` only after validating `X-Agent-Service-Token`.

## Compatibility

Existing response and SSE fields remain. New plan metadata is additive. The legacy router is retained solely as a fallback.

## Risks And Mitigations

- Invalid model JSON: validate and fall back deterministically.
- Planner loops: one replan, three steps per plan, five executions total, duplicate suppression.
- SSRF or credential injection: service aliases and server-injected headers only.
- Tool result leakage: normalized summaries and existing ACL enforcement.

## Test Strategy

Unit-test registry and plan validation, mock model and HTTP calls in Python, test internal authentication and ACLs in Java, and verify SSE/UI compatibility with a frontend build.
