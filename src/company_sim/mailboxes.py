"""Pairwise agent mailboxes (text files).

Every unordered pair of actors (companies + cities, including the player)
gets one shared mailbox file under saves/mailboxes/.

Example with player, ai_1, ai_2, city_a → C(4,2) = 6 files:
  company_player__company_ai_1.txt
  company_player__company_ai_2.txt
  company_player__city_city_a.txt
  company_ai_1__company_ai_2.txt
  company_ai_1__city_city_a.txt
  company_ai_2__city_city_a.txt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from company_sim.actors import Actor


def actor_key(kind: str, actor_id: str) -> str:
    return f"{kind}:{actor_id}"


def parse_actor_key(key: str) -> tuple[str, str]:
    if ":" not in key:
        raise ValueError(f"Invalid actor key: {key}")
    kind, aid = key.split(":", 1)
    return kind, aid


def _safe_token(key: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)


def pair_filename(key_a: str, key_b: str) -> str:
    a, b = sorted((key_a, key_b))
    return f"{_safe_token(a)}__{_safe_token(b)}.txt"


@dataclass
class MailMessage:
    day: int
    from_key: str
    to_key: str
    body: str

    def to_line(self) -> str:
        # Single-line body (newlines flattened) so files stay easy to parse
        flat = " ".join(self.body.split())
        return f"[day {self.day}] {self.from_key} -> {self.to_key}: {flat}"

    def to_public_dict(self) -> dict:
        return {
            "day": self.day,
            "from": self.from_key,
            "to": self.to_key,
            "body": self.body,
        }


@dataclass
class Mailbox:
    """Shared conversation between exactly two actors."""

    key_a: str
    key_b: str
    messages: list[MailMessage] = field(default_factory=list)

    @property
    def pair_keys(self) -> tuple[str, str]:
        return tuple(sorted((self.key_a, self.key_b)))  # type: ignore[return-value]

    def involves(self, key: str) -> bool:
        return key in (self.key_a, self.key_b)

    def other(self, key: str) -> str:
        if key == self.key_a:
            return self.key_b
        if key == self.key_b:
            return self.key_a
        raise ValueError(f"{key} not in mailbox {self.pair_keys}")

    def append(self, msg: MailMessage) -> None:
        self.messages.append(msg)

    def to_text(self) -> str:
        a, b = self.pair_keys
        lines = [
            "=== MAILBOX ===",
            f"file: mailboxes/{pair_filename(a, b)}",
            f"participants: {a}, {b}",
            f"message_count: {len(self.messages)}",
            "",
            "-- messages (oldest first) --",
        ]
        if self.messages:
            lines.extend(m.to_line() for m in self.messages)
        else:
            lines.append("(empty)")
        lines.append("")
        return "\n".join(lines) + "\n"

    def to_public_dict(self) -> dict:
        a, b = self.pair_keys
        return {
            "participants": [a, b],
            "filename": pair_filename(a, b),
            "message_count": len(self.messages),
            "messages": [m.to_public_dict() for m in self.messages],
        }


@dataclass
class MailboxStore:
    """
    All pairwise mailboxes for the current cast.

    Generated on startup from the live agent list so the set of files always
    matches C(n, 2) for n agents.
    """

    root: Path
    boxes: dict[str, Mailbox] = field(default_factory=dict)  # filename → box

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.mail_dir = self.root / "mailboxes"

    def ensure_dirs(self) -> None:
        self.mail_dir.mkdir(parents=True, exist_ok=True)

    def _pair_id(self, key_a: str, key_b: str) -> str:
        if key_a == key_b:
            raise ValueError("Cannot create a mailbox with yourself")
        return pair_filename(key_a, key_b)

    def get_box(self, key_a: str, key_b: str) -> Mailbox:
        pid = self._pair_id(key_a, key_b)
        if pid not in self.boxes:
            raise KeyError(f"No mailbox for {key_a} <-> {key_b} (missing {pid})")
        return self.boxes[pid]

    def ensure_all_pairs(self, actors: Iterable[Actor]) -> list[Path]:
        """
        Create in-memory + on-disk mailboxes for every unordered pair.
        Idempotent: existing conversations are kept; missing pairs are added.
        """
        keys = [actor_key(a.kind, a.id) for a in actors]
        keys = sorted(set(keys))
        self.ensure_dirs()
        written: list[Path] = []
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                pid = pair_filename(a, b)
                if pid not in self.boxes:
                    self.boxes[pid] = Mailbox(key_a=a, key_b=b, messages=[])
                path = self.mail_dir / pid
                if not path.exists():
                    path.write_text(self.boxes[pid].to_text(), encoding="utf-8")
                written.append(path)
        # Drop pairs that no longer exist (agent removed) — keep files but
        # remove from active set only if keys changed; for now leave orphans.
        valid = {pair_filename(a, b) for i, a in enumerate(keys) for b in keys[i + 1 :]}
        for pid in list(self.boxes):
            if pid not in valid:
                del self.boxes[pid]
        return written

    def save_all(self) -> list[Path]:
        self.ensure_dirs()
        paths: list[Path] = []
        for pid, box in self.boxes.items():
            path = self.mail_dir / pid
            path.write_text(box.to_text(), encoding="utf-8")
            paths.append(path)
        return paths

    def send(
        self,
        *,
        from_kind: str,
        from_id: str,
        to_kind: str,
        to_id: str,
        body: str,
        day: int,
    ) -> MailMessage:
        text = body.strip()
        if not text:
            raise ValueError("Message body is empty")
        if len(text) > 500:
            raise ValueError("Message too long (max 500 chars)")
        from_key = actor_key(from_kind, from_id)
        to_key = actor_key(to_kind, to_id)
        if from_key == to_key:
            raise ValueError("Cannot message yourself")
        box = self.get_box(from_key, to_key)
        msg = MailMessage(day=day, from_key=from_key, to_key=to_key, body=text)
        box.append(msg)
        # Persist this mailbox immediately
        self.ensure_dirs()
        (self.mail_dir / pair_filename(from_key, to_key)).write_text(box.to_text(), encoding="utf-8")
        return msg

    def boxes_for(self, kind: str, actor_id: str) -> list[Mailbox]:
        key = actor_key(kind, actor_id)
        rows = [b for b in self.boxes.values() if b.involves(key)]
        rows.sort(key=lambda b: b.other(key))
        return rows

    def render_for_agent(self, kind: str, actor_id: str) -> str:
        """All mailboxes involving this agent (for LLM context)."""
        key = actor_key(kind, actor_id)
        boxes = self.boxes_for(kind, actor_id)
        lines = [
            "=== MAIL (your conversations) ===",
            f"you: {key}",
            f"mailbox_count: {len(boxes)}",
            "",
        ]
        if not boxes:
            lines.append("(no mailboxes)")
            lines.append("")
            return "\n".join(lines) + "\n"
        for box in boxes:
            other = box.other(key)
            lines.append(f"-- with {other} ({pair_filename(*box.pair_keys)}) --")
            if box.messages:
                # Last 20 messages to keep prompt small
                for m in box.messages[-20:]:
                    lines.append(m.to_line())
            else:
                lines.append("(empty)")
            lines.append("")
        return "\n".join(lines) + "\n"

    def list_contacts(self, kind: str, actor_id: str) -> list[dict]:
        key = actor_key(kind, actor_id)
        out = []
        for box in self.boxes_for(kind, actor_id):
            other = box.other(key)
            okind, oid = parse_actor_key(other)
            out.append(
                {
                    "key": other,
                    "kind": okind,
                    "id": oid,
                    "filename": pair_filename(*box.pair_keys),
                    "message_count": len(box.messages),
                }
            )
        return out

    def to_public_dict(self) -> dict:
        return {
            "mailbox_count": len(self.boxes),
            "mailboxes": [b.to_public_dict() for b in sorted(self.boxes.values(), key=lambda x: x.pair_keys)],
        }

    def expected_pair_count(self, n_agents: int) -> int:
        return n_agents * (n_agents - 1) // 2
