# Text2SQL Hybrid Agent Proposal

## Goal

Replace hand-written SQL branches with a semantic registry, validated QueryPlan, policy injection, and generic parameterized SQL compiler across all existing structured-data domains.

## Non-Goals

- The model never emits executable SQL.
- No arbitrary cross-domain joins in v1.
- No runtime semantic-registry administration UI.

## Requirements

- Cover attendance, work logs, knowledge bases, documents, chat sessions, and chat messages.
- Store domain semantics, aliases, dimensions, metrics, enum values, and policies in versioned JSON.
- Generate QueryPlan through the model with one sanitized repair attempt, then use a rule-based QueryPlan fallback.
- Apply authorization after plan validation and before SQL compilation.
- Keep existing Agent APIs and SSE event names compatible.

## Success Criteria

- Existing fixed SQL builders are no longer the execution path.
- Unknown fields, sources, operators, sensitive requests, and writes cannot compile.
- Permission failures never enter model repair or answer generation.
- Existing AI, Java, frontend, and Docker smoke checks pass.

