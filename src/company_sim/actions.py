"""Shared action API — player UI and LLM tools both go through here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class ActionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
