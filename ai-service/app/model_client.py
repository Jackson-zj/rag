import json
import re
from typing import Any

import httpx


def extract_json_object(content: str) -> dict[str, Any]:
    clean = content.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model response did not contain a JSON object")
        value = json.loads(clean[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


async def complete_text(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    timeout: float = 30,
) -> str:
    if not api_key:
        raise RuntimeError("Model API key is not configured")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise ValueError("Model returned empty content")
        return content.strip()


async def complete_json(**kwargs: Any) -> dict[str, Any]:
    return extract_json_object(await complete_text(**kwargs))

