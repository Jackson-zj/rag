import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

try:
    from langgraph.graph import END, StateGraph
except Exception:
    END = None
    StateGraph = None

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

from .schemas import AgentResponse, AgentState, ChatRequest, SearchRequest
from . import model_client
from .capabilities import (
    CapabilityDefinition,
    CapabilityDispatcher,
    CapabilityResult,
    PlanStep,
    build_plan_with_model,
    enabled_capabilities,
    evaluate_results_with_model,
    execution_key,
    load_capability_registry,
    select_capabilities_with_model,
)
from .text2sql import (
    PermissionDenied,
    QueryPlan,
    apply_policy,
    compile_query,
    create_query_plan,
    extract_locked_constraints,
    fallback_query_plan,
    load_semantic_registry,
    preflight_permission,
    retrieve_domains,
)

logger = logging.getLogger(__name__)

AGENT_SQL_DATABASE_URL = os.getenv("AGENT_SQL_DATABASE_URL") or os.getenv("VECTOR_DATABASE_URL", "")
MAX_SQL_ROWS = int(os.getenv("AGENT_SQL_MAX_ROWS", "50"))
TEXT2SQL_SCHEMA_TOP_K = int(os.getenv("TEXT2SQL_SCHEMA_TOP_K", "2"))
TEXT2SQL_MAX_REPAIRS = int(os.getenv("TEXT2SQL_MAX_REPAIRS", "1"))
TEXT2SQL_PLANNER_TIMEOUT_SECONDS = float(os.getenv("TEXT2SQL_PLANNER_TIMEOUT_SECONDS", "10"))
SEMANTIC_REGISTRY = load_semantic_registry()
CAPABILITY_REGISTRY = load_capability_registry()
JAVA_TOOL_BASE_URL = os.getenv("JAVA_TOOL_BASE_URL", "")
AGENT_INTERNAL_TOKEN = os.getenv("AGENT_INTERNAL_TOKEN", "")
MAX_PLAN_STEPS = 3
MAX_TOOL_EXECUTIONS = 5
MAX_REPLANS = 1

SQL_SCHEMA_REGISTRY = {
    domain.source: {
        "columns": list(domain.dimensions),
        "description": domain.description,
        "max_rows": MAX_SQL_ROWS,
    }
    for domain in SEMANTIC_REGISTRY.domains.values()
}


def sql_connection():
    if psycopg is None or dict_row is None:
        raise RuntimeError("AGENT_SQL_DATABASE_URL is configured, but psycopg is not installed")
    return psycopg.connect(AGENT_SQL_DATABASE_URL, row_factory=dict_row, connect_timeout=5)


def route_intent(question: str) -> str:
    lowered = question.lower()
    structured_domains = retrieve_domains(question, SEMANTIC_REGISTRY, TEXT2SQL_SCHEMA_TOP_K)
    policy_terms = any(term in lowered for term in ("policy", "rule", "制度", "规则", "规定"))
    content_terms = [
        "policy",
        "rule",
        "explain",
        "内容",
        "规则",
        "制度",
        "讲了",
        "说明",
        "怎么",
        "如何",
        "是什么",
    ]
    smalltalk_terms = ["hello", "hi", "你好", "谢谢", "你是谁", "help", "帮助"]
    has_content = any(term in lowered for term in content_terms)
    if structured_domains and policy_terms:
        return "mixed"
    if structured_domains:
        return "sql"
    if any(term in lowered for term in smalltalk_terms) and not has_content:
        return "direct"
    return "rag"


def validate_sql(sql: str) -> str:
    normalized = " ".join(sql.strip().split())
    lowered = normalized.lower()
    if not lowered.startswith("select "):
        raise ValueError("Only SELECT statements are allowed")
    if ";" in normalized:
        raise ValueError("Multiple statements are not allowed")
    forbidden = r"\b(insert|update|delete|drop|alter|truncate|create|copy|grant|revoke|merge|call|execute)\b"
    if re.search(forbidden, lowered):
        raise ValueError("Only read-only SELECT statements are allowed")
    referenced = set(re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered))
    if not referenced:
        raise ValueError("A whitelisted FROM table is required")
    blocked = referenced - set(SQL_SCHEMA_REGISTRY)
    if blocked:
        raise ValueError(f"Table is not whitelisted: {', '.join(sorted(blocked))}")
    if " limit " in lowered:
        match = re.search(r"\blimit\s+(\d+)\b", lowered)
        if match and int(match.group(1)) > MAX_SQL_ROWS:
            normalized = re.sub(r"\blimit\s+\d+\b", f"LIMIT {MAX_SQL_ROWS}", normalized, flags=re.IGNORECASE)
    else:
        normalized = f"{normalized} LIMIT {MAX_SQL_ROWS}"
    return normalized


def load_sql_principal(cursor: Any, user_id: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT users.id,
               users.username,
               EXISTS (
                 SELECT 1
                 FROM user_roles
                 JOIN roles ON roles.id = user_roles.role_id
                 WHERE user_roles.user_id = users.id AND roles.name = 'ADMIN'
               ) AS is_admin
        FROM users
        WHERE users.id = %s AND users.disabled = false
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise PermissionDenied("当前用户不存在或已被禁用，不能执行结构化数据查询。")
    return dict(row)


def fallback_tool_answer(question: str, rows: list[dict[str, Any]], contexts: list[dict[str, Any]]) -> str:
    """Produce a readable answer when the configured model is unavailable."""
    if rows and all("role" in row and ("record_count" in row or "message_count" in row) for row in rows):
        counts = {str(row["role"]).lower(): int(row.get("record_count", row.get("message_count", 0))) for row in rows}
        user_count = counts.get("user", 0)
        assistant_count = counts.get("assistant", 0)
        rounds = min(user_count, assistant_count)
        return f"系统当前共有 {rounds} 轮完整对话，包含 {user_count} 条用户消息和 {assistant_count} 条助手消息。"

    if rows and all("attendance_date" in row for row in rows):
        statuses = Counter(str(row.get("status") or "UNKNOWN") for row in rows)
        status_text = "、".join(f"{status} {count} 次" for status, count in statuses.items())
        overtime = sum(int(row.get("overtime_minutes") or 0) for row in rows)
        employees = len({str(row.get("username")) for row in rows})
        return f"查询范围包含 {employees} 名员工的 {len(rows)} 条考勤记录，状态分布为：{status_text}，合计加班 {overtime} 分钟。"

    if rows and all("work_summary" in row for row in rows):
        statuses = Counter(str(row.get("completion_status") or "UNKNOWN") for row in rows)
        status_text = "、".join(f"{status} {count} 条" for status, count in statuses.items())
        hours = sum(float(row.get("work_hours") or 0) for row in rows)
        employees = len({str(row.get("username")) for row in rows})
        return f"查询范围包含 {employees} 名员工的 {len(rows)} 条工作日志，累计工时 {hours:g} 小时，完成状态为：{status_text}。"

    if rows and all("filename" in row for row in rows):
        statuses = Counter(str(row.get("status") or "未知") for row in rows)
        status_text = "、".join(f"{status} {count} 个" for status, count in statuses.items())
        chunk_count = sum(int(row.get("chunk_count") or 0) for row in rows)
        answer = f"当前查询范围内共有 {len(rows)} 个文档，状态分布为：{status_text}，合计生成 {chunk_count} 个知识切片。"
        if contexts:
            answer += "\n\n" + main_fallback_rag_answer(question, contexts)
        return answer

    if rows and all("name" in row for row in rows):
        names = "、".join(str(row["name"]) for row in rows)
        return f"当前可访问 {len(rows)} 个知识库：{names}。"

    if rows and all("title" in row for row in rows):
        return f"查询到 {len(rows)} 个最近会话。"

    if contexts:
        return main_fallback_rag_answer(question, contexts)
    if rows:
        return f"查询到 {len(rows)} 条符合条件的记录。"
    return "未查询到足够的信息来回答该问题。"


def main_fallback_rag_answer(question: str, contexts: list[dict[str, Any]]) -> str:
    from . import main

    return main.compose_retrieval_answer(question, contexts)


async def generate_tool_answer(
    question: str,
    rows: list[dict[str, Any]],
    contexts: list[dict[str, Any]],
    history: list[dict[str, str]],
) -> str:
    from . import main

    fallback = fallback_tool_answer(question, rows, contexts)
    if not main.MODEL_API_KEY:
        return fallback

    structured_evidence = json.dumps(rows, ensure_ascii=False, default=str)
    rag_evidence = "\n".join(f"- {item['text']}（来源：{item['filename']}）" for item in contexts)
    try:
        return await model_client.complete_text(
            base_url=main.MODEL_BASE_URL,
            api_key=main.MODEL_API_KEY,
            model=main.MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是企业知识库 Agent。请根据工具证据直接回答问题并进行归纳总结。"
                        "不要逐行转抄数据，不要输出字段名=value、SQL、JSON或数据库时间戳。"
                        "数量问题应计算后给出明确数字；必要时用简短自然语言要点说明。"
                        "只能使用提供的证据，证据不足时明确说明。"
                    ),
                },
                *history[-6:],
                {
                    "role": "user",
                    "content": (
                        f"问题：{question}\n\n结构化工具证据：\n{structured_evidence or '无'}"
                        f"\n\n知识库证据：\n{rag_evidence or '无'}"
                    ),
                },
            ],
            temperature=0.2,
        )
    except Exception:
        pass
    return fallback


def tool_result(name: str, started: float, status: str, summary: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "data": data or {},
    }


async def run_rag_tool(state: AgentState) -> AgentState:
    from . import main

    started = time.perf_counter()
    state.setdefault("tool_calls", []).append({"name": "rag_search", "arguments": {"top_k": 5}})
    search = main.rag_search(
        SearchRequest(
            user_id=state["user_id"],
            query=state["question"],
            knowledge_base_ids=state.get("knowledge_base_ids", []),
        )
    )
    state["search"] = search
    count = len(search.get("results", []))
    summary = f"RAG 检索完成，命中 {count} 个片段。"
    state.setdefault("tool_results", []).append(tool_result("rag_search", started, "ok", summary, {"result_count": count}))
    return state


def record_sql_result(state: AgentState, status: str) -> AgentState:
    result = state.get("sql", {})
    if state.get("_suppress_tool_events"):
        return state
    state.setdefault("tool_results", []).append(
        tool_result(
            "sql_query",
            state.get("sql_started", time.perf_counter()),
            status,
            result.get("summary", "结构化查询未完成。"),
            {
                "domain": result.get("domain", "unknown"),
                "planner": result.get("planner", state.get("planner", "unknown")),
                "row_count": result.get("row_count", 0),
                "scope": result.get("scope", "unknown"),
            },
        )
    )
    return state


async def retrieve_semantics_node(state: AgentState) -> AgentState:
    state["sql_started"] = time.perf_counter()
    if not state.get("_suppress_tool_events"):
        state.setdefault("tool_calls", []).append({"name": "sql_query", "arguments": {}})
    state["semantic_domains"] = retrieve_domains(state["question"], SEMANTIC_REGISTRY, TEXT2SQL_SCHEMA_TOP_K)
    if not state["semantic_domains"]:
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "无法确定需要查询的业务数据，请补充业务对象或统计口径。",
            "row_count": 0,
            "scope": "clarify",
            "clarify": True,
        }
        return record_sql_result(state, "error")
    if not AGENT_SQL_DATABASE_URL:
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "SQL 工具未配置数据库连接，已跳过结构化数据查询。",
            "row_count": 0,
            "scope": "unconfigured",
            "error": True,
        }
        return record_sql_result(state, "error")
    try:
        with sql_connection() as connection:
            with connection.cursor() as cursor:
                state["principal"] = load_sql_principal(cursor, state["user_id"])
    except PermissionDenied as ex:
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": str(ex),
            "row_count": 0,
            "scope": "denied",
            "domain": state["semantic_domains"][0],
            "planner": "not_called",
            "denied": True,
            "error": True,
        }
        return record_sql_result(state, "error")
    return state


async def extract_entities_node(state: AgentState) -> AgentState:
    state["locked_constraints"] = extract_locked_constraints(
        state["question"],
        state.get("semantic_domains", []),
        SEMANTIC_REGISTRY,
    )
    try:
        preflight_permission(
            state["question"],
            state.get("semantic_domains", []),
            SEMANTIC_REGISTRY,
            state["principal"],
            state.get("knowledge_base_ids", []),
        )
    except PermissionDenied as ex:
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": str(ex),
            "row_count": 0,
            "scope": "denied",
            "domain": state["semantic_domains"][0],
            "planner": "not_called",
            "denied": True,
            "error": True,
        }
        return record_sql_result(state, "error")
    return state


async def plan_query_node(state: AgentState) -> AgentState:
    from . import main

    async def planner_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
        return await model_client.complete_json(
            base_url=main.MODEL_BASE_URL,
            api_key=main.MODEL_API_KEY,
            model=os.getenv("TEXT2SQL_PLANNER_MODEL", main.MODEL_NAME),
            messages=messages,
            temperature=0.0,
            timeout=TEXT2SQL_PLANNER_TIMEOUT_SECONDS,
        )

    completion = planner_completion if main.MODEL_API_KEY else None
    try:
        plan, planner = await create_query_plan(
            state["question"],
            SEMANTIC_REGISTRY,
            state.get("semantic_domains", []),
            completion,
            max_repairs=TEXT2SQL_MAX_REPAIRS,
            locked_constraints=state.get("locked_constraints"),
        )
        state["planner"] = planner
        if plan is None:
            state["sql"] = {
                "query": state["question"],
                "rows": [],
                "summary": "无法生成安全的查询计划，请换一种方式描述查询条件。",
                "row_count": 0,
                "scope": "clarify",
                "planner": planner,
                "clarify": True,
            }
            return record_sql_result(state, "error")
        state["query_plan"] = plan
        if not state.get("_suppress_tool_events"):
            state["tool_calls"][-1]["arguments"] = {"domain": plan.domain, "planner": planner}
    except Exception as ex:
        logger.warning("Text2SQL planning failed safely: %s", type(ex).__name__)
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "查询计划校验失败，请补充要查询的字段或统计口径。",
            "row_count": 0,
            "scope": "clarify",
            "planner": "failed",
            "clarify": True,
        }
        return record_sql_result(state, "error")
    return state


async def validate_plan_node(state: AgentState) -> AgentState:
    if not isinstance(state.get("query_plan"), QueryPlan):
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "查询计划格式无效，请重新描述问题。",
            "row_count": 0,
            "scope": "clarify",
            "clarify": True,
        }
        return record_sql_result(state, "error")
    return state


async def apply_policy_node(state: AgentState) -> AgentState:
    try:
        secured, scope = apply_policy(
            state["question"],
            state["query_plan"],
            SEMANTIC_REGISTRY,
            state["principal"],
            state.get("knowledge_base_ids", []),
        )
        state["secured_plan"] = secured
        state["sql_scope"] = scope
    except PermissionDenied as ex:
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": str(ex),
            "row_count": 0,
            "scope": "denied",
            "domain": getattr(state.get("query_plan"), "domain", "unknown"),
            "planner": state.get("planner", "unknown"),
            "error": True,
            "denied": True,
        }
        return record_sql_result(state, "error")
    return state


async def compile_sql_node(state: AgentState) -> AgentState:
    try:
        state["compiled_query"] = compile_query(state["secured_plan"], SEMANTIC_REGISTRY, state["sql_scope"])
    except Exception as ex:
        logger.warning("Text2SQL compilation failed safely: %s", type(ex).__name__)
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "查询计划无法安全编译，请调整查询条件。",
            "row_count": 0,
            "scope": "compile_error",
            "domain": getattr(state.get("query_plan"), "domain", "unknown"),
            "planner": state.get("planner", "unknown"),
            "error": True,
        }
        return record_sql_result(state, "error")
    return state


async def execute_sql_node(state: AgentState) -> AgentState:
    compiled = state["compiled_query"]
    try:
        safe_sql = validate_sql(compiled.sql)
        with sql_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute(safe_sql, compiled.params)
                rows = [dict(row) for row in cursor.fetchall()]
        domain = state["query_plan"].domain
        state["sql"] = {
            "query": state["question"],
            "rows": rows,
            "summary": f"SQL 查询完成，返回 {len(rows)} 条记录，查询范围：{compiled.scope}。",
            "row_count": len(rows),
            "scope": compiled.scope,
            "domain": domain,
            "planner": state.get("planner", "unknown"),
            "denied": False,
        }
        return record_sql_result(state, "ok")
    except Exception as ex:
        logger.exception(
            "Text2SQL execution failed for domain=%s planner=%s: %s",
            getattr(state.get("query_plan"), "domain", "unknown"),
            state.get("planner", "unknown"),
            type(ex).__name__,
        )
        state["sql"] = {
            "query": state["question"],
            "rows": [],
            "summary": "结构化查询执行失败，请稍后重试或调整查询条件。",
            "row_count": 0,
            "scope": "execution_error",
            "domain": getattr(state.get("query_plan"), "domain", "unknown"),
            "planner": state.get("planner", "unknown"),
            "error": True,
        }
        return record_sql_result(state, "error")


async def run_sql_pipeline(state: AgentState) -> AgentState:
    for node in (
        retrieve_semantics_node,
        extract_entities_node,
        plan_query_node,
        validate_plan_node,
        apply_policy_node,
        compile_sql_node,
        execute_sql_node,
    ):
        state = await node(state)
        if state.get("sql"):
            break
    return state


def available_capabilities() -> list[CapabilityDefinition]:
    return enabled_capabilities(
        CAPABILITY_REGISTRY,
        java_base_url=JAVA_TOOL_BASE_URL,
        internal_token=AGENT_INTERNAL_TOKEN,
    )


async def capability_planner_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    from . import main

    return await model_client.complete_json(
        base_url=main.MODEL_BASE_URL,
        api_key=main.MODEL_API_KEY,
        model=main.MODEL_NAME,
        messages=messages,
        temperature=0.0,
        timeout=TEXT2SQL_PLANNER_TIMEOUT_SECONDS,
    )


def compact_capability_results(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "capability_id": item.get("capability_id", "unknown"),
            "status": item.get("status", "error"),
            "summary": item.get("summary", ""),
        }
        for item in state.get("capability_results", [])
    ]


async def select_capabilities_node(state: AgentState) -> AgentState:
    capabilities = available_capabilities()
    selection = await select_capabilities_with_model(
        state["question"],
        capabilities,
        capability_planner_completion,
        compact_capability_results(state),
    )
    state["selected_capabilities"] = selection.capability_ids
    state["planning_summary"] = selection.summary
    state["planner_mode"] = "model"
    state["capability_plan"] = []
    state["should_replan"] = False
    return state


async def build_capability_plan_node(state: AgentState) -> AgentState:
    selected_ids = state.get("selected_capabilities", [])
    if not selected_ids:
        state["capability_plan"] = []
        return state
    definitions = {item.id: item for item in available_capabilities()}
    selected = [definitions[item_id] for item_id in selected_ids]
    plan = await build_plan_with_model(
        state["question"],
        selected,
        capability_planner_completion,
        compact_capability_results(state),
    )
    state["capability_plan"] = [item.model_dump() for item in plan.steps]
    return state


async def execute_rag_capability(
    definition: CapabilityDefinition,
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> CapabilityResult:
    from . import main

    started = time.perf_counter()
    search = main.rag_search(
        SearchRequest(
            user_id=context["user_id"],
            query=arguments["query"],
            knowledge_base_ids=context.get("knowledge_base_ids", []),
            top_k=arguments.get("top_k", 5),
        )
    )
    context["search"] = search
    results = search.get("results", [])
    citations = [
        {
            "type": "rag",
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "knowledge_base_id": item["knowledge_base_id"],
            "filename": item["filename"],
            "score": item["score"],
            "text": item["text"],
        }
        for item in results
    ]
    return CapabilityResult(
        capability_id=definition.id,
        name=definition.name,
        status="ok",
        summary=f"RAG 检索完成，命中 {len(results)} 个片段。",
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        data={"result_count": len(results)},
        citations=citations,
    )


async def execute_sql_capability(
    definition: CapabilityDefinition,
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> CapabilityResult:
    started = time.perf_counter()
    context["_suppress_tool_events"] = True
    try:
        await run_sql_pipeline(context)
    finally:
        context.pop("_suppress_tool_events", None)
    result = context.get("sql", {})
    status = "error" if result.get("error") or result.get("denied") or result.get("clarify") else "ok"
    citation = {
        "type": "sql",
        "summary": result.get("summary", ""),
        "row_count": result.get("row_count", 0),
        "scope": result.get("scope", "unknown"),
        "domain": result.get("domain", "unknown"),
        "planner": result.get("planner", "unknown"),
    }
    return CapabilityResult(
        capability_id=definition.id,
        name=definition.name,
        status=status,
        summary=result.get("summary", "结构化查询未完成。"),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        data={key: citation[key] for key in ("row_count", "scope", "domain", "planner")},
        citations=[citation],
    )


def capability_dispatcher() -> CapabilityDispatcher:
    return CapabilityDispatcher(
        handlers={"rag_search": execute_rag_capability, "sql_query": execute_sql_capability},
        services={"backend-java": JAVA_TOOL_BASE_URL},
        internal_token=AGENT_INTERNAL_TOKEN,
    )


async def execute_capability_plan_node(state: AgentState) -> AgentState:
    definitions = CAPABILITY_REGISTRY.by_id()
    dispatcher = capability_dispatcher()
    state.setdefault("capability_results", [])
    state.setdefault("executed_capability_keys", [])
    state.setdefault("execution_count", 0)
    executed = set(state["executed_capability_keys"])

    for raw_step in state.get("capability_plan", []):
        if state["execution_count"] >= MAX_TOOL_EXECUTIONS:
            break
        capability_id = str(raw_step["capability_id"])
        arguments = dict(raw_step.get("arguments", {}))
        key = execution_key(PlanStep(step_id=str(raw_step["step_id"]), capability_id=capability_id, arguments=arguments))
        if key in executed:
            result = CapabilityResult(
                capability_id=capability_id,
                name=definitions[capability_id].name,
                status="error",
                summary="已阻止重复执行相同能力和参数。",
            )
        else:
            executed.add(key)
            state["executed_capability_keys"].append(key)
            state["execution_count"] += 1
            state.setdefault("tool_calls", []).append({"name": capability_id, "arguments": arguments})
            try:
                result = await dispatcher.execute(definitions[capability_id], arguments, state)
            except Exception as ex:
                logger.warning("Capability execution failed capability=%s error=%s", capability_id, type(ex).__name__)
                result = CapabilityResult(
                    capability_id=capability_id,
                    name=definitions[capability_id].name,
                    status="error",
                    summary=f"能力执行失败：{type(ex).__name__}",
                )
        payload = result.model_dump()
        state["capability_results"].append(payload)
        state.setdefault("tool_results", []).append(
            {
                "name": capability_id,
                "status": result.status,
                "summary": result.summary,
                "elapsed_ms": result.elapsed_ms,
                "data": result.data,
            }
        )
    return state


async def evaluate_capability_results_node(state: AgentState) -> AgentState:
    if not state.get("selected_capabilities"):
        state["evaluation"] = {"decision": "complete", "summary": state.get("planning_summary", "")}
        state["should_replan"] = False
        return state
    try:
        evaluation = await evaluate_results_with_model(
            state["question"],
            compact_capability_results(state),
            capability_planner_completion,
        )
    except Exception:
        successful = any(item.get("status") == "ok" for item in state.get("capability_results", []))
        decision = "complete" if successful else "clarify"
        evaluation = type("Evaluation", (), {"decision": decision, "summary": "工具结果不足，请补充查询条件。"})()
    state["evaluation"] = {"decision": evaluation.decision, "summary": evaluation.summary}
    can_replan = (
        evaluation.decision == "replan"
        and state.get("replan_count", 0) < MAX_REPLANS
        and state.get("execution_count", 0) < MAX_TOOL_EXECUTIONS
    )
    state["should_replan"] = can_replan
    if can_replan:
        state["replan_count"] = state.get("replan_count", 0) + 1
    elif evaluation.decision in {"replan", "clarify"}:
        state["clarification"] = evaluation.summary or "现有信息不足，请补充查询条件。"
    return state


def next_after_capability_selection(state: AgentState) -> str:
    return "compose_capability_answer" if not state.get("selected_capabilities") else "build_capability_plan"


def next_after_capability_evaluation(state: AgentState) -> str:
    return "select_capabilities" if state.get("should_replan") else "compose_capability_answer"


def capability_route(state: AgentState) -> str:
    capability_ids = {item.get("capability_id", "") for item in state.get("capability_results", [])}
    if not capability_ids:
        return "direct"
    categories = set()
    if "rag.search.v1" in capability_ids:
        categories.add("rag")
    if "sql.query.v1" in capability_ids:
        categories.add("sql")
    if "document.status.v1" in capability_ids:
        categories.add("java")
    return next(iter(categories)) if len(categories) == 1 else "mixed"


async def generate_capability_answer(state: AgentState) -> str:
    from . import main

    clarification = state.get("clarification", "")
    if clarification:
        return clarification
    history = state.get("history", [])
    results = state.get("capability_results", [])
    if not results:
        try:
            return await model_client.complete_text(
                base_url=main.MODEL_BASE_URL,
                api_key=main.MODEL_API_KEY,
                model=main.MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是企业知识助手。直接、简洁地回答，不要虚构业务数据。"},
                    *history[-6:],
                    {"role": "user", "content": state["question"]},
                ],
                temperature=0.2,
            )
        except Exception:
            return "我是企业知识库 Agent，可以检索授权知识、查询结构化数据和文档索引状态。"

    evidence = {
        "capability_results": [
            {
                "capability_id": item.get("capability_id"),
                "status": item.get("status"),
                "summary": item.get("summary"),
                "data": item.get("data", {}),
            }
            for item in results
        ],
        "sql_rows": state.get("sql", {}).get("rows", []),
        "rag_passages": [
            {"filename": item.get("filename"), "text": item.get("text"), "score": item.get("score")}
            for item in state.get("search", {}).get("results", [])
        ],
    }
    try:
        return await model_client.complete_text(
            base_url=main.MODEL_BASE_URL,
            api_key=main.MODEL_API_KEY,
            model=main.MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是企业知识库 Agent。仅根据给定的工具证据回答，先给结论再简要说明依据。"
                        "不要输出 SQL、JSON、内部字段映射或隐藏推理；证据不足时明确说明。"
                    ),
                },
                *history[-6:],
                {
                    "role": "user",
                    "content": f"问题：{state['question']}\n\n工具证据：\n{json.dumps(evidence, ensure_ascii=False, default=str)}",
                },
            ],
            temperature=0.2,
        )
    except Exception:
        http_results = [item for item in results if item.get("capability_id") == "document.status.v1" and item.get("status") == "ok"]
        if http_results:
            data = http_results[-1].get("data", {})
            return (
                f"文档 {data.get('id', '')}（{data.get('filename', '未知文件')}）当前状态为 "
                f"{data.get('status', '未知')}，已生成 {data.get('chunkCount', data.get('chunk_count', 0))} 个切片。"
            )
        return fallback_tool_answer(
            state["question"],
            state.get("sql", {}).get("rows", []),
            state.get("search", {}).get("results", []),
        )


async def compose_capability_answer_node(state: AgentState) -> AgentState:
    state["route"] = capability_route(state)
    state["answer"] = await generate_capability_answer(state)
    state.setdefault("tool_calls", []).append({"name": "final_answer", "arguments": {"route": state["route"]}})
    state.setdefault("tool_results", []).append(
        {"name": "final_answer", "status": "ok", "summary": "已汇总能力结果并生成最终回答。", "elapsed_ms": 0, "data": {}}
    )
    return state


async def load_memory_node(state: AgentState) -> AgentState:
    from . import main

    history = main.MEMORY.setdefault(state["session_id"], [])
    state["history"] = history[-6:]
    state.setdefault("tool_results", []).append(
        {"name": "conversation_memory", "status": "ok", "summary": f"已加载 {len(state['history'])} 条历史消息。", "elapsed_ms": 0, "data": {}}
    )
    return state


async def route_node(state: AgentState) -> AgentState:
    state["route"] = route_intent(state["question"])
    return state


def next_after_route(state: AgentState) -> str:
    route = state.get("route", "rag")
    if route == "sql" or route == "mixed":
        return "retrieve_semantics"
    if route == "direct":
        return "compose_answer"
    return "rag_tool"


def next_after_semantics(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "extract_entities"


def next_after_entities(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "plan_query"


def next_after_plan(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "validate_plan"


def next_after_validation(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "apply_policy"


def next_after_policy(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "compile_sql"


def next_after_compile(state: AgentState) -> str:
    return "compose_answer" if state.get("sql") else "execute_sql"


def next_after_sql(state: AgentState) -> str:
    return "rag_tool" if state.get("route") == "mixed" else "compose_answer"


async def compose_answer_node(state: AgentState) -> AgentState:
    from . import main

    route = state.get("route", "rag")
    contexts = state.get("search", {}).get("results", [])
    history = state.get("history", [])
    if route == "direct":
        state["answer"] = "我是企业知识库 Agent，可以帮你查询授权知识库内容，也可以查询系统中的知识库、文档状态和会话统计。"
    elif route in ("sql", "mixed"):
        sql_result = state.get("sql", {})
        if sql_result.get("denied") or sql_result.get("clarify") or sql_result.get("error"):
            state["answer"] = sql_result.get("summary", "结构化查询未完成。")
        else:
            rows = sql_result.get("rows", [])
            state["answer"] = await generate_tool_answer(state["question"], rows, contexts, history)
    else:
        state["answer"] = await main.generate_answer(state["question"], contexts, history)
    state.setdefault("tool_calls", []).append({"name": "final_answer", "arguments": {"route": route}})
    state.setdefault("tool_results", []).append(
        {"name": "final_answer", "status": "ok", "summary": "已汇总工具结果并生成最终回答。", "elapsed_ms": 0, "data": {}}
    )
    return state


async def persist_memory_node(state: AgentState) -> AgentState:
    from . import main

    history = main.MEMORY.setdefault(state["session_id"], [])
    history.append({"role": "user", "content": state["question"]})
    history.append({"role": "assistant", "content": state.get("answer", "")})
    return state


async def run_legacy_agent_graph(request: ChatRequest, persist: bool = True) -> dict[str, Any]:
    initial: AgentState = {
        "question": request.question,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "knowledge_base_ids": request.knowledge_base_ids,
        "tool_calls": [],
        "tool_results": [],
    }
    if StateGraph is not None:
        try:
            graph = StateGraph(AgentState)
            graph.add_node("load_memory", load_memory_node)
            graph.add_node("route_intent", route_node)
            graph.add_node("retrieve_semantics", retrieve_semantics_node)
            graph.add_node("extract_entities", extract_entities_node)
            graph.add_node("plan_query", plan_query_node)
            graph.add_node("validate_plan", validate_plan_node)
            graph.add_node("apply_policy", apply_policy_node)
            graph.add_node("compile_sql", compile_sql_node)
            graph.add_node("execute_sql", execute_sql_node)
            graph.add_node("rag_tool", run_rag_tool)
            graph.add_node("compose_answer", compose_answer_node)
            graph.add_node("persist_memory", persist_memory_node)
            graph.set_entry_point("load_memory")
            graph.add_edge("load_memory", "route_intent")
            graph.add_conditional_edges("route_intent", next_after_route)
            graph.add_conditional_edges("retrieve_semantics", next_after_semantics)
            graph.add_conditional_edges("extract_entities", next_after_entities)
            graph.add_conditional_edges("plan_query", next_after_plan)
            graph.add_conditional_edges("validate_plan", next_after_validation)
            graph.add_conditional_edges("apply_policy", next_after_policy)
            graph.add_conditional_edges("compile_sql", next_after_compile)
            graph.add_conditional_edges("execute_sql", next_after_sql)
            graph.add_edge("rag_tool", "compose_answer")
            if persist:
                graph.add_edge("compose_answer", "persist_memory")
                graph.add_edge("persist_memory", END)
            else:
                graph.add_edge("compose_answer", END)
            return await graph.compile().ainvoke(initial)
        except Exception:
            pass

    state = await load_memory_node(initial)
    state = await route_node(state)
    if state["route"] in ("sql", "mixed"):
        state = await run_sql_pipeline(state)
    if state["route"] == "rag" or (state["route"] == "mixed" and not state.get("sql", {}).get("error") and not state.get("sql", {}).get("denied")):
        state = await run_rag_tool(state)
    state = await compose_answer_node(state)
    return await persist_memory_node(state) if persist else state


async def run_capability_agent_graph(request: ChatRequest, persist: bool = True) -> dict[str, Any]:
    initial: AgentState = {
        "question": request.question,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "knowledge_base_ids": request.knowledge_base_ids,
        "tool_calls": [],
        "tool_results": [],
        "capability_results": [],
        "selected_capabilities": [],
        "capability_plan": [],
        "planner_mode": "model",
        "replan_count": 0,
        "execution_count": 0,
        "executed_capability_keys": [],
    }
    if StateGraph is not None:
        graph = StateGraph(AgentState)
        graph.add_node("load_memory", load_memory_node)
        graph.add_node("select_capabilities", select_capabilities_node)
        graph.add_node("build_capability_plan", build_capability_plan_node)
        graph.add_node("execute_capability_plan", execute_capability_plan_node)
        graph.add_node("evaluate_capability_results", evaluate_capability_results_node)
        graph.add_node("compose_capability_answer", compose_capability_answer_node)
        graph.add_node("persist_memory", persist_memory_node)
        graph.set_entry_point("load_memory")
        graph.add_edge("load_memory", "select_capabilities")
        graph.add_conditional_edges("select_capabilities", next_after_capability_selection)
        graph.add_edge("build_capability_plan", "execute_capability_plan")
        graph.add_edge("execute_capability_plan", "evaluate_capability_results")
        graph.add_conditional_edges("evaluate_capability_results", next_after_capability_evaluation)
        if persist:
            graph.add_edge("compose_capability_answer", "persist_memory")
            graph.add_edge("persist_memory", END)
        else:
            graph.add_edge("compose_capability_answer", END)
        return await graph.compile().ainvoke(initial, config={"recursion_limit": 20})

    state = await load_memory_node(initial)
    while True:
        state = await select_capabilities_node(state)
        if not state.get("selected_capabilities"):
            break
        state = await build_capability_plan_node(state)
        state = await execute_capability_plan_node(state)
        state = await evaluate_capability_results_node(state)
        if not state.get("should_replan"):
            break
    state = await compose_capability_answer_node(state)
    return await persist_memory_node(state) if persist else state


async def run_agent_graph(request: ChatRequest, persist: bool = True) -> dict[str, Any]:
    from . import main

    if main.MODEL_API_KEY:
        try:
            return await run_capability_agent_graph(request, persist=persist)
        except Exception as ex:
            logger.warning("Capability planning failed; using deterministic fallback: %s", type(ex).__name__)
    state = await run_legacy_agent_graph(request, persist=persist)
    state["planner_mode"] = "fallback"
    state.setdefault("selected_capabilities", [])
    state.setdefault("capability_plan", [])
    state.setdefault("replan_count", 0)
    return state


def build_agent_response(state: dict[str, Any]) -> AgentResponse:
    from . import main

    results = state.get("search", {}).get("results", [])
    capability_results = state.get("capability_results", [])
    citations = [citation for result in capability_results for citation in result.get("citations", [])]
    if not capability_results:
        citations = [
            {
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "knowledge_base_id": item["knowledge_base_id"],
                "filename": item["filename"],
                "score": item["score"],
                "text": item["text"],
            }
            for item in results
        ]
    if state.get("sql") and not any(item.get("type") == "sql" for item in citations):
        citations.append(
            {
                "type": "sql",
                "summary": state["sql"].get("summary", ""),
                "row_count": state["sql"].get("row_count", 0),
                "scope": state["sql"].get("scope", "unknown"),
                "domain": state["sql"].get("domain", "unknown"),
                "planner": state["sql"].get("planner", "unknown"),
            }
        )
    return AgentResponse(
        answer=state.get("answer") or main.compose_retrieval_answer(state.get("question", ""), results),
        citations=citations,
        tool_calls=state.get("tool_calls", []),
        tool_results=state.get("tool_results", []),
        route=state.get("route", "rag"),
        selected_capabilities=state.get("selected_capabilities", []),
        plan=state.get("capability_plan", []),
        planner_mode=state.get("planner_mode", "fallback"),
        replan_count=state.get("replan_count", 0),
    )


async def stream_agent_events(request: ChatRequest) -> AsyncIterator[tuple[str, str]]:
    from . import main
    state = await run_agent_graph(request, persist=False)
    if state.get("planner_mode") == "model":
        yield "plan", main.json.dumps(
            {
                "selected_capabilities": state.get("selected_capabilities", []),
                "steps": state.get("capability_plan", []),
                "summary": state.get("planning_summary", ""),
                "replan_count": state.get("replan_count", 0),
            },
            ensure_ascii=False,
        )
    for call in state.get("tool_calls", []):
        if call.get("name") != "final_answer":
            yield "tool", str(call.get("name", "tool"))
    for result in state.get("tool_results", []):
        if result.get("name") != "final_answer":
            yield "tool_result", main.json.dumps(result, ensure_ascii=False)
    response = build_agent_response(state)
    for citation in response.citations:
        safe_citation = dict(citation)
        if "text" in safe_citation:
            safe_citation["text"] = str(safe_citation["text"])[:180]
        yield "citation", main.json.dumps(safe_citation, ensure_ascii=False)
    answer = state.get("answer", "")
    for token in answer.split():
        yield "token", f"{token} "
        await asyncio.sleep(0.01)
    await persist_memory_node(state)
    yield "done", "[DONE]"
