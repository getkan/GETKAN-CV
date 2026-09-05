"""OpenRouter JSON-schema transport adapter."""

from __future__ import annotations

from typing import Any

import requests


def post_json_schema(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    title: str,
    timeout: int,
    strict: bool = False,
) -> str:
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://github.com/GETKAN-CV", "X-Title": title},
        json={
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": strict, "schema": schema}},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
