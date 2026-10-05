import json

from langchain_core.tools import tool


def make_tools(api, identity: dict, selected_id: str | None = None, request_id: str | None = None):
    @tool
    def get_my_identity() -> str:
        """Return my local agent identity and interests."""
        return json.dumps(identity)

    @tool
    def search_agents(keywords: list[str], interests: list[str]) -> str:
        """Find other agents by concise keywords or predefined interest labels."""
        result = api.search_agents(keywords, interests)
        result["agents"] = [item for item in result["agents"]
                            if item["agent_id"] != identity["agent_id"]]
        return json.dumps(result)

    @tool
    def contact_agent(agent_id: str, purpose: str) -> str:
        """Start a demo conversation with the agent selected by the human."""
        # Model text cannot redirect the side effect to a different recipient.
        if not selected_id or agent_id != selected_id or not request_id:
            raise RuntimeError("Contact target differs from your selection.")
        if not purpose.strip() or len(purpose) > 2000:
            raise RuntimeError("Contact purpose is empty or too long.")
        return json.dumps(api.contact_agent(identity["agent_id"], selected_id, purpose, request_id))

    return [get_my_identity, search_agents, contact_agent]
