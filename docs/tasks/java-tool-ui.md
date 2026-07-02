# Task: Java Tool, UI, And Deployment

## Objective

Add the authenticated Java document-status capability, expose plan summaries in the UI, and wire deployment configuration.

## Input Docs

- `docs/proposal.md`
- `docs/detailed-design.md`

## Expected Files

- `backend-java/src/*`
- `frontend/src/main.tsx`
- `deploy/*`

## Dependencies

- Capability registry contract.

## Implementation Steps

- [x] Add internal service-token authentication and document endpoint.
- [x] Add AI/Java environment configuration.
- [x] Render plan and Java citation events.
- [x] Add Java tests and update documentation.

## Tests And Checks

```powershell
.\mvnw.cmd test
cd frontend; npm run build
```

## Definition Of Done

- [x] Code implemented
- [x] Tests and build pass
- [x] Documentation updated
