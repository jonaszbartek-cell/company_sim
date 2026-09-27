"""Pairwise mailbox generation + messaging."""

from __future__ import annotations

import tempfile
from pathlib import Path

from company_sim.mailboxes import pair_filename
from company_sim.world import World, WorldConfig


def _world(tmp: Path, *, ai: int = 2, cities: int = 1) -> World:
    return World.new_game(
        WorldConfig(
            map_width=18,
            map_height=12,
            starting_cities=cities,
            ai_company_count=ai,
            save_dir=str(tmp),
            min_seconds_between_turns=0.0,
        )
    )


def test_startup_creates_all_pair_mailboxes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        # player + ai_1 + ai_2 + city_a = 4 agents → C(4,2)=6
        n = len(list(w.iter_all_actors()))
        assert n == 4
        assert w.mailboxes is not None
        assert len(w.mailboxes.boxes) == 6
        mail_dir = root / "mailboxes"
        files = list(mail_dir.glob("*.txt"))
        assert len(files) == 6
        # Spot-check expected pair file exists
        expected = pair_filename("company:player", "company:ai_1")
        assert (mail_dir / expected).exists()
        text = (mail_dir / expected).read_text(encoding="utf-8")
        assert text.startswith("=== MAILBOX ===")
        assert "participants: company:ai_1, company:player" in text or (
            "company:player" in text and "company:ai_1" in text
        )
        assert "(empty)" in text


def test_mailbox_count_scales_with_agents():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td), ai=1, cities=1)
        # player + ai_1 + city = 3 → C(3,2)=3
        assert len(w.mailboxes.boxes) == 3


def test_agent_agent_and_user_agent_messages():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        r = w.send_message("company", "ai_1", "player", "Want to buy your steel?")
        assert r.ok
        r2 = w.send_message("company", "player", "ai_1", "Maybe at 40/u.")
        assert r2.ok
        r3 = w.send_message("company", "ai_1", "city_a", "Need road access east.")
        assert r3.ok

        path = root / "mailboxes" / pair_filename("company:ai_1", "company:player")
        text = path.read_text(encoding="utf-8")
        assert "Want to buy your steel?" in text
        assert "Maybe at 40/u." in text
        assert "company:ai_1 -> company:player" in text
        assert "company:player -> company:ai_1" in text

        city_path = root / "mailboxes" / pair_filename("company:ai_1", "city:city_a")
        assert "Need road access east." in city_path.read_text(encoding="utf-8")


def test_cannot_message_self():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        try:
            w.send_message("company", "player", "player", "hi")
            assert False, "expected error"
        except Exception as exc:
            assert "yourself" in str(exc).lower() or "yourself" in getattr(exc, "message", "").lower()


def test_llm_context_includes_own_mail_only():
    with tempfile.TemporaryDirectory() as td:
        w = _world(Path(td))
        w.send_message("company", "ai_1", "ai_2", "secret rival deal")
        w.send_message("company", "player", "city_a", "hello city")
        bundle = w.persistence.load_context_for_agent(w, w.companies["player"])
        assert "=== MAIL (your conversations) ===" in bundle
        assert "hello city" in bundle
        # Player is not in ai_1↔ai_2 mailbox
        assert "secret rival deal" not in bundle


def test_ensure_all_pairs_idempotent():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        w = _world(root)
        w.mailboxes.ensure_all_pairs(w.iter_all_actors())
        assert len(w.mailboxes.boxes) == 6
        assert len(list((root / "mailboxes").glob("*.txt"))) == 6
        w.send_message("city", "city_a", "ai_2", "tax notice")
        assert len(list((root / "mailboxes").glob("*.txt"))) == 6
        assert len(w.mailboxes.boxes) == 6
