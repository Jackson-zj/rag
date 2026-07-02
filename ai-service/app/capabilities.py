import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


RESERVED_ARGUMENTS = {
    "user_id",
    "knowledge_base_ids",
    "token",
    "authorization",
    "url",
    "base_url",
    "x_agent_service_token",
    "x_acting_user_id",
}


class ExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["handler", "http"]
    handler: str | None = None
    service: str | None = None
    method: Literal["GET"] | None = None
    path: str | None = None

    @model_validator(mode="after")
    def validate_executor(self):
        if self.type == "handler" and (not self.handler or self.service or self.method or self.path):
            raise ValueError("Handler executors require only handler")
        if self.type == "http":
            if not self.service or self.method != "GET" or not self.path or self.handler:
                raise ValueError("HTTP executors require service, GET method, and path")
            if not self.path.startswith("/") or "://" in self.path or ".." in self.path:
                raise ValueError("HTTP executor path is unsafe")
        return self


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    side_effect: Literal["read"]
    input_schema: dict[str, Any]
    executor: ExecutorConfig

    @model_validator(mode="after")
    def validate_definition(self):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*\.v\d+", self.id):
            raise ValueError("Capability ID must be versioned")
        validate_schema_definition(self.input_schema)
        return self

    def public_metadata(self, include_schema: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "side_effect": self.side_effect,
        }
        if include_schema:
            result["input_schema"] = self.input_schema
        return result


class CapabilityRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    capabilities: list[CapabilityDefinition]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [item.id for item in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("Capability IDs must be unique")
        return self

    def by_id(self) -> dict[str, CapabilityDefinition]:
        return {item.id: item for item in self.capabilities}


class CapabilitySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["direct", "tools"]
    capability_ids: list[str] = Field(default_factory=list, max_length=3)
    summary: str = ""

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "direct" and self.capability_ids:
            raise ValueError("Direct mode cannot select capabilities")
        if self.mode == "tools" and not self.capability_ids:
            raise ValueError("Tools mode requires capabilities")
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError("Selected capabilities must be unique")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    capability_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_step_ids(self):
        ids = [item.step_id for item in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Plan step IDs must be unique")
        return self


class CapabilityEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["complete", "replan", "clarify"]
    summary: str = ""


class CapabilityResult(BaseModel):
    capability_id: str
    name: str
    status: Literal["ok", "error"]
    summary: str
    elapsed_ms: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)


def validate_schema_definition(schema: dict[str, Any]) -> None:
    if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise ValueError("Capability input schema must be an object schema")
    if schema.get("additionalProperties", True) is not False:
        raise ValueError("Capability input schema must reject additional properties")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(required, list) or any(item not in properties for item in required):
        raise ValueError("Capability schema has invalid required fields")
    for name, definition in properties.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise ValueError("Capability property definitions are invalid")
        if definition.get("type") not in {"string", "integer", "number", "boolean"}:
            raise ValueError(f"Unsupported property type for {name}")


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("Capability arguments must be an object")
    lowered = {str(name).lower() for name in arguments}
    blocked = lowered & RESERVED_ARGUMENTS
    if blocked:
        raise ValueError(f"Reserved capability arguments are not allowed: {', '.join(sorted(blocked))}")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError(f"Missing required capability arguments: {', '.join(missing)}")
    if schema.get("additionalProperties") is False:
        unknown = set(arguments) - set(properties)
        if unknown:
            raise ValueError(f"Unknown capability arguments: {', '.join(sorted(unknown))}")
    for name, value in arguments.items():
        definition = properties[name]
        expected = definition.get("type")
        valid = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
        }[expected]
        if not valid:
            raise ValueError(f"Capability argument {name} must be {expected}")
        if isinstance(value, str) and len(value) < int(definition.get("minLength", 0)):
            raise ValueError(f"Capability argument {name} is too short")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in definition and value < definition["minimum"]:
                raise ValueError(f"Capability argument {name} is below minimum")
            if "maximum" in definition and value > definition["maximum"]:
                raise ValueError(f"Capability argument {name} exceeds maximum")


def load_capability_registry(path: str | Path | None = None) -> CapabilityRegistry:
    registry_path = Path(path) if path else Path(__file__).with_name("capability-registry.json")
    with registry_path.open("r", encoding="utf-8") as handle:
        return CapabilityRegistry.model_validate(json.load(handle))


def enabled_capabilities(
    registry: CapabilityRegistry,
    *,
    java_base_url: str = "",
    internal_token: str = "",
) -> list[CapabilityDefinition]:
    return [
        item
        for item in registry.capabilities
        if item.executor.type != "http" or (java_base_url.strip() and internal_token.strip())
    ]


def validate_selection(payload: dict[str, Any], enabled: list[CapabilityDefinition]) -> CapabilitySelection:
    selection = CapabilitySelection.model_validate(payload)
    known = {item.id for item in enabled}
    unknown = set(selection.capability_ids) - known
    if unknown:
        raise ValueError(f"Model selected unavailable capabilities: {', '.join(sorted(unknown))}")
    return selection


def validate_plan(
    payload: dict[str, Any],
    selected: list[CapabilityDefinition],
) -> ExecutionPlan:
    plan = ExecutionPlan.model_validate(payload)
    definitions = {item.id: item for item in selected}
    for step in plan.steps:
        definition = definitions.get(step.capability_id)
        if definition is None:
            raise ValueError(f"Plan uses an unselected capability: {step.capability_id}")
        validate_arguments(definition.input_schema, step.arguments)
    return plan


def execution_key(step: PlanStep) -> str:
    return f"{step.capability_id}:{json.dumps(step.arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"


Handler = Callable[[CapabilityDefinition, dict[str, Any], dict[str, Any]], Awaitable[CapabilityResult]]


class CapabilityDispatcher:
    def __init__(
        self,
        *,
        handlers: dict[str, Handler],
        services: dict[str, str],
        internal_token: str,
        timeout: float = 10,
    ):
        self.handlers = handlers
        self.services = {name: url.rstrip("/") for name, url in services.items() if url.strip()}
        self.internal_token = internal_token
        self.timeout = timeout

    async def execute(
        self,
        definition: CapabilityDefinition,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> CapabilityResult:
        validate_arguments(definition.input_schema, arguments)
        started = time.perf_counter()
        if definition.executor.type == "handler":
            handler = self.handlers.get(definition.executor.handler or "")
            if handler is None:
                raise ValueError(f"Capability handler is not registered: {definition.executor.handler}")
            return await handler(definition, arguments, context)

        service = definition.executor.service or ""
        base_url = self.services.get(service)
        if not base_url or not self.internal_token:
            raise RuntimeError(f"Capability service is not configured: {service}")
        path = definition.executor.path or ""
        for name, value in arguments.items():
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        if "{" in path or "}" in path:
            raise ValueError("Capability path contains unresolved parameters")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{base_url}{path}",
                headers={
                    "X-Agent-Service-Token": self.internal_token,
                    "X-Acting-User-Id": str(context["user_id"]),
                },
            )
            response.raise_for_status()
            data = response.json()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return CapabilityResult(
            capability_id=definition.id,
            name=definition.name,
            status="ok",
            summary=f"Document status query completed for {arguments['document_id']}.",
            elapsed_ms=elapsed_ms,
            data=data if isinstance(data, dict) else {"result": data},
            citations=[{"type": "java", "capability_id": definition.id, "summary": f"Document {arguments['document_id']} status"}],
        )


async def select_capabilities_with_model(
    question: str,
    capabilities: list[CapabilityDefinition],
    complete_json: Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]],
    prior_results: list[dict[str, Any]] | None = None,
) -> CapabilitySelection:
    payload = await complete_json(
        [
            {
                "role": "system",
                "content": (
                    "Select the minimum capabilities needed to answer the user. Return one JSON object only with "
                    "mode=direct|tools, capability_ids (maximum 3), and a short summary. Do not provide reasoning."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "capabilities": [item.public_metadata() for item in capabilities],
                        "prior_results": prior_results or [],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    )
    return validate_selection(payload, capabilities)


async def build_plan_with_model(
    question: str,
    selected: list[CapabilityDefinition],
    complete_json: Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]],
    prior_results: list[dict[str, Any]] | None = None,
) -> ExecutionPlan:
    payload = await complete_json(
        [
            {
                "role": "system",
                "content": (
                    "Build an ordered execution plan. Return one JSON object only with 1-3 steps. Each step must contain "
                    "step_id, capability_id, and arguments matching the supplied schema. Never include identity, credentials, URLs, or authorization data."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "selected_capabilities": [item.public_metadata(include_schema=True) for item in selected],
                        "prior_results": prior_results or [],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    )
    return validate_plan(payload, selected)


async def evaluate_results_with_model(
    question: str,
    results: list[dict[str, Any]],
    complete_json: Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]],
) -> CapabilityEvaluation:
    payload = await complete_json(
        [
            {
                "role": "system",
                "content": (
                    "Decide whether the available tool result summaries are sufficient. Return one JSON object only with "
                    "decision=complete|replan|clarify and a short user-safe summary. Do not provide hidden reasoning."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "results": results}, ensure_ascii=False),
            },
        ]
    )
    return CapabilityEvaluation.model_validate(payload)
