# Task: Agent SSE And UI Trail

## Objective

Pass through new Agent SSE events and display concise tool/citation timeline entries in the frontend.

## Input Docs

- `docs/agent/agent-proposal.md`
- `docs/agent/agent-high-level-design.md`
- `docs/agent/agent-detailed-design.md`

## Expected Files

- `backend-java/src/main/java/com/enterprise/rag/AiClient.java`
- `backend-java/src/test/java/com/enterprise/rag/ApiControllerTest.java`
- `frontend/src/main.tsx`
- `frontend/src/styles.css`

## Dependencies

- Agent AI Core stream contract.

## Implementation Steps

- [x] Forward `tool_result` and `citation` events in Java `AiClient`.
- [x] Add a Java test for passthrough event dispatch.
- [x] Parse `tool_result` and `citation` events in the frontend stream loop.
- [x] Keep final answer text limited to `token` events.

## Tests And Checks

```powershell
.\mvnw.cmd test
cd frontend
npm run build
```

## Definition Of Done

- [x] Code implemented
- [x] Tests added or updated
- [x] Checks pass
- [x] Relevant docs or state updated
