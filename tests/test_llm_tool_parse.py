"""Unit tests for LLM tool-call parsing (no live Ollama required)."""

from __future__ import annotations

from company_sim.ai.llm_client import LLMConfig, parse_tool_calls


KNOWN = {
    "get_status",
    "list_plots_for_sale",
    "propose_plot_buy",
    "build_building",
    "done",
    "accept_proposal",
}


def test_parse_structured_tool_calls():
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "function": {"name": "get_status", "arguments": {}},
            },
            {
                "id": "call_2",
                "function": {
                    "name": "propose_plot_buy",
                    "arguments": '{"to":"city:city_a","x":1,"y":0,"price":100}',
                },
            },
        ],
    }
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert [c[0] for c in calls] == ["get_status", "propose_plot_buy"]
    assert calls[1][1]["price"] == 100
    assert calls[0][2] == "call_1"


def test_parse_json_content_fallback():
    msg = {
        "content": '{"name": "list_plots_for_sale", "arguments": {"limit": 5}}',
    }
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert calls == [("list_plots_for_sale", {"limit": 5}, None)]


def test_parse_qwen_tool_call_xml():
    msg = {
        "content": (
            '<tool_call>\n'
            '{"name": "propose_plot_buy", "arguments": '
            '{"to": "city:city_a", "x": 2, "y": 1, "price": 100}}\n'
            "</tool_call>"
        ),
    }
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert len(calls) == 1
    assert calls[0][0] == "propose_plot_buy"
    assert calls[0][1]["x"] == 2


def test_parse_bare_tool_name_prose():
    msg = {"content": "list_plots_for_sale"}
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert calls == [("list_plots_for_sale", {}, None)]


def test_parse_call_with_kwargs_prose():
    msg = {
        "content": 'propose_plot_buy(to="city:city_a", x=1, y=0, price=100)\ndone(note="bought")',
    }
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert [c[0] for c in calls] == ["propose_plot_buy", "done"]
    assert calls[0][1] == {"to": "city:city_a", "x": 1, "y": 0, "price": 100}
    assert calls[1][1]["note"] == "bought"


def test_parse_ignores_unknown_bare_names():
    msg = {"content": "launch_nukes\nget_status"}
    calls = parse_tool_calls(msg, known_tools=KNOWN)
    assert calls == [("get_status", {}, None)]


def test_llm_config_num_ctx_from_env(monkeypatch):
    monkeypatch.setenv("COMPANY_SIM_LLM", "1")
    monkeypatch.setenv("COMPANY_SIM_LLM_NUM_CTX", "8192")
    cfg = LLMConfig.from_env()
    assert cfg.enabled is True
    assert cfg.num_ctx == 8192
