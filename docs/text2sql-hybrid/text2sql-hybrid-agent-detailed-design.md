# Text2SQL Hybrid Agent Detailed Design

## QueryPlan

- `domain`: one registered domain.
- `dimensions`, `metrics`, and `group_by`: registered names only.
- `filters`: field, operator, and scalar/list value; operators are `eq/ne/in/contains/gt/gte/lt/lte`.
- `order_by`: registered selected field/metric and `asc/desc` direction.
- `limit`: 1 through 50.

## Planning

- Lexically score domain aliases/descriptions and retrieve the top two catalogs.
- Extract deterministic date, username, and enum filters for every candidate domain before model planning.
- Send the safe catalogs and locked filters to the configured model, which generates JSON QueryPlan without SQL.
- Parse the model structure, remove model filters for locked fields, merge the locked filters, then validate with Pydantic plus registry checks.
- On invalid output, send sanitized issue codes and allowed names for one repair.
- If no model or repair fails, generate a QueryPlan from registry aliases and common metric words, then merge the same locked filters.
- Chat-round semantics remain a deterministic plan adjustment after merge; permissions remain a separate later phase.

## Locked Entity Constraints

- Locked constraints are domain-specific because `date_field` differs between attendance, work logs, documents, and sessions.
- Date ranges recognize `到`, `至`, `-`, `—`, `–`, `~`, and `～`; range endpoints are inclusive for date fields.
- Explicit `userN` names become locked `username` filters when that domain exposes the field.
- Enum aliases from the registry, such as `缺卡 -> ABSENT`, become locked field filters.
- Model output cannot replace, widen, or remove a locked field. Permission policy may still replace username with a trusted user ID scope.

## Policy And Compilation

- Employee policy resolves administrator versus current user and rejects another-user targets for non-admins.
- Knowledge-base policy injects the backend-approved ID list.
- Session policy injects current user ID for non-admins.
- Compiler quotes only validated identifiers, parameterizes values, emits one `SELECT`, and adds grouping, ordering, and bounded limit.
- Existing SQL validator and statement timeout remain defense in depth.

## Compatibility

- `/ai/agent/run` and `/ai/chat/stream` response contracts remain stable.
- SQL tool metadata gains domain and planner but never includes QueryPlan, SQL, or rows.
- Existing RAG and mixed routes remain available.
