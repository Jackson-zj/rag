import asyncio
import hashlib
import json
import math
import os
import re
from typing import Any, TypedDict

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

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

app = FastAPI(title="Enterprise RAG AI Service", version="0.1.0")
Instrumentator().instrument(app).expose(app)

VECTOR_DIM = int(os.getenv("VECTOR_DIM", "64"))
VECTOR_DATABASE_URL = os.getenv("VECTOR_DATABASE_URL", "")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL_API_KEY = os.getenv("MODEL_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.7-plus")

CHUNKS: list[dict[str, Any]] = []
MEMORY: dict[str, list[dict[str, str]]] = {}


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


class AgentResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    search: dict[str, Any]
    answer: str


def readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    readable = re.findall(r"[\w\s\u4e00-\u9fff，。！？；：、（）《》“”'\".,!?;:()\[\]\-]", text, re.UNICODE)
    return len(readable) / len(text)


def is_readable_text(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    replacement_count = clean.count("\ufffd")
    control_count = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", clean))
    if replacement_count + control_count > max(3, len(clean) * 0.08):
        return False
    if re.search(r"(?:QE[\x00-\x1f]?){3,}", clean):
        return False
    return readable_ratio(clean) >= 0.55


def clean_document_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"(?:\bQE\b\s*){2,}", " ", text)
    text = text.replace("\ufffd", " ")
    lines = []
    for line in re.split(r"[\r\n]+", text):
        clean = " ".join(line.split())
        if re.fullmatch(r"Page\s+\d+", clean, re.IGNORECASE):
            continue
        if re.fullmatch(r"[—\-–-]?\s*\d+\s*[—\-–-]?", clean):
            continue
        if re.fullmatch(r"第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?", clean):
            continue
        if is_readable_text(clean):
            lines.append(clean)
    return "\n".join(lines).strip()


STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "及",
    "或",
    "在",
    "是",
    "有",
    "多少",
    "怎么",
    "如何",
    "什么",
    "一下",
    "可以",
    "需要",
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    lowered = text.lower()
    tokens.extend(re.findall(r"[a-z0-9]+", lowered))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(segment) == 1:
            tokens.append(segment)
            continue
        tokens.extend(segment)
        tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        tokens.extend(segment[index : index + 3] for index in range(len(segment) - 2))
    return [token for token in tokens if token and token not in STOPWORDS]


def split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def split_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    cleaned = clean_document_text(text)
    if not cleaned:
        return []

    units = []
    for line in cleaned.splitlines():
        line = " ".join(line.split())
        if not line:
            continue
        parts = re.split(r"(?<=[。！？.!?；;])\s*", line)
        units.extend(part.strip() for part in parts if part.strip())

    if not units:
        return split_long_text(" ".join(cleaned.split()), chunk_size, overlap)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        if len(unit) > chunk_size:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.extend(split_long_text(unit, chunk_size, overlap))
            continue
        if current and current_len + len(unit) + 1 > chunk_size:
            chunks.append(" ".join(current))
            overlap_units: list[str] = []
            overlap_len = 0
            for previous in reversed(current):
                if overlap_len + len(previous) > overlap:
                    break
                overlap_units.insert(0, previous)
                overlap_len += len(previous)
            current = overlap_units
            current_len = sum(len(item) for item in current)
        current.append(unit)
        current_len += len(unit) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def embed(text: str) -> list[float]:
    vector = [0.0 for _ in range(VECTOR_DIM)]
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % VECTOR_DIM
        vector[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def postgres_enabled() -> bool:
    return bool(VECTOR_DATABASE_URL)


def postgres_connection():
    if psycopg is None or dict_row is None:
        raise RuntimeError("VECTOR_DATABASE_URL is configured, but psycopg is not installed")
    return psycopg.connect(VECTOR_DATABASE_URL, row_factory=dict_row)


def stable_content_hash(content: str) -> str:
    normalized = "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def vector_sql_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.10f}" for value in vector) + "]"


def ensure_postgres_knowledge_base(cursor, knowledge_base_id: str) -> None:
    cursor.execute(
        """
        INSERT INTO knowledge_bases (id, name, description)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (knowledge_base_id, knowledge_base_id, "Created by AI indexing service"),
    )


def index_document_in_memory(request: IndexRequest, chunks: list[str]) -> dict[str, Any]:
    CHUNKS[:] = [chunk for chunk in CHUNKS if chunk["document_id"] != request.document_id]
    for position, chunk in enumerate(chunks):
        CHUNKS.append(
            {
                "chunk_id": f"{request.document_id}-{position}",
                "document_id": request.document_id,
                "knowledge_base_id": request.knowledge_base_id,
                "filename": request.filename,
                "position": position,
                "text": chunk,
                "embedding": embed(chunk),
                "allowed_user_ids": request.allowed_user_ids,
            }
        )
    return {"document_id": request.document_id, "status": "READY", "chunk_count": len(chunks), "duplicate": False}


def index_document_in_postgres(request: IndexRequest) -> dict[str, Any]:
    content_hash = request.content_hash or stable_content_hash(request.content)
    with postgres_connection() as connection:
        with connection.cursor() as cursor:
            ensure_postgres_knowledge_base(cursor, request.knowledge_base_id)
            cursor.execute(
                """
                SELECT id, status, chunk_count
                FROM documents
                WHERE knowledge_base_id = %s AND content_hash = %s
                """,
                (request.knowledge_base_id, content_hash),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return {
                    "document_id": existing["id"],
                    "status": existing["status"],
                    "chunk_count": existing["chunk_count"],
                    "duplicate": True,
                }

            chunks = split_text(request.content)
            try:
                cursor.execute(
                    """
                    INSERT INTO documents (id, knowledge_base_id, filename, status, content_hash, chunk_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (request.document_id, request.knowledge_base_id, request.filename, "READY", content_hash, len(chunks)),
                )
            except Exception:
                connection.rollback()
                with connection.cursor() as retry_cursor:
                    retry_cursor.execute(
                        """
                        SELECT id, status, chunk_count
                        FROM documents
                        WHERE knowledge_base_id = %s AND content_hash = %s
                        """,
                        (request.knowledge_base_id, content_hash),
                    )
                    existing = retry_cursor.fetchone()
                    if existing is not None:
                        return {
                            "document_id": existing["id"],
                            "status": existing["status"],
                            "chunk_count": existing["chunk_count"],
                            "duplicate": True,
                        }
                raise

            for position, chunk in enumerate(chunks):
                cursor.execute(
                    """
                    INSERT INTO document_chunks
                        (id, document_id, knowledge_base_id, filename, position, content, embedding, allowed_user_ids)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)
                    """,
                    (
                        f"{request.document_id}-{position}",
                        request.document_id,
                        request.knowledge_base_id,
                        request.filename,
                        position,
                        chunk,
                        vector_sql_literal(embed(chunk)),
                        request.allowed_user_ids,
                    ),
                )
    return {"document_id": request.document_id, "status": "READY", "chunk_count": len(chunks), "duplicate": False}


def search_chunks_in_memory(request: SearchRequest, query_vector: list[float]) -> list[dict[str, Any]]:
    visible = []
    for chunk in CHUNKS:
        if chunk["knowledge_base_id"] not in request.knowledge_base_ids:
            continue
        if chunk["allowed_user_ids"] and request.user_id not in chunk["allowed_user_ids"]:
            continue
        if not is_readable_text(chunk["text"]):
            continue
        vector_score = cosine(query_vector, chunk["embedding"])
        visible.append({**chunk, "vector_score": vector_score})
    visible.sort(key=lambda item: item["vector_score"], reverse=True)
    return visible


def search_chunks_in_postgres(request: SearchRequest, query_vector: list[float]) -> list[dict[str, Any]]:
    if not request.knowledge_base_ids:
        return []
    limit = max(request.top_k * 8, request.top_k)
    with postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id AS chunk_id,
                    document_id,
                    knowledge_base_id,
                    filename,
                    position,
                    content AS text,
                    allowed_user_ids,
                    1 - (embedding <=> %s::vector) AS vector_score
                FROM document_chunks
                WHERE knowledge_base_id = ANY(%s)
                  AND (cardinality(allowed_user_ids) = 0 OR %s = ANY(allowed_user_ids))
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    vector_sql_literal(query_vector),
                    request.knowledge_base_ids,
                    request.user_id,
                    vector_sql_literal(query_vector),
                    limit,
                ),
            )
            rows = cursor.fetchall()
    return [dict(row) for row in rows if is_readable_text(str(row["text"]))]


def lexical_overlap_score(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    text_tokens = set(tokenize(text))
    if not query_tokens or not text_tokens:
        return 0.0
    weighted_hits = sum(len(token) for token in query_tokens & text_tokens)
    weighted_total = sum(len(token) for token in query_tokens)
    return weighted_hits / max(1, weighted_total)


def phrase_match_score(query: str, text: str) -> float:
    phrases = [token for token in set(tokenize(query)) if len(token) >= 2]
    if not phrases:
        return 0.0
    hits = sum(1 for phrase in phrases if phrase in text)
    return hits / len(phrases)


def question_intent_bonus(query: str, text: str) -> float:
    bonus = 0.0
    if re.search(r"多少|几|几天|多久|天数|额度|金额|比例", query):
        if re.search(r"\d+(?:\.\d+)?\s*(?:天|日|年|月|次|%|％|元|小时)", text):
            bonus += 0.18
    if re.search(r"怎么|如何|流程|申请|办理|提交", query):
        if re.search(r"申请|提交|审批|流程|证明|办理|系统|平台", text):
            bonus += 0.16
    if re.search(r"年假|年休假", query):
        if re.search(r"年假|年休假|休假", text):
            bonus += 0.22
    if re.search(r"病假", query):
        if re.search(r"病假|医疗|证明", text):
            bonus += 0.22
    return bonus


def rerank_score(query: str, item: dict[str, Any]) -> float:
    text = str(item["text"])
    vector_score = float(item.get("vector_score", item.get("score", 0.0)))
    lexical_score = lexical_overlap_score(query, text)
    phrase_score = phrase_match_score(query, text)
    intent_bonus = question_intent_bonus(query, text)
    return (0.45 * vector_score) + (0.35 * lexical_score) + (0.20 * phrase_score) + intent_bonus


def extract_measurements(question: str) -> tuple[int | None, float | None]:
    height = None
    weight = None

    height_match = re.search(r"(?:身高|高)\s*[:：]?\s*(\d{2,3})(?:\s*(?:cm|厘米|公分))?", question, re.IGNORECASE)
    if not height_match:
        height_match = re.search(r"(\d{2,3})\s*(?:cm|厘米|公分)", question, re.IGNORECASE)
    if not height_match and re.search(r"尺码|码数|衣服|穿搭|推荐", question, re.IGNORECASE):
        height_match = re.search(r"(?<!\d)(1[4-9]\d|20\d)(?!\d)", question)
    if height_match:
        height = int(height_match.group(1))

    weight_match = re.search(r"(?:体重|重)\s*[:：]?\s*(\d{2,3})(?:\s*(kg|公斤|千克|斤))?", question, re.IGNORECASE)
    if not weight_match:
        weight_match = re.search(r"(\d{2,3})\s*(kg|公斤|千克|斤)", question, re.IGNORECASE)
    if weight_match:
        weight = float(weight_match.group(1))
        unit = (weight_match.group(2) or "kg").lower()
        if unit == "斤":
            weight = weight / 2

    return height, weight


def parse_range(text: str, labels: str) -> tuple[float, float] | None:
    pattern = rf"(?:{labels})\s*[:：]?\s*(\d{{2,3}}(?:\.\d+)?)\s*(?:-|~|～|至|到)\s*(\d{{2,3}}(?:\.\d+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    start = float(match.group(1))
    end = float(match.group(2))
    return (min(start, end), max(start, end))


def extract_size_rules(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = []
    size_pattern = re.compile(r"(?<![A-Za-z0-9])(XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL)(?![A-Za-z0-9])", re.IGNORECASE)
    for context in contexts:
        text = str(context["text"])
        segments = [part.strip() for part in re.split(r"[\n\r;；。]", text) if part.strip()]
        for segment in segments:
            size_match = size_pattern.search(segment)
            height_range = parse_range(segment, r"身高|高度|高")
            weight_range = parse_range(segment, r"体重|重量|重")
            if size_match and height_range and weight_range:
                rules.append(
                    {
                        "size": size_match.group(1).upper(),
                        "height": height_range,
                        "weight": weight_range,
                        "filename": context["filename"],
                        "text": segment,
                    }
                )
    return rules


def score_size_rule(rule: dict[str, Any], height: int | None, weight: float | None) -> tuple[int, float]:
    matched = 0
    distance = 0.0
    if height is not None:
        low, high = rule["height"]
        if low <= height <= high:
            matched += 1
        else:
            distance += min(abs(height - low), abs(height - high))
    if weight is not None:
        low, high = rule["weight"]
        if low <= weight <= high:
            matched += 1
        else:
            distance += min(abs(weight - low), abs(weight - high))
    return matched, -distance


def body_shape_from_question(question: str) -> str | None:
    if re.search(r"瘦|偏瘦|较瘦|很瘦|苗条", question):
        return "slim"
    if re.search(r"胖|偏胖|壮|丰满|微胖", question):
        return "broad"
    return None


def choose_size_rule(rules: list[dict[str, Any]], height: int | None, weight: float | None, question: str) -> dict[str, Any] | None:
    if not rules:
        return None
    matched_rules = [rule for rule in rules if score_size_rule(rule, height, weight)[0] > 0]
    if not matched_rules:
        return None

    shape = body_shape_from_question(question)
    if weight is None and shape and height is not None:
        height_matches = [rule for rule in matched_rules if rule["height"][0] <= height <= rule["height"][1]]
        if height_matches:
            if shape == "slim":
                return min(height_matches, key=lambda rule: (rule["weight"][0], rule["weight"][1]))
            if shape == "broad":
                return max(height_matches, key=lambda rule: (rule["weight"][1], rule["weight"][0]))

    return max(matched_rules, key=lambda rule: score_size_rule(rule, height, weight))


def compose_size_answer(question: str, contexts: list[dict[str, Any]]) -> str | None:
    if not re.search(r"尺码|码数|size|穿多大|推荐.*码", question, re.IGNORECASE):
        return None

    height, weight = extract_measurements(question)
    if height is None and weight is None:
        return None

    rules = extract_size_rules(contexts)
    if not rules:
        return None

    best = choose_size_rule(rules, height, weight, question)
    if not best:
        return None

    profile_parts = []
    if height is not None:
        profile_parts.append(f"身高 {height}cm")
    if weight is not None:
        profile_parts.append(f"体重 {weight:g}kg")
    if body_shape_from_question(question) == "slim":
        profile_parts.append("体型偏瘦")
    elif body_shape_from_question(question) == "broad":
        profile_parts.append("体型偏壮")
    profile_text = "、".join(profile_parts) if profile_parts else "当前信息"
    h_low, h_high = best["height"]
    w_low, w_high = best["weight"]
    source = best["filename"]
    advice = f"根据尺码表，你的{profile_text}更适合 {best['size']} 码。"
    basis = f"依据：{source} 中 {best['size']} 码对应身高 {h_low:g}-{h_high:g}cm、体重 {w_low:g}-{w_high:g}kg。"

    if height is not None and weight is not None:
        weight_low, weight_high = best["weight"]
        if weight < weight_low:
            advice += " 你的体重在该尺码区间偏轻，如果喜欢修身或介于两个尺码之间，建议同时试穿小一码。"
        elif weight > weight_high:
            advice += " 你的体重在该尺码区间偏重，如果喜欢宽松或介于两个尺码之间，建议同时试穿大一码。"
    elif body_shape_from_question(question) == "slim":
        advice += " 你提到比较瘦，建议优先选这个区间里偏小或更修身的尺码。"
    elif body_shape_from_question(question) == "broad":
        advice += " 你提到体型偏壮，建议优先选这个区间里偏宽松的尺码。"

    return f"{advice}\n{basis}"


def split_context_segments(contexts: list[dict[str, Any]]) -> list[dict[str, str]]:
    segments = []
    for context in contexts:
        text = str(context["text"])
        for segment in re.split(r"[\n\r;；。]", text):
            clean = " ".join(segment.split())
            if clean:
                segments.append({"filename": str(context["filename"]), "text": clean})
    return segments


def compose_color_answer(question: str, contexts: list[dict[str, Any]]) -> str | None:
    if not re.search(r"颜色|配色|色系|肤色|偏白|白皙|显白|穿搭|衣服", question):
        return None

    segments = split_context_segments(contexts)
    if re.search(r"偏白|白皙|皮肤白|肤色白", question):
        preferred = [
            item
            for item in segments
            if re.search(r"偏白|白皙|皮肤白|肤色白|冷色|浅色|粉|蓝|绿|米白|卡其", item["text"])
        ]
        if preferred:
            evidence = preferred[0]
            return f"颜色建议：你肤色偏白，优先选择浅色或低饱和度色系，例如浅蓝、米白、浅灰、浅粉、雾霾蓝这类颜色，会更清爽显气色。\n依据：{evidence['text']}\n来源：{evidence['filename']}"

    color_segments = [item for item in segments if re.search(r"颜色|色系|黑|白|灰|蓝|绿|粉|卡其|米|藏蓝|亮色|深色|浅色", item["text"])]
    if not color_segments:
        return None

    evidence = color_segments[0]
    return f"颜色建议：可以按文档中的配色规则选择更适合你的色系，优先考虑文档提到的主色和搭配色。\n依据：{evidence['text']}\n来源：{evidence['filename']}"


def compose_clothing_answer(question: str, contexts: list[dict[str, Any]]) -> str | None:
    if not re.search(r"衣服|穿搭|颜色|尺码|码数|推荐", question):
        return None

    color_answer = compose_color_answer(question, contexts)
    size_answer = compose_size_answer(question, contexts)
    if not color_answer and not size_answer:
        return None

    parts = []
    if size_answer:
        parts.append(size_answer)
    if color_answer:
        parts.append(color_answer)
    return "\n\n".join(parts)


def compose_general_answer(question: str, contexts: list[dict[str, Any]]) -> str:
    sources = ", ".join(sorted({str(c["filename"]) for c in contexts}))
    ranked_sentences = []
    keyword_patterns = [token for token in set(tokenize(question)) if len(token) >= 2]

    for context in contexts:
        text = " ".join(clean_document_text(str(context["text"])).split())
        for sentence in re.split(r"(?<=[。！？.!?])\s*", text):
            if not sentence or not is_readable_text(sentence):
                continue
            score = lexical_overlap_score(question, sentence) + phrase_match_score(question, sentence) + question_intent_bonus(question, sentence)
            if any(keyword in sentence for keyword in keyword_patterns):
                score += 0.2
            ranked_sentences.append((score, sentence))

    ranked_sentences.sort(key=lambda item: item[0], reverse=True)
    sentences = [sentence for score, sentence in ranked_sentences if score > 0]
    if not sentences:
        sentences = [" ".join(str(context["text"]).split()) for context in contexts[:2] if is_readable_text(str(context["text"]))]

    evidence = "；".join(sentences[:3])
    if len(evidence) > 360:
        evidence = evidence[:357] + "..."
    if re.search(r"病假|请假", question) and evidence:
        return f"回答：病假一般需要按公司请假流程提交申请，并按制度要求提供病假或医疗相关证明；连续或长期病假需关注制度中的审批和工资计算规则。\n依据：{evidence}\n来源：{sources}"
    if re.search(r"多少|几|几天|多久|天数|额度|金额|比例", question) and evidence:
        return f"回答：相关制度中的数量/期限信息如下：{sentences[0]}\n依据：{evidence}\n来源：{sources}"
    return f"回答：{sentences[0] if sentences else '根据已召回的文档，可参考以下制度内容处理。'}\n依据：{evidence}\n来源：{sources}"


def compose_retrieval_answer(question: str, contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return "未在当前用户可访问的知识库中找到相关依据。"

    clothing_answer = compose_clothing_answer(question, contexts)
    if clothing_answer:
        return clothing_answer

    size_answer = compose_size_answer(question, contexts)
    if size_answer:
        return size_answer

    return compose_general_answer(question, contexts)


async def generate_answer(question: str, contexts: list[dict[str, Any]], history: list[dict[str, str]]) -> str:
    context_text = "\n".join(f"- {c['text']} (source: {c['filename']})" for c in contexts)
    fallback_answer = compose_retrieval_answer(question, contexts)
    if not contexts:
        return fallback_answer

    if MODEL_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{MODEL_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {MODEL_API_KEY}"},
                    json={
                        "model": MODEL_NAME,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "你是企业知识库问答助手。必须只依据给定 Context 回答用户问题。"
                                    "请先给出直接结论，再用1-3条要点概括依据；不要整段粘贴原文；"
                                    "不要输出页眉、页脚、页码或无关片段。证据不足时明确说明。"
                                ),
                            },
                            *history[-6:],
                            {"role": "user", "content": f"问题：{question}\n\n依据片段：\n{context_text}"},
                        ],
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"].get("content") or ""
                if content.strip():
                    return content.strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            pass

    return fallback_answer


def build_model_messages(question: str, context_text: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是企业知识库问答助手。必须只依据给定 Context 回答用户问题。"
                "请先给出直接结论，再用1-3条要点概括依据；不要整段粘贴原文；"
                "不要输出页眉、页脚、页码或无关片段。证据不足时明确说明。"
            ),
        },
        *history[-6:],
        {"role": "user", "content": f"问题：{question}\n\n依据片段：\n{context_text}"},
    ]


def format_sse(event: str, data: str) -> str:
    lines = str(data).replace("\r", "").split("\n")
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


async def stream_model_tokens(question: str, contexts: list[dict[str, Any]], history: list[dict[str, str]]):
    context_text = "\n".join(f"- {c['text']} (source: {c['filename']})" for c in contexts)
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{MODEL_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {MODEL_API_KEY}"},
            json={
                "model": MODEL_NAME,
                "messages": build_model_messages(question, context_text, history),
                "temperature": 0.2,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line.removeprefix("data:").strip()
                if not payload or payload == "[DONE]":
                    break
                try:
                    body = json.loads(payload)
                    delta = body["choices"][0].get("delta", {})
                    content = delta.get("content") or ""
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if content:
                    yield content


async def run_agent_graph(request: ChatRequest) -> dict[str, Any]:
    history = MEMORY.setdefault(request.session_id, [])

    async def memory_node(state: AgentState) -> AgentState:
        state["history"] = history[-6:]
        return state

    async def rag_tool_node(state: AgentState) -> AgentState:
        state["tool_calls"] = [{"name": "rag_search", "arguments": {"top_k": 5}}]
        state["search"] = rag_search(
            SearchRequest(
                user_id=request.user_id,
                query=request.question,
                knowledge_base_ids=request.knowledge_base_ids,
            )
        )
        return state

    async def answer_node(state: AgentState) -> AgentState:
        state["answer"] = await generate_answer(request.question, state["search"]["results"], state["history"])
        return state

    if StateGraph is not None:
        try:
            graph = StateGraph(AgentState)
            graph.add_node("memory", memory_node)
            graph.add_node("rag_tool", rag_tool_node)
            graph.add_node("compose_answer", answer_node)
            graph.set_entry_point("memory")
            graph.add_edge("memory", "rag_tool")
            graph.add_edge("rag_tool", "compose_answer")
            graph.add_edge("compose_answer", END)
            return await graph.compile().ainvoke({"question": request.question})
        except Exception:
            pass

    state: AgentState = {"question": request.question}
    state = await memory_node(state)
    state = await rag_tool_node(state)
    return await answer_node(state)


def build_agent_response(state: dict[str, Any]) -> AgentResponse:
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
    return AgentResponse(
        answer=state.get("answer") or compose_retrieval_answer(state.get("question", ""), results),
        citations=citations,
        tool_calls=state.get("tool_calls", []),
    )


@app.post("/ai/documents/parse")
def parse_document(request: ParseRequest) -> dict[str, Any]:
    chunks = split_text(request.content)
    return {"filename": request.filename, "chunk_count": len(chunks), "chunks": chunks}


@app.post("/ai/documents/index")
def index_document(request: IndexRequest) -> dict[str, Any]:
    if postgres_enabled():
        return index_document_in_postgres(request)
    return index_document_in_memory(request, split_text(request.content))


@app.post("/ai/rag/search")
def rag_search(request: SearchRequest) -> dict[str, Any]:
    query_vector = embed(request.query)
    visible = search_chunks_in_postgres(request, query_vector) if postgres_enabled() else search_chunks_in_memory(request, query_vector)
    candidates = visible[: max(request.top_k * 8, request.top_k)]
    for item in candidates:
        item["score"] = rerank_score(request.query, item)
    candidates.sort(key=lambda item: item["score"], reverse=True)
    results = [
        {
            "chunk_id": item["chunk_id"],
            "document_id": item["document_id"],
            "knowledge_base_id": item["knowledge_base_id"],
            "filename": item["filename"],
            "text": item["text"],
            "score": round(item["score"], 4),
            "vector_score": round(item["vector_score"], 4),
        }
        for item in candidates[: request.top_k]
    ]
    return {"query": request.query, "results": results}


@app.post("/ai/agent/run")
async def agent_run(request: ChatRequest) -> AgentResponse:
    history = MEMORY.setdefault(request.session_id, [])
    state = await run_agent_graph(request)
    response = build_agent_response(state)
    history.append({"role": "user", "content": request.question})
    history.append({"role": "assistant", "content": response.answer})
    return response


@app.post("/ai/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def events():
        history = MEMORY.setdefault(request.session_id, [])
        tool_call = {"name": "rag_search", "arguments": {"top_k": 5}}
        yield format_sse("tool", tool_call["name"])

        search = rag_search(
            SearchRequest(
                user_id=request.user_id,
                query=request.question,
                knowledge_base_ids=request.knowledge_base_ids,
            )
        )
        contexts = search["results"]
        answer_parts: list[str] = []

        if MODEL_API_KEY and contexts:
            try:
                async for token in stream_model_tokens(request.question, contexts, history):
                    answer_parts.append(token)
                    yield format_sse("token", token)
            except httpx.HTTPError as ex:
                print(f"Model streaming failed, falling back to local answer: {ex}")

        if not answer_parts:
            fallback_answer = compose_retrieval_answer(request.question, contexts)
            answer_parts.append(fallback_answer)
            for token in fallback_answer.split():
                yield format_sse("token", f"{token} ")
                await asyncio.sleep(0.01)

        answer = "".join(answer_parts)
        history.append({"role": "user", "content": request.question})
        history.append({"role": "assistant", "content": answer})
        yield format_sse("done", "[DONE]")

    return StreamingResponse(events(), media_type="text/event-stream")
