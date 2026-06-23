# Task: Attendance Worklog Database

## Objective

Create schema, views, demo employees, and deterministic seed records.

## Input Docs

- `docs/attendance-worklog/attendance-worklog-agent-proposal.md`
- `docs/attendance-worklog/attendance-worklog-agent-detailed-design.md`

## Expected Files

- `deploy/postgres/init.sql`
- `backend-java/src/main/java/com/enterprise/rag/UserRepository.java`
- focused Java tests

## Implementation Steps

- [x] Add tables, constraints, indexes, and safe views.
- [x] Preserve existing seed accounts while creating missing `user1` through `user5`.
- [x] Insert four deterministic rows per user into each table.
- [x] Verify restart idempotency and row distribution.

## Definition Of Done

- [x] Schema supports new and existing volumes.
- [x] Each table has exactly 20 seed rows and each employee has four.
- [x] Java tests pass.
