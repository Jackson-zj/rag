from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    filename: str
    content: str


class IndexRequest(BaseModel):
    document_id: str
    knowledge_base_id: str
    filename: str
    content: str
    content_hash: str | None = None
    allowed_user_ids: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    user_id: str
    query: str
    knowledge_base_ids: list[str]
    top_k: int = 5


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    knowledge_base_ids: list[str]


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    status: Literal["ok", "error"]
    summary: str
    elapsed_ms: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    route: str = "rag"


class AgentState(TypedDict, total=False):
    question: str
    user_id: str
    session_id: str
    knowledge_base_ids: list[str]
    route: str
    history: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    search: dict[str, Any]
    sql: dict[str, Any]
    answer: str
    semantic_domains: list[str]
    locked_constraints: Any
    query_plan: Any
    secured_plan: Any
    planner: str
    principal: dict[str, Any]
    compiled_query: Any
    sql_started: float
    sql_scope: str
