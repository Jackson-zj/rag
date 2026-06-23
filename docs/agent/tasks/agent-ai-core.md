# Task: Agent AI Core

## Objective

Refactor the FastAPI AI service into a LangGraph Agent runtime with RAG, SQL, memory, and final answer tools while preserving current RAG behavior.

## Input Docs

- `docs/agent/agent-proposal.md`
- `docs/agent/agent-high-level-design.md`
- `docs/agent/agent-detailed-design.md`

## Expected Files

- `ai-service/app/main.py`
- `ai-service/app/schemas.py`
- `ai-service/app/agent.py`
- `ai-service/tests/test_api.py`
- `ai-service/tests/test_rag.py`

## Dependencies

- Existing RAG tests and API contracts.

## Implementation Steps

- [x] Add shared schema models.
- [x] Add Agent graph, route rules, SQL registry, SQL validation, and tool wrappers.
- [x] Wire `/ai/agent/run` through the new Agent graph.
- [x] Wire `/ai/chat/stream` through Agent stream events.
- [x] Add AI tests for routing, response shape, and SQL safety.

## Tests And Checks

```powershell
python -m unittest discover -s ai-service\tests
```

## Definition Of Done

- [x] Code implemented
- [x] Tests added or updated
- [x] Checks pass
- [x] Relevant docs or state updated
