# Attendance And Worklog Agent Detailed Design

## Storage

- `attendance_records`: text ID, user FK, work date, nullable clock-in/out, constrained status, work/overtime minutes, remark, creation time, unique user/date.
- `employee_work_logs`: text ID, user FK, log date, project, summary, decimal work hours, constrained completion status, creation time, unique user/date.
- Views `agent_attendance_records` and `agent_employee_work_logs` join username and expose no authentication fields.
- Index both base tables on `(user_id, date DESC)`.

## Seed Behavior

- Resolve or create `user1` through `user5`, assign `USER`, and never replace an existing password.
- Generate four dated records per user with deterministic CASE expressions for varied status, time, project, hours, and summaries.
- Use stable IDs and `ON CONFLICT DO NOTHING`; expected count is exactly 20 rows per new table.

## SQL Tool

- Extend schema registry and route keywords for attendance, clocking, leave, overtime, daily logs, projects, and work hours.
- Resolve database scope from `user_id`; an administrator may query all employees or a username explicitly named in the question.
- Every non-admin employee query includes `WHERE user_id = %s`; model text cannot modify the scope.
- SQL citations and tool results contain row count and scope only. Raw rows stay in Agent state for final answer generation.

## Error Handling And Tests

- Unknown users receive a safe SQL-tool error and no rows.
- Missing database configuration keeps the existing fallback behavior.
- Tests cover routing, view whitelist, role scope, target username filtering, safe summaries, seed idempotency, and existing RAG/SSE regressions.

