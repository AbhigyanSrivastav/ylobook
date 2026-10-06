from types import SimpleNamespace

from ylobook_agent import integrations
from ylobook_agent.mcp_server import create_server
from ylobook_agent.service import YlobookService


class FakeAPI:
    def close(self):
        pass

    def search_agents(self, keywords, interests):
        return {"agents": [{"agent_id": "agent_b", "display_name": "Bob", "interests": ["AI Agents"]}]}


def test_mcp_registers_only_bounded_tools():
    service = YlobookService(FakeAPI(), {
        "agent_id": "agent_a", "display_name": "Alice", "interests": ["AI Agents"],
        "agent_token": "secret-token", "groq_api_key": "secret-groq",
    })
    server = create_server(service)
    assert sorted(server._tool_manager._tools) == [
        "contact_agent", "get_messages", "get_my_identity", "list_conversations",
        "list_inbox", "search_agents", "send_message",
    ]
    assert service.get_my_identity() == {
        "agent_id": "agent_a", "display_name": "Alice", "interests": ["AI Agents"],
    }
    assert "secret-token" not in str(service.get_my_identity())
    assert "secret-groq" not in str(service.get_my_identity())


def test_codex_setup_is_idempotent_without_editing_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(integrations, "_require_identity", lambda: None)
    monkeypatch.setattr(integrations, "_executable", lambda: "/bin/ylobook")

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="ylobook", stderr="")

    monkeypatch.setattr(integrations.subprocess, "run", run)
    result = integrations.setup_codex()
    assert "already configured" in result
    assert calls == [["/bin/codex", "mcp", "list"]]
