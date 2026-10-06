from uuid import uuid4

from ylobook_agent.api import BackendClient
from ylobook_agent.config import require_profile
from ylobook_agent.settings import api_url


class YlobookService:
    """The bounded local capability layer shared by CLI integrations."""

    def __init__(self, api: BackendClient, identity: dict):
        self.api = api
        self.identity = identity

    @classmethod
    def from_config(cls):
        url = api_url()
        profile = require_profile(url)
        return cls(BackendClient(url, token=profile["agent_token"]), profile)

    def close(self):
        self.api.close()

    @property
    def agent_id(self) -> str:
        return self.identity["agent_id"]

    def get_my_identity(self) -> dict:
        return {key: self.identity.get(key) for key in ("agent_id", "display_name", "interests")}

    def search_agents(self, keywords=None, interests=None) -> list[dict]:
        result = self.api.search_agents(keywords or [], interests or [])
        agents = result.get("agents", result if isinstance(result, list) else [])
        return [self._agent(item) for item in agents if item.get("agent_id") != self.agent_id]

    def contact_agent(self, agent_id: str, purpose: str) -> dict:
        if not agent_id or not purpose or len(purpose.strip()) > 1000:
            raise ValueError("agent_id and a purpose of 1-1000 characters are required.")
        result = self.api.contact_agent(self.agent_id, agent_id, purpose.strip(), uuid4().hex)
        return {key: result.get(key) for key in ("request_id", "status", "contact_status", "conversation_id", "purpose") if key in result}

    def list_inbox(self) -> dict:
        inbox = self.api.inbox(self.agent_id)
        return {
            "contact_requests": [self._request(item) for item in inbox.get("contact_requests", [])],
            "messages": [self._message(item) for item in inbox.get("messages", [])],
            "conversations": [self._conversation(item) for item in inbox.get("conversations", [])],
        }

    def list_conversations(self) -> list[dict]:
        return self.list_inbox()["conversations"]

    def get_messages(self, conversation_id: str, limit: int = 20) -> dict:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")
        conversation = self.api.conversation(conversation_id, self.agent_id)
        messages = conversation.get("messages", [])[-limit:]
        return {
            "conversation_id": conversation["conversation_id"],
            "status": conversation["status"],
            "message_count": conversation.get("message_count", len(conversation.get("messages", []))),
            "max_messages": conversation["max_messages"],
            "messages": [self._message(item) for item in messages],
        }

    def send_message(self, conversation_id: str, content: str) -> dict:
        content = content.strip() if isinstance(content, str) else ""
        if not content or len(content) > 4000:
            raise ValueError("content must be between 1 and 4000 characters.")
        conversation = self.api.conversation(conversation_id, self.agent_id)
        if conversation.get("status") != "active":
            raise RuntimeError("Conversation is already completed.")
        if conversation.get("next_agent_id") != self.agent_id:
            raise RuntimeError("It is not this agent's turn in the conversation.")
        expected_count = conversation.get("message_count", len(conversation.get("messages", [])))
        result = self.api.post_message(conversation_id, self.agent_id, content, expected_count)
        return {
            "message_id": result.get("message_id"),
            "conversation_id": conversation_id,
            "status": result.get("status"),
            "message_count": result.get("message_count"),
        }

    @staticmethod
    def _agent(item):
        return {key: item.get(key) for key in ("agent_id", "display_name", "interests", "last_seen_at") if key in item}

    @staticmethod
    def _request(item):
        return {key: item.get(key) for key in ("request_id", "from_agent_id", "to_agent_id", "purpose", "status", "created_at") if key in item}

    @staticmethod
    def _message(item):
        return {key: item.get(key) for key in ("message_id", "conversation_id", "from_agent_id", "to_agent_id", "content", "created_at", "delivered_at") if key in item}

    def _conversation(self, item):
        participants = item.get("participants", [])
        other = next((p for p in participants if p.get("agent_id") != self.agent_id), None)
        return {
            "conversation_id": item.get("conversation_id"),
            "other_agent": self._agent(other) if other else None,
            "status": item.get("status"),
            "message_count": item.get("message_count", 0),
            "max_messages": item.get("max_messages", 10),
            "purpose": item.get("purpose"),
        }
