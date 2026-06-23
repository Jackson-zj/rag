# Text2SQL Hybrid Agent High-Level Design

## Pipeline

`retrieve_semantics -> plan_query -> validate_plan -> apply_policy -> compile_sql -> execute_sql -> compose_answer`

## Boundaries

- `semantic-registry.json` is the only model-visible schema catalog.
- `text2sql.py` owns registry loading, domain retrieval, QueryPlan validation, fallback planning, policy application, and SQL compilation.
- `model_client.py` owns OpenAI-compatible JSON and text completion calls.
- `agent.py` coordinates LangGraph state, database principal resolution, execution, events, and final answers.

## Security

- Registry identifiers and metric expressions are trusted versioned configuration; user values are always SQL parameters.
- Employee, knowledge-base, and session policies are injected by code and cannot be removed by QueryPlan.
- Safe views flatten chat-message ownership without exposing content.
- Permission errors return fixed responses; validation errors expose only safe catalog names and retry once.

