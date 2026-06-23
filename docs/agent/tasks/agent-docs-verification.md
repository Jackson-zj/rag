# Task: Agent Docs And Verification

## Objective

Update public documentation and track verification for the Agent MVP.

## Input Docs

- `docs/agent/agent-proposal.md`
- `docs/agent/agent-high-level-design.md`
- `docs/agent/agent-detailed-design.md`
- `docs/agent/tasks/agent-ai-core.md`
- `docs/agent/tasks/agent-sse-ui.md`

## Expected Files

- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `README.md`
- `docs/agent/tasks/agent-progress.md`

## Dependencies

- Agent AI Core
- Agent SSE And UI Trail

## Implementation Steps

- [x] Document extended `/ai/agent/run` response.
- [x] Document Agent SSE events.
- [x] Document SQL safety and environment variables.
- [x] Record commands run, failures, and remaining risks.

## Tests And Checks

```powershell
python -m unittest discover -s ai-service\tests
.\mvnw.cmd test
cd frontend
npm run build
```

## Definition Of Done

- [x] Code implemented
- [x] Checks pass or failures documented
- [x] Relevant docs or state updated
