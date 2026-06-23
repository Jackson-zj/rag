# Task: Text2SQL Deterministic Locked Entities

## Objective

Move date, username, and enum extraction before model planning and make the extracted filters immutable through QueryPlan generation.

## Input Docs

- `docs/text2sql-hybrid/text2sql-hybrid-agent-detailed-design.md`
- `docs/text2sql-hybrid/text2sql-hybrid-agent-high-level-design.md`

## Expected Files

- `ai-service/app/text2sql.py`
- `ai-service/app/agent.py`
- `ai-service/app/schemas.py`
- `ai-service/tests/test_text2sql.py`

## Implementation Steps

- [x] Add domain-specific deterministic entity extraction.
- [x] Send locked filters to the planner and merge before semantic validation.
- [x] Add a LangGraph entity-extraction node.
- [x] Support equivalent date-range separators.
- [x] Add focused regression tests and Docker smoke verification.

## Definition Of Done

- [x] The planner sees locked filters before generating QueryPlan.
- [x] Model filters cannot override dates, usernames, or enum aliases.
- [x] Permission injection remains authoritative.
- [x] AI tests and real database smoke queries pass.
