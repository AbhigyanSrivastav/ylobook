"""Exercise the real HTTP contract with two independent local agents."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from ylobook_agent.api import BackendClient, BackendError
from ylobook_agent.cli import onboard, select_interests
from ylobook_agent.config import load_config, save_config
from ylobook_agent.conversations import ConversationLoop
from ylobook_agent.graph import YlobookGraph
from ylobook_agent.tools import make_tools
from ylobook_backend.main import MAX_AUTONOMOUS_MESSAGES, create_app


class LocalModel:
    """Deterministic substitute for Groq; executes the real LangGraph tool nodes."""
    def __init__(self, selected=None):
        self.selected = selected
        self.calls = 0
        self.tool_name = None

    def bind_tools(self, tools, tool_choice):
        assert len(tools) == 3
        self.tool_name = tool_choice["function"]["name"]
        return self

    def invoke(self, messages):
        if self.tool_name:
            name, self.tool_name = self.tool_name, None
            args = ({"keywords": [], "interests": ["AI Agents"]} if name == "search_agents"
                    else {"agent_id": self.selected, "purpose": "What are you building?"})
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1"}])
        self.calls += 1
        return AIMessage(content=f"Reply {self.calls}: I am exploring my listed interests.")


@pytest.fixture
def network(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'network.db'}")) as server:
        traffic = []
        def handler(request):
            traffic.append((dict(request.headers), request.content))
            response = server.request(request.method, str(request.url), content=request.content,
                                      headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content)
        api = BackendClient("http://testserver", transport=httpx.MockTransport(handler))
        yield api, server, traffic
        api.close()


def profile(name):
    return {"agent_id": f"agent_{uuid4().hex}", "display_name": name, "interests": ["AI Agents"]}


def test_two_agents_ten_messages_and_restart(network):
    api, _server, traffic = network
    alice, bob = profile("Alice"), profile("Bob")
    api.register(alice)
    api.register(bob)
    model_a, model_b = LocalModel(bob["agent_id"]), LocalModel(alice["agent_id"])
    a = YlobookGraph(api, alice, api_key="local-only-sentinel", llm=model_a)
    b = YlobookGraph(api, bob, api_key="another-local-only-sentinel", llm=model_b)
    assert [t.name for t in make_tools(api, alice)] == [
        "get_my_identity", "search_agents", "contact_agent"]
    assert a.search("Find AI agents")["agents"] == [bob]
    contact = a.contact("What are you building?", bob["agent_id"])
    cid = contact["conversation_id"]
    la, lb = ConversationLoop(api, a, alice, lambda _: None), ConversationLoop(api, b, bob, lambda _: None)
    la.tick()  # A speaks even when B has not yet started.
    assert len(api.conversation(cid, alice["agent_id"])["messages"]) == 1
    la.tick()
    assert model_a.calls == 1  # Offline B stalls the turn, not a self-loop.
    for _ in range(5):
        lb.tick()
        la.tick()
    history = api.conversation(cid, alice["agent_id"])
    assert len(history["messages"]) == MAX_AUTONOMOUS_MESSAGES
    assert history["status"] == "complete"
    assert [m["from_agent_id"] for m in history["messages"]] == [alice["agent_id"], bob["agent_id"]] * 5
    ConversationLoop(api, a, alice, lambda _: None).tick()
    assert model_a.calls == model_b.calls == 5
    with pytest.raises(BackendError) as error:
        api.post_message(cid, alice["agent_id"], "eleventh", 10)
    assert error.value.status == 409
    assert all("authorization" not in headers for headers, _ in traffic)
    assert "local-only-sentinel" not in str(traffic)


def test_duplicate_posts_and_contacts(network):
    api, _, _ = network
    a, b = profile("Alice"), profile("Bob")
    api.register(a)
    api.register(b)
    rid = f"request_{uuid4().hex}"
    contact = api.contact_agent(a["agent_id"], b["agent_id"], "hello", rid)
    duplicate = api.contact_agent(a["agent_id"], b["agent_id"], "hello", rid)
    assert contact["conversation_id"] == duplicate["conversation_id"]
    cid = contact["conversation_id"]
    with pytest.raises(BackendError):
        api.post_message(cid, b["agent_id"], "out of turn", 0)
    def send(_):
        try:
            api.post_message(cid, a["agent_id"], "hello", 0)
            return 200
        except BackendError as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(send, range(2))) == [200, 409]
    assert len(api.conversation(cid, a["agent_id"])["messages"]) == 1
    with pytest.raises(BackendError):
        api.contact_agent(a["agent_id"], a["agent_id"], "self", f"request_{uuid4().hex}")


def test_config_onboarding_and_interest_validation(network, tmp_path, monkeypatch):
    from ylobook_agent import config
    api, _, _ = network
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    values = iter(["Alice", "1,2"])
    monkeypatch.setattr("builtins.input", lambda _: next(values))
    save_config({"groq_api_key": "test-placeholder"})
    a = onboard(api)
    assert onboard(api) == a  # Does not prompt again.
    assert load_config()["groq_api_key"] == "test-placeholder"
    assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600
    assert select_interests("1,2,1") == ["AI Agents", "Developer Tools"]
    for value in ("0", "6", "", "1,", "hello"):
        with pytest.raises(ValueError):
            select_interests(value)


def test_invalid_payloads_and_member_check(network):
    api, server, _ = network
    a, b, outsider = profile("Alice"), profile("Bob"), profile("Outsider")
    for item in (a, b, outsider):
        api.register(item)
    assert server.post("/agents", json={"agent_id": a["agent_id"], "name": " ", "interests": []}).status_code == 422
    assert server.post("/agents", json={"agent_id": a["agent_id"], "name": "Alice",
        "interests": ["AI Agents"], "groq_api_key": "must-not-be-stored"}).status_code == 422
    cid = api.contact_agent(a["agent_id"], b["agent_id"], "hello", f"request_{uuid4().hex}")["conversation_id"]
    with pytest.raises(BackendError) as error:
        api.conversation(cid, outsider["agent_id"])
    assert error.value.status == 404


def test_selection_cannot_be_redirected(network):
    api, _, _ = network
    a, b, outsider = profile("Alice"), profile("Bob"), profile("Other")
    for item in (a, b, outsider):
        api.register(item)
    graph = YlobookGraph(api, a, llm=LocalModel(outsider["agent_id"]))
    with pytest.raises(RuntimeError, match="different contact target"):
        graph.contact("hello", b["agent_id"])
    assert api.inbox(a["agent_id"]) == []


def test_database_survives_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    a, b = profile("Alice"), profile("Bob")
    with TestClient(create_app(url)) as server:
        for person in (a, b):
            assert server.post("/agents", json={"agent_id": person["agent_id"],
                "name": person["display_name"], "interests": person["interests"]}).status_code == 200
        cid = server.post("/requests", json={"request_id": f"request_{uuid4().hex}",
            "from_agent_id": a["agent_id"], "to_agent_id": b["agent_id"], "purpose": "hello"}).json()["conversation_id"]
        assert server.post(f"/conversations/{cid}/messages", json={
            "from_agent_id": a["agent_id"], "content": "persist me", "expected_count": 0}).status_code == 200
    with TestClient(create_app(url)) as server:
        history = server.get(f"/conversations/{cid}/messages", params={"agent_id": b["agent_id"]}).json()
        assert history["messages"][0]["content"] == "persist me"
        assert history["next_agent_id"] == b["agent_id"]
