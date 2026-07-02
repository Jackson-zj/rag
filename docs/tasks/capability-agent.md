# Task: Capability Registry And Agent

## Objective

Implement validated capability registration, model planning, bounded execution, fallback, and tests.

## Input Docs

- `docs/proposal.md`
- `docs/high-level-design.md`
- `docs/detailed-design.md`

## Expected Files

- `ai-service/app/*`
- `ai-service/tests/*`

## Dependencies

None.

## Implementation Steps

- [x] Add registry and planning contracts.
- [x] Add RAG, SQL, and HTTP executors.
- [x] Replace the primary fixed router with the bounded planning graph.
- [x] Add public capability metadata and SSE plan events.
- [x] Add focused tests.

## Tests And Checks

```powershell
python -m unittest discover -s ai-service\tests
```

## Definition Of Done

- [x] Code implemented
- [x] Tests pass
- [x] Compatibility preserved
