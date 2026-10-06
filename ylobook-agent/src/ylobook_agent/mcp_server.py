import sys

from mcp.server.fastmcp import FastMCP

from ylobook_agent.service import YlobookService


def create_server(service: YlobookService | None = None) -> FastMCP:
    service = service or YlobookService.from_config()
    server = FastMCP(
        "Ylobook",
        instructions="Use these bounded tools to discover and communicate with agents on the Ylobook network. "
        "The local Ylobook runtime owns identity and authentication.",
    )

    @server.tool()
    def get_my_identity() -> dict:
        """Return the local Ylobook agent identity. Never exposes the local authentication token."""
        return service.get_my_identity()

    @server.tool()
    def search_agents(keywords: list[str] | None = None, interests: list[str] | None = None) -> list[dict]:
        """Search the Ylobook network for other agents using interests or natural-language keywords."""
        return service.search_agents(keywords, interests)

    @server.tool()
    def contact_agent(agent_id: str, purpose: str) -> dict:
        """Send a contact request to another Ylobook agent. The local identity is always the sender."""
        return service.contact_agent(agent_id, purpose)

    @server.tool()
    def list_inbox() -> dict:
        """List pending contact requests, newly delivered messages, and the local agent's conversations."""
        return service.list_inbox()

    @server.tool()
    def list_conversations() -> list[dict]:
        """List active and recent Ylobook conversations for the local agent."""
        return service.list_conversations()

    @server.tool()
    def get_messages(conversation_id: str, limit: int = 20) -> dict:
        """Read recent messages from one conversation; history is bounded to at most 50 messages."""
        return service.get_messages(conversation_id, limit)

    @server.tool()
    def send_message(conversation_id: str, content: str) -> dict:
        """Send a message in a Ylobook conversation as the local agent, respecting turn and message limits."""
        return service.send_message(conversation_id, content)

    return server


def serve() -> None:
    service = None
    try:
        service = YlobookService.from_config()
        create_server(service).run(transport="stdio")
    except (RuntimeError, ValueError) as exc:
        print(f"Ylobook MCP error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if service:
            service.close()
