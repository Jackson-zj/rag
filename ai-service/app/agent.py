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


async def run_agent_graph(request: ChatRequest, persist: bool = True) -> dict[str, Any]:
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


def build_agent_response(state: dict[str, Any]) -> AgentResponse:
    from . import main

    results = state.get("search", {}).get("results", [])
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
    if state.get("sql"):
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
    )


async def stream_agent_events(request: ChatRequest) -> AsyncIterator[tuple[str, str]]:
    from . import main

    state = await load_memory_node(
        {
            "question": request.question,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "knowledge_base_ids": request.knowledge_base_ids,
            "tool_calls": [],
            "tool_results": [],
        }
    )
    state = await route_node(state)

    async def emit_last_result() -> AsyncIterator[tuple[str, str]]:
        result = state.get("tool_results", [])[-1]
        yield "tool_result", main.json.dumps(result, ensure_ascii=False)

    if state["route"] in ("sql", "mixed"):
        yield "tool", "sql_query"
        state = await run_sql_pipeline(state)
        async for event in emit_last_result():
            yield event
    if state["route"] == "rag" or (state["route"] == "mixed" and not state.get("sql", {}).get("error") and not state.get("sql", {}).get("denied")):
        yield "tool", "rag_search"
        state = await run_rag_tool(state)
        async for event in emit_last_result():
            yield event
        for item in state.get("search", {}).get("results", [])[:5]:
            yield "citation", main.json.dumps(
                {"type": "rag", "filename": item["filename"], "score": item["score"], "text": item["text"][:180]},
                ensure_ascii=False,
            )
    if state.get("sql"):
        yield "citation", main.json.dumps(
            {
                "type": "sql",
                "summary": state["sql"].get("summary", ""),
                "row_count": state["sql"].get("row_count", 0),
                "scope": state["sql"].get("scope", "unknown"),
                "domain": state["sql"].get("domain", "unknown"),
                "planner": state["sql"].get("planner", "unknown"),
            },
            ensure_ascii=False,
        )

    state = await compose_answer_node(state)
    answer = state.get("answer", "")
    for token in answer.split():
        yield "token", f"{token} "
        await asyncio.sleep(0.01)
    await persist_memory_node(state)
    yield "done", "[DONE]"
