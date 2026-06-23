# Attendance And Worklog Agent High-Level Design

## Architecture

- Java startup remains responsible for schema compatibility, demo users, and idempotent business-data seeding.
- PostgreSQL stores base tables and exposes two safe views containing only employee-facing fields plus username.
- FastAPI verifies the current user's role from PostgreSQL, builds parameterized templates, applies row scope, and passes rows only to answer composition.
- The model summarizes tool evidence; SSE emits only counts and safe scope metadata for SQL results.

## Data Flow

1. Java authenticates the caller and sends the trusted `user_id` through the existing chat contract.
2. LangGraph routes attendance/work-log language to `sql_query`.
3. SQL tool resolves the user and `ADMIN` role from the database.
4. Administrators receive all or username-filtered rows; other users receive only rows matching their database user ID.
5. Tool rows remain internal and the answer composer returns a concise natural-language answer.

## Decisions And Risks

- Use fixed SQL templates instead of free-form model SQL to keep row-level scope enforceable.
- Use views for the Agent whitelist and keep base employee tables unavailable to the validator.
- Duplicate schema declarations in `init.sql` and Java follow the repository's existing compatibility pattern.
- Existing databases require a Java restart because Docker initialization scripts do not rerun for populated volumes.

