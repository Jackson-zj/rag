import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
FilterOperator = Literal["eq", "ne", "in", "contains", "gt", "gte", "lt", "lte"]


class FieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["string", "integer", "number", "date", "time", "datetime", "enum"]
    description: str
    aliases: list[str] = Field(default_factory=list)
    value_aliases: dict[str, str | list[str]] = Field(default_factory=dict)
    internal: bool = False


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregate: Literal["count", "count_distinct", "sum", "avg", "min", "max"]
    field: str
    description: str
    aliases: list[str] = Field(default_factory=list)


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    direction: Literal["asc", "desc"] = "asc"


class DomainDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    description: str
    aliases: list[str]
    policy: Literal["employee_scope", "knowledge_base_scope", "session_scope"]
    scope_field: str
    date_field: str | None = None
    default_dimensions: list[str] = Field(default_factory=list)
    default_order: list[OrderBy] = Field(default_factory=list)
    dimensions: dict[str, FieldDefinition]
    metrics: dict[str, MetricDefinition]

    @model_validator(mode="after")
    def validate_catalog(self):
        if not IDENTIFIER.fullmatch(self.source):
            raise ValueError("Domain source must be a safe identifier")
        for name in [*self.dimensions, *self.metrics]:
            if not IDENTIFIER.fullmatch(name):
                raise ValueError(f"Unsafe semantic name: {name}")
        if self.scope_field not in self.dimensions:
            raise ValueError("scope_field must be a registered dimension")
        if self.date_field and self.date_field not in self.dimensions:
            raise ValueError("date_field must be a registered dimension")
        if any(name not in self.dimensions for name in self.default_dimensions):
            raise ValueError("default_dimensions contains an unknown field")
        for metric in self.metrics.values():
            if metric.field != "*" and metric.field not in self.dimensions:
                raise ValueError("Metric field must be '*' or a registered dimension")
        return self


class SemanticRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    domains: dict[str, DomainDefinition]

    @model_validator(mode="after")
    def validate_domains(self):
        if self.version != 1:
            raise ValueError("Unsupported semantic registry version")
        if not self.domains:
            raise ValueError("Semantic registry must contain domains")
        for name in self.domains:
            if not IDENTIFIER.fullmatch(name):
                raise ValueError(f"Unsafe domain name: {name}")
        return self


class QueryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    operator: FilterOperator
    value: str | int | float | bool | list[str] | list[int] | list[float]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    metrics: list[str] = Field(default_factory=list, max_length=5)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)
    group_by: list[str] = Field(default_factory=list, max_length=8)
    order_by: list[OrderBy] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=20, ge=1, le=50)


class LockedQueryConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)


class PlanValidationError(ValueError):
    def __init__(self, issues: list[dict[str, str]], catalog: dict[str, Any]):
        super().__init__("QueryPlan validation failed")
        self.issues = issues
        self.catalog = catalog


class PermissionDenied(ValueError):
    pass


@dataclass
class CompiledQuery:
    sql: str
    params: tuple[Any, ...]
    scope: str


def load_semantic_registry(path: str | Path | None = None) -> SemanticRegistry:
    registry_path = Path(path) if path else Path(__file__).with_name("semantic-registry.json")
    with registry_path.open("r", encoding="utf-8") as handle:
        return SemanticRegistry.model_validate(json.load(handle))


def domain_catalog(name: str, domain: DomainDefinition) -> dict[str, Any]:
    return {
        "domain": name,
        "description": domain.description,
        "dimensions": {
            field: {
                "type": definition.type,
                "description": definition.description,
                **(
                    {"enum_values": sorted({value for canonical in definition.value_aliases.values() for value in (canonical if isinstance(canonical, list) else [canonical])})}
                    if definition.value_aliases
                    else {}
                ),
            }
            for field, definition in domain.dimensions.items()
            if not definition.internal
        },
        "metrics": {metric: definition.description for metric, definition in domain.metrics.items()},
        "filter_operators": ["eq", "ne", "in", "contains", "gt", "gte", "lt", "lte"],
    }


def retrieve_domains(question: str, registry: SemanticRegistry, top_k: int = 2) -> list[str]:
    lowered = question.lower()
    scored: list[tuple[int, str]] = []
    for name, domain in registry.domains.items():
        score = 0
        for term in [name, *domain.aliases]:
            if term.lower() in lowered:
                score += max(2, len(term))
        for metric_name, metric in domain.metrics.items():
            if metric_name in lowered:
                score += 2
            score += sum(2 for alias in metric.aliases if alias.lower() in lowered)
        for field in domain.dimensions.values():
            score += sum(3 for alias in field.value_aliases if alias.lower() in lowered)
        if score > 0:
            for field_name, field in domain.dimensions.items():
                if field_name in lowered:
                    score += 2
                score += sum(1 for alias in field.aliases if alias.lower() in lowered)
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored[: max(1, top_k)]]


def sanitized_validation_issues(error: Exception) -> list[dict[str, str]]:
    if isinstance(error, PlanValidationError):
        return error.issues
    if isinstance(error, ValidationError):
        return [
            {"path": ".".join(str(part) for part in issue["loc"]), "code": issue["type"]}
            for issue in error.errors(include_input=False)
        ]
    return [{"path": "plan", "code": "invalid_json_plan"}]


def _is_valid_temporal_value(field_type: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if field_type == "date":
            date.fromisoformat(value)
        elif field_type == "time":
            time.fromisoformat(value)
        elif field_type == "datetime":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                date.fromisoformat(value)
        else:
            return True
    except ValueError:
        return False
    return True


def validate_query_plan(
    plan: QueryPlan | dict[str, Any],
    registry: SemanticRegistry,
    allowed_domains: list[str] | None = None,
) -> QueryPlan:
    try:
        parsed = plan if isinstance(plan, QueryPlan) else QueryPlan.model_validate(plan)
    except ValidationError as ex:
        raise PlanValidationError(sanitized_validation_issues(ex), {}) from ex
    issues: list[dict[str, str]] = []
    if parsed.domain not in registry.domains or (allowed_domains and parsed.domain not in allowed_domains):
        issues.append({"path": "domain", "code": "unknown_or_unretrieved_domain"})
        catalog = {name: domain_catalog(name, registry.domains[name]) for name in allowed_domains or [] if name in registry.domains}
        raise PlanValidationError(issues, catalog)
    domain = registry.domains[parsed.domain]
    public_dimensions = {name for name, definition in domain.dimensions.items() if not definition.internal}
    for path, names in (("dimensions", parsed.dimensions), ("group_by", parsed.group_by)):
        for name in names:
            if name not in public_dimensions:
                issues.append({"path": path, "code": f"unknown_field:{name}"})
    for name in parsed.metrics:
        if name not in domain.metrics:
            issues.append({"path": "metrics", "code": f"unknown_metric:{name}"})
    for item in parsed.filters:
        if item.field not in public_dimensions:
            issues.append({"path": "filters", "code": f"unknown_field:{item.field}"})
            continue
        definition = domain.dimensions[item.field]
        if item.operator == "in" and not isinstance(item.value, list):
            issues.append({"path": "filters", "code": "in_requires_list"})
        if item.operator == "contains" and not isinstance(item.value, str):
            issues.append({"path": "filters", "code": "contains_requires_string"})
        if item.operator == "contains" and definition.type != "string":
            issues.append({"path": "filters", "code": f"contains_not_allowed_for:{definition.type}"})
        if item.operator in ("gt", "gte", "lt", "lte") and definition.type not in ("integer", "number", "date", "time", "datetime"):
            issues.append({"path": "filters", "code": f"range_not_allowed_for:{definition.type}"})
        values = item.value if isinstance(item.value, list) else [item.value]
        if definition.type == "enum":
            allowed_values = {
                value
                for canonical in definition.value_aliases.values()
                for value in (canonical if isinstance(canonical, list) else [canonical])
            }
            for value in values:
                if value not in allowed_values:
                    issues.append({"path": "filters", "code": f"invalid_enum_value:{item.field}"})
        if definition.type in ("date", "time", "datetime"):
            for value in values:
                if not _is_valid_temporal_value(definition.type, value):
                    issues.append({"path": "filters", "code": f"invalid_{definition.type}_value:{item.field}"})
        if definition.type in ("integer", "number") and any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
            issues.append({"path": "filters", "code": f"numeric_value_required:{item.field}"})
    if parsed.metrics and set(parsed.dimensions) - set(parsed.group_by):
        issues.append({"path": "group_by", "code": "all_selected_dimensions_must_be_grouped"})
    selected = set(parsed.dimensions) | set(parsed.metrics)
    for order in parsed.order_by:
        if order.field not in selected:
            issues.append({"path": "order_by", "code": f"field_not_selected:{order.field}"})
    if not parsed.dimensions and not parsed.metrics:
        issues.append({"path": "plan", "code": "empty_projection"})
    if issues:
        raise PlanValidationError(issues, {parsed.domain: domain_catalog(parsed.domain, domain)})
    return parsed


def question_username(question: str) -> str | None:
    match = re.search(r"(?<![a-z0-9_])user\d+(?![a-z0-9_])", question.lower())
    return match.group(0) if match else None


CHINESE_DAY_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _date_filters_for_day(field: str, field_type: str, value: date) -> list[QueryFilter]:
    if field_type == "datetime":
        return [
            QueryFilter(field=field, operator="gte", value=value.isoformat()),
            QueryFilter(field=field, operator="lt", value=(value + timedelta(days=1)).isoformat()),
        ]
    return [QueryFilter(field=field, operator="eq", value=value.isoformat())]


def _date_filters_for_range(field: str, field_type: str, start: date, end: date) -> list[QueryFilter]:
    if start > end:
        return []
    if field_type == "datetime":
        return [
            QueryFilter(field=field, operator="gte", value=start.isoformat()),
            QueryFilter(field=field, operator="lt", value=(end + timedelta(days=1)).isoformat()),
        ]
    return [
        QueryFilter(field=field, operator="gte", value=start.isoformat()),
        QueryFilter(field=field, operator="lte", value=end.isoformat()),
    ]


def question_date_filters(question: str, domain: DomainDefinition) -> list[QueryFilter]:
    if not domain.date_field:
        return []
    field = domain.date_field
    field_type = domain.dimensions[field].type
    lowered = question.lower()
    today = date.today()

    date_range = re.search(
        r"(?:从)?(?:(\d{4})[./-])?(\d{1,2})[./月](\d{1,2})(?:日|号)?\s*"
        r"(?:到|至|[-—–~～])\s*(?:(\d{4})[./-])?(\d{1,2})[./月](\d{1,2})(?:日|号)?",
        lowered,
    )
    full_date = re.search(r"(?<!\d)(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?:日|号)?(?!\d)", lowered)
    month_day = re.search(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:日|号)?(?!\d)", lowered)
    chinese_month_day = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})(?:日|号)?", lowered)
    try:
        if date_range:
            start = date(
                int(date_range.group(1) or today.year),
                int(date_range.group(2)),
                int(date_range.group(3)),
            )
            end = date(
                int(date_range.group(4) or start.year),
                int(date_range.group(5)),
                int(date_range.group(6)),
            )
            return _date_filters_for_range(field, field_type, start, end)
        if full_date:
            target = date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3)))
            return _date_filters_for_day(field, field_type, target)
        matched = month_day or chinese_month_day
        if matched:
            target = date(today.year, int(matched.group(1)), int(matched.group(2)))
            return _date_filters_for_day(field, field_type, target)
    except ValueError:
        return []

    recent = re.search(r"(?:近|最近|过去)(\d+|[一二三四五六七八九十])天", lowered)
    if recent:
        token = recent.group(1)
        days = int(token) if token.isdigit() else CHINESE_DAY_NUMBERS.get(token, 0)
        if days > 0:
            return [QueryFilter(field=field, operator="gte", value=(today - timedelta(days=days - 1)).isoformat())]

    current_monday = today - timedelta(days=today.weekday())
    if "last week" in lowered or "上周" in lowered:
        return [
            QueryFilter(field=field, operator="gte", value=(current_monday - timedelta(days=7)).isoformat()),
            QueryFilter(field=field, operator="lt", value=current_monday.isoformat()),
        ]
    if "this week" in lowered or "本周" in lowered:
        return [QueryFilter(field=field, operator="gte", value=current_monday.isoformat())]
    if "today" in lowered or "今天" in lowered or "今日" in lowered:
        return _date_filters_for_day(field, field_type, today)
    if "this month" in lowered or "本月" in lowered:
        return [QueryFilter(field=field, operator="gte", value=today.replace(day=1).isoformat())]
    return []


def extract_locked_constraints(
    question: str,
    candidates: list[str],
    registry: SemanticRegistry,
) -> dict[str, LockedQueryConstraints]:
    lowered = question.lower()
    username = question_username(question)
    extracted: dict[str, LockedQueryConstraints] = {}
    for name in candidates:
        if name not in registry.domains:
            continue
        domain = registry.domains[name]
        filters: list[QueryFilter] = []
        for field_name, field in domain.dimensions.items():
            if field.internal:
                continue
            for alias, canonical in sorted(field.value_aliases.items(), key=lambda item: len(item[0]), reverse=True):
                if alias.lower() not in lowered:
                    continue
                values = canonical if isinstance(canonical, list) else [canonical]
                filters.append(
                    QueryFilter(
                        field=field_name,
                        operator="in" if len(values) > 1 else "eq",
                        value=values if len(values) > 1 else values[0],
                    )
                )
                break
        if username and "username" in domain.dimensions and not domain.dimensions["username"].internal:
            filters.append(QueryFilter(field="username", operator="eq", value=username))
        filters.extend(question_date_filters(question, domain))
        extracted[name] = LockedQueryConstraints(domain=name, filters=filters)
    return extracted


def merge_locked_constraints(
    question: str,
    plan: QueryPlan,
    constraints: dict[str, LockedQueryConstraints],
    registry: SemanticRegistry,
) -> QueryPlan:
    merged = plan.model_copy(deep=True)
    locked = constraints.get(merged.domain)
    if locked:
        locked_fields = {item.field for item in locked.filters}
        merged.filters = [item for item in merged.filters if item.field not in locked_fields]
        merged.filters.extend(item.model_copy(deep=True) for item in locked.filters)

    lowered = question.lower()
    if merged.domain == "chat_message" and any(term in lowered for term in ("轮", "conversation round", "对话轮数", "问答轮数")):
        merged.dimensions = []
        merged.group_by = []
        merged.metrics = ["record_count"]
        merged.order_by = []
        merged.filters = [item for item in merged.filters if item.field != "role"]
        merged.filters.append(QueryFilter(field="role", operator="eq", value="user"))
    return merged


def fallback_query_plan(question: str, candidates: list[str], registry: SemanticRegistry) -> QueryPlan | None:
    if not candidates:
        return None
    name = candidates[0]
    domain = registry.domains[name]
    lowered = question.lower()
    filters: list[QueryFilter] = []
    explicit_dimensions: list[str] = []
    metrics: list[str] = []

    for field_name, field in domain.dimensions.items():
        if field.internal:
            continue
        if field_name in lowered or any(alias.lower() in lowered for alias in field.aliases):
            explicit_dimensions.append(field_name)

    for metric_name, metric in domain.metrics.items():
        if metric_name in lowered or any(alias.lower() in lowered for alias in metric.aliases):
            metrics.append(metric_name)
    count_terms = ("count", "多少", "几条", "总数", "数量", "统计", "轮")
    if any(term in lowered for term in count_terms) and not metrics and "record_count" in domain.metrics:
        metrics.append("record_count")

    if name == "chat_message" and any(term in lowered for term in ("轮", "conversation", "对话")):
        metrics = ["record_count"]
        explicit_dimensions = ["role"]

    if metrics:
        group_by = list(dict.fromkeys(explicit_dimensions))
        dimensions = group_by
        order_by: list[OrderBy] = []
    else:
        dimensions = list(dict.fromkeys(explicit_dimensions or domain.default_dimensions))
        group_by = []
        selected = set(dimensions)
        order_by = [item for item in domain.default_order if item.field in selected]

    return QueryPlan(
        domain=name,
        dimensions=dimensions,
        metrics=list(dict.fromkeys(metrics)),
        filters=filters,
        group_by=group_by,
        order_by=order_by,
        limit=20,
    )


async def create_query_plan(
    question: str,
    registry: SemanticRegistry,
    candidates: list[str],
    complete_json: Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]] | None,
    max_repairs: int = 1,
    locked_constraints: dict[str, LockedQueryConstraints] | None = None,
) -> tuple[QueryPlan | None, str]:
    catalogs = {name: domain_catalog(name, registry.domains[name]) for name in candidates}
    constraints = locked_constraints if locked_constraints is not None else extract_locked_constraints(question, candidates, registry)
    locked_payload = {
        name: {"filters": [item.model_dump() for item in locked.filters]}
        for name, locked in constraints.items()
    }
    if complete_json and candidates:
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the user question into one QueryPlan JSON object. Never output SQL. "
                    "Use only the supplied domains, dimensions, metrics, operators and enum values. "
                    "Locked filters were extracted deterministically and will be merged after your plan; "
                    "treat them as immutable constraints and do not add conflicting filters for those fields. "
                    "When metrics and dimensions are both selected, include every dimension in group_by."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "catalogs": catalogs, "locked_constraints": locked_payload},
                    ensure_ascii=False,
                ),
            },
        ]
        for attempt in range(max_repairs + 1):
            try:
                payload = await complete_json(messages)
                structural_plan = QueryPlan.model_validate(payload)
                if structural_plan.domain not in registry.domains or structural_plan.domain not in candidates:
                    raise PlanValidationError(
                        [{"path": "domain", "code": "unknown_or_unretrieved_domain"}],
                        catalogs,
                    )
                merged = merge_locked_constraints(question, structural_plan, constraints, registry)
                return validate_query_plan(merged, registry, candidates), "model"
            except Exception as ex:
                if not isinstance(ex, (PlanValidationError, ValidationError, ValueError)):
                    break
                if attempt >= max_repairs:
                    break
                messages.append({"role": "assistant", "content": "The previous QueryPlan was invalid."})
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "validation_issues": sanitized_validation_issues(ex),
                                "allowed_catalogs": catalogs,
                                "locked_constraints": locked_payload,
                                "instruction": "Return a corrected QueryPlan JSON object only without changing locked constraints.",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
    fallback = fallback_query_plan(question, candidates, registry)
    if fallback is None:
        return None, "fallback"
    merged = merge_locked_constraints(question, fallback, constraints, registry)
    return validate_query_plan(merged, registry, candidates), "fallback"


def apply_policy(
    question: str,
    plan: QueryPlan,
    registry: SemanticRegistry,
    principal: dict[str, Any],
    knowledge_base_ids: list[str],
) -> tuple[QueryPlan, str]:
    domain = registry.domains[plan.domain]
    secured = plan.model_copy(deep=True)
    secured.filters = [item for item in secured.filters if item.field != domain.scope_field]
    is_admin = bool(principal.get("is_admin"))
    username = str(principal["username"])
    target = question_username(question)

    if domain.policy == "employee_scope":
        plan_targets = [str(item.value).lower() for item in secured.filters if item.field == "username" and item.operator == "eq"]
        requested = target or (plan_targets[0] if plan_targets else None)
        secured.filters = [item for item in secured.filters if item.field != "username"]
        if not is_admin and requested and requested != username.lower():
            raise PermissionDenied("普通用户只能查询自己的考勤和工作日志。")
        if is_admin and requested:
            secured.filters.append(QueryFilter(field="username", operator="eq", value=requested))
            scope = f"员工 {requested}"
        elif is_admin:
            scope = "全部员工"
        else:
            secured.filters.append(QueryFilter(field=domain.scope_field, operator="eq", value=principal["id"]))
            scope = f"本人 {username}"
    elif domain.policy == "knowledge_base_scope":
        if not knowledge_base_ids:
            raise PermissionDenied("当前用户没有可查询的知识库范围。")
        secured.filters.append(QueryFilter(field=domain.scope_field, operator="in", value=knowledge_base_ids))
        scope = f"授权知识库 {len(knowledge_base_ids)} 个"
    else:
        if is_admin:
            scope = "全部会话"
        else:
            secured.filters.append(QueryFilter(field=domain.scope_field, operator="eq", value=principal["id"]))
            scope = f"本人 {username}"
    return secured, scope


def preflight_permission(
    question: str,
    candidates: list[str],
    registry: SemanticRegistry,
    principal: dict[str, Any],
    knowledge_base_ids: list[str],
) -> None:
    policies = {registry.domains[name].policy for name in candidates if name in registry.domains}
    target = question_username(question)
    if "employee_scope" in policies and target and not principal.get("is_admin") and target != str(principal["username"]).lower():
        raise PermissionDenied("普通用户只能查询自己的考勤和工作日志。")
    if candidates and registry.domains[candidates[0]].policy == "knowledge_base_scope" and not knowledge_base_ids:
        raise PermissionDenied("当前用户没有可查询的知识库范围。")


def compile_query(plan: QueryPlan, registry: SemanticRegistry, scope: str) -> CompiledQuery:
    domain = registry.domains[plan.domain]
    projections: list[str] = list(plan.dimensions)
    for metric_name in plan.metrics:
        metric = domain.metrics[metric_name]
        field = metric.field
        if metric.aggregate == "count":
            expression = "COUNT(*)"
        elif metric.aggregate == "count_distinct":
            expression = f"COUNT(DISTINCT {field})"
        else:
            expression = f"{metric.aggregate.upper()}({field})"
        projections.append(f"{expression} AS {metric_name}")

    clauses: list[str] = []
    params: list[Any] = []
    operators = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for item in plan.filters:
        if item.field not in domain.dimensions:
            raise ValueError("Compiler received an unknown field")
        if item.operator == "in":
            clauses.append(f"{item.field} = ANY(%s)")
            params.append(list(item.value) if isinstance(item.value, list) else [item.value])
        elif item.operator == "contains":
            clauses.append(f"{item.field}::text ILIKE %s")
            params.append(f"%{item.value}%")
        else:
            clauses.append(f"{item.field} {operators[item.operator]} %s")
            params.append(item.value)

    sql = f"SELECT {', '.join(projections)} FROM {domain.source}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if plan.group_by:
        sql += " GROUP BY " + ", ".join(plan.group_by)
    if plan.order_by:
        sql += " ORDER BY " + ", ".join(f"{item.field} {item.direction.upper()}" for item in plan.order_by)
    sql += f" LIMIT {plan.limit}"
    return CompiledQuery(sql=sql, params=tuple(params), scope=scope)
