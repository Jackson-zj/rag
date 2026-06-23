# Task: Attendance Worklog SQL Agent

## Objective

Add scoped SQL templates, routing, safe events, and model summaries for employee data.

## Input Docs

- `docs/attendance-worklog/attendance-worklog-agent-proposal.md`
- `docs/attendance-worklog/attendance-worklog-agent-detailed-design.md`

## Expected Files

- `ai-service/app/agent.py`
- `ai-service/tests/test_api.py`
- public Agent documentation

## Implementation Steps

- [x] Add safe views to the schema registry and route vocabulary.
- [x] Resolve user role and enforce administrator/all versus user/self scope.
- [x] Add attendance and work-log detail/summary templates.
- [x] Remove raw SQL rows from citations and tool-result events.
- [x] Add focused permission, routing, and answer tests.

## Definition Of Done

- [x] Normal users cannot query another employee.
- [x] Administrators can query all or a named employee.
- [x] Final answers are summarized and SSE metadata is safe.
