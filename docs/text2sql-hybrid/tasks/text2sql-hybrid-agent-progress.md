# Text2SQL Hybrid Agent Progress

## Current Status

Locked-entity planning refactor and verification are complete.

## Tasks

- [x] Hybrid Core - registry, QueryPlan, model repair, rule fallback, normalization, policy, and compiler implemented.
- [x] Agent Integration - LangGraph pipeline nodes, safe events, and ownership views implemented.
- [x] Verification And Documentation - local suites, documentation, and Docker smoke checks passed.
- [x] Locked Entity Refactor - deterministic constraints are extracted before model planning and merged before validation.

## Decisions

- Migrate all current SQL domains.
- Use versioned JSON semantic configuration.
- Use one model repair attempt, then rule-based QueryPlan fallback.
- Keep QueryPlan, SQL, and raw rows internal.
- Treat extracted date, username, and enum filters as immutable planner constraints.

## Blockers

- None.

## Commands Run

- AI unit suite - 40 tests passed.
- Java unit suite - 10 tests passed.
- Docker rebuilt AI and Java; health endpoints returned 200.
- Safe chat views exist and exclude message content.
- Smoke queries verified model planning, permission preflight, document metrics, absence normalization, and conversation-round semantics.
- Java SSE smoke verified compatible tool, tool_result, citation, token, and done events without exposing QueryPlan, executable SQL, or raw rows.
- Date-query regression verified explicit month/day, recent-day windows, and last-week ranges; planner network failures now fall back without a repair retry.
- Locked-entity regression verified that date ranges, explicit usernames, and enum aliases reach the planner first and override conflicting model filters.
- Docker smoke verified equivalent date separators produce identical locked filters, QueryPlan filters, and four-row user5 results.
