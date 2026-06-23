# Agent Progress

## Current Status

Agent MVP implementation is complete for this pass. Planning artifacts were created separately from the existing RBAC/persistence documents to avoid overwriting prior project state.

## Tasks

- [x] Agent AI Core - LangGraph-style Agent runtime, RAG tool, SQL tool, routing, streaming, and AI tests implemented.
- [x] Agent SSE And UI Trail - Java passthrough and frontend concise tool/citation timeline implemented.
- [x] Agent Docs And Verification - Agent docs, public API/architecture/README updates, and validation records completed.

## Commands Run

- `Get-Content C:\Users\94898\.codex\skills\vibe-coding-workflow\SKILL.md`
- `Get-Content C:\Users\94898\.codex\skills\vibe-coding-workflow\references\prompt-templates.md`
- Repository inspection commands for AI, Java, frontend, and docs.
- `D:\anaconda3\envs\rag-ai\python.exe -m unittest discover -s tests` from `ai-service` - passed, 24 tests.
- `$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'; $env:Path="$env:JAVA_HOME\bin;$env:Path"; .\mvnw.cmd test` - passed, 10 Java tests.
- `npm run build` from `frontend` - passed.

## Decisions

- SQL tool queries only this project's PostgreSQL metadata for the MVP.
- SQL tool is read-only and whitelist-based.
- Frontend shows concise tool trail events.
- Existing docs with generic names are not overwritten; Agent docs use `agent-*` names.
- AI tests must use the `rag-ai` environment. The old `torch311` environment still has the known FastAPI/Starlette conflict.

## Blockers

- None currently.

## Next Steps

- Optional next pass: replace template SQL routing with model-assisted SQL generation guarded by the same validator.
- Optional next pass: persist tool audit events in PostgreSQL.
