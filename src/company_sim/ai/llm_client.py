"""Local LLM HTTP client (Ollama-compatible /api/chat with tools)."""

from __future__ import annotations

import json
import os
import re
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
    # Default 16k: packed agent prompts + tool schemas exceed Ollama's 4k default,
    # which makes small models emit bare tool names instead of structured tool_calls.
    num_ctx: int = 16384

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
            num_ctx=int(os.environ.get("COMPANY_SIM_LLM_NUM_CTX", "16384")),
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
                "num_predict": 256,
                "num_ctx": max(2048, self.config.num_ctx),
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


_TOOL_CALL_XML_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)
_BARE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,64}$")
_CALL_LINE_RE = re.compile(
    r"^(?:call\s+|tool\s*:?\s*|function\s*:?\s*)?"
    r"([A-Za-z_][A-Za-z0-9_]{1,64})"
    r"(?:\s*\((.*)\))?\s*$",
    re.IGNORECASE,
)


def _parse_args_blob(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return dict(obj) if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    # Lightweight key=value / key: value pairs inside parentheses bodies
    out: dict[str, Any] = {}
    for part in re.split(r",(?=(?:[^\"']*[\"'][^\"']*[\"'])*[^\"']*$)", text):
        piece = part.strip()
        if not piece:
            continue
        if "=" in piece:
            k, v = piece.split("=", 1)
        elif ":" in piece:
            k, v = piece.split(":", 1)
        else:
            continue
        key = k.strip().strip("\"'")
        val = v.strip().strip("\"'")
        if not key:
            continue
        if re.fullmatch(r"-?\d+", val):
            out[key] = int(val)
        elif re.fullmatch(r"-?\d+\.\d+", val):
            out[key] = float(val)
        elif val.lower() in {"true", "false"}:
            out[key] = val.lower() == "true"
        else:
            out[key] = val
    return out


def _known_tool_names(known_tools: set[str] | None) -> set[str] | None:
    if known_tools is not None:
        return known_tools
    try:
        from company_sim.ai.tools import TOOL_DEFINITIONS, tool_name

        return {tool_name(d) for d in TOOL_DEFINITIONS}
    except Exception:  # noqa: BLE001
        return None


def _append_call(
    out: list[tuple[str, dict[str, Any], str | None]],
    name: str,
    args: dict[str, Any],
    call_id: str | None,
    known: set[str] | None,
) -> None:
    name = (name or "").strip()
    if not name:
        return
    if known is not None and name not in known:
        return
    out.append((name, args, call_id))


def parse_tool_calls(
    message: dict[str, Any],
    *,
    known_tools: set[str] | None = None,
) -> list[tuple[str, dict[str, Any], str | None]]:
    """Return list of (name, arguments, tool_call_id).

    Accepts structured Ollama/OpenAI tool_calls, plus fallbacks for small models
    that emit JSON, Qwen ``<tool_call>`` XML, or bare tool-name prose.
    """
    out: list[tuple[str, dict[str, Any], str | None]] = []
    known = _known_tool_names(known_tools)

    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = _parse_args_blob(fn.get("arguments", {}))
        _append_call(out, str(name), args, tc.get("id"), known)

    if out:
        return out

    content = (message.get("content") or "").strip()
    if not content:
        return out

    # Strip markdown fences if the model wrapped JSON/XML
    fenced = re.sub(r"^```(?:json|xml)?\s*|\s*```$", "", content, flags=re.IGNORECASE).strip()
    text = fenced or content

    # Qwen-style <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    for match in _TOOL_CALL_XML_RE.finditer(text):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or (obj.get("function") or {}).get("name")
        args = _parse_args_blob(obj.get("arguments") or obj.get("parameters") or {})
        _append_call(out, str(name or ""), args, None, known)
    if out:
        return out

    # Whole-content JSON object or list of calls
    if text.startswith("{") or text.startswith("["):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            name = obj.get("name") or (obj.get("function") or {}).get("name")
            args = _parse_args_blob(obj.get("arguments") or obj.get("parameters") or {})
            if name:
                _append_call(out, str(name), args, None, known)
        elif isinstance(obj, list):
            for item in obj:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or (item.get("function") or {}).get("name")
                args = _parse_args_blob(item.get("arguments") or item.get("parameters") or {})
                if name:
                    _append_call(out, str(name), args, None, known)
        if out:
            return out

    # Prose / bare tool names (one per line). Small models often echo the tool id.
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("`").strip()
        if not line or line.startswith("#"):
            continue
        # Ignore obvious sentences
        if " " in line and "(" not in line and not _BARE_NAME_RE.match(line):
            # Allow "call get_status" style
            m = _CALL_LINE_RE.match(line)
            if not m:
                continue
            name, arg_body = m.group(1), m.group(2)
            _append_call(out, name, _parse_args_blob(arg_body), None, known)
            continue
        m = _CALL_LINE_RE.match(line)
        if not m:
            continue
        name, arg_body = m.group(1), m.group(2)
        _append_call(out, name, _parse_args_blob(arg_body), None, known)

    return out
