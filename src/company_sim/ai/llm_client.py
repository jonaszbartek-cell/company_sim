"""Local LLM HTTP client (Ollama-compatible /api/chat with tools)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b-instruct"
    timeout_sec: float = 45.0
    max_tool_rounds: int = 4

    @classmethod
    def from_env(cls) -> LLMConfig:
        enabled_raw = os.environ.get("COMPANY_SIM_LLM", "0").strip().lower()
        enabled = enabled_raw in {"1", "true", "yes", "on"}
        return cls(
            enabled=enabled,
            base_url=os.environ.get("COMPANY_SIM_LLM_URL", "http://127.0.0.1:11434").rstrip("/"),
            model=os.environ.get("COMPANY_SIM_LLM_MODEL", "qwen2.5:3b-instruct"),
            timeout_sec=float(os.environ.get("COMPANY_SIM_LLM_TIMEOUT", "45")),
            max_tool_rounds=int(os.environ.get("COMPANY_SIM_LLM_MAX_ROUNDS", "4")),
        )


@dataclass
class LLMResponse:
    message: dict[str, Any]
    raw: dict[str, Any]


class LLMClient:
    """Thin client for Ollama chat + tools. Sync; call from a worker thread."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    def available(self) -> bool:
        if not self.config.enabled:
            return False
        try:
            req = urllib.request.Request(f"{self.config.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            return False

    def chat(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if messages:
            msgs.extend(messages)
        else:
            msgs.append({"role": "user", "content": user})

        payload = {
            "model": self.config.model,
            "messages": msgs,
            "tools": tools,
            "stream": False,
            # Prefer tool calls when the model supports it (Ollama OpenAI-compat).
            "tool_choice": "auto",
            "options": {
                "temperature": 0.1,
                "num_predict": 192,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_sec) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {body[:300]}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        message = raw.get("message") or {}
        return LLMResponse(message=message, raw=raw)


def parse_tool_calls(message: dict[str, Any]) -> list[tuple[str, dict[str, Any], str | None]]:
    """Return list of (name, arguments, tool_call_id)."""
    out: list[tuple[str, dict[str, Any], str | None]] = []
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        out.append((name, args, tc.get("id")))
    # Fallback: some small models emit {"name": "...", "arguments": {...}} as content
    if not out:
        content = (message.get("content") or "").strip()
        if content.startswith("{") and '"name"' in content:
            try:
                obj = json.loads(content)
                name = obj.get("name") or (obj.get("function") or {}).get("name")
                args = obj.get("arguments") or obj.get("parameters") or {}
                if isinstance(args, str):
                    args = json.loads(args) if args.strip() else {}
                if name:
                    out.append((str(name), dict(args) if isinstance(args, dict) else {}, None))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    return out
