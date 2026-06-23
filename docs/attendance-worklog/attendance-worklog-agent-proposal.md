# Attendance And Worklog Agent Proposal

## Goal

Add attendance and daily work-log data for employees `user1` through `user5`, and make it queryable through the existing SQL tool with database-enforced user scope and model-generated summaries.

## Non-Goals

- No attendance or work-log CRUD page.
- No model-generated arbitrary SQL.
- No exposure of password hashes, role relations, or raw employee rows in SSE events.

## Functional Requirements

- Create missing `user1` through `user5` accounts with role `USER` and password `user123`; preserve existing accounts.
- Create `attendance_records` and `employee_work_logs` with safe Agent views.
- Seed exactly 20 rows per table: four rows for each employee.
- Allow administrators to query all employees; constrain other users to their own rows.
- Route attendance and work-log questions to the SQL tool and summarize evidence with the configured model.

## Success Criteria

- Schema and seed operations are idempotent on new and existing databases.
- SQL scope cannot be widened by prompt text or caller-supplied roles.
- Agent answers are natural-language summaries without raw SQL row formatting.
- AI, Java, frontend, and Docker smoke checks pass.

## Assumptions

- Existing `user1` through `user5` IDs and passwords are retained.
- New accounts use deterministic IDs only when the username does not already exist.
- Test rows use deterministic variation so counts remain stable across restarts.

