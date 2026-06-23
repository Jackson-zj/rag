# Task: Text2SQL Hybrid Agent Integration

## Objective

Replace legacy SQL branches with the hybrid pipeline and preserve Agent contracts.

## Expected Files

- `ai-service/app/agent.py`
- PostgreSQL schema compatibility files
- Agent/API documentation and tests

## Steps

- [x] Add safe session and message ownership views.
- [x] Add pipeline fields and LangGraph nodes.
- [x] Emit safe domain/planner/row-count/scope metadata.
- [x] Remove legacy SQL-builder execution paths.
- [x] Run local and Docker end-to-end checks.

## Definition Of Done

- [x] Existing APIs remain compatible.
- [x] Permission failures bypass the model.
- [x] Full validation suite and smoke tests pass.
