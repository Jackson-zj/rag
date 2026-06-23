# Task: Text2SQL Hybrid Core

## Objective

Implement semantic registry, QueryPlan, model/rule planning, policy injection, and SQL compilation.

## Expected Files

- `ai-service/app/semantic-registry.json`
- `ai-service/app/text2sql.py`
- `ai-service/app/model_client.py`
- focused AI tests

## Steps

- [x] Define and validate six semantic domains.
- [x] Implement QueryPlan and sanitized validation errors.
- [x] Implement top-k domain retrieval and model repair loop.
- [x] Implement generic fallback planner and compiler.
- [x] Add policy injection and security tests.

## Definition Of Done

- [x] No executable SQL comes from the model.
- [x] All six domains compile through one generic compiler.
- [x] Focused tests pass.
