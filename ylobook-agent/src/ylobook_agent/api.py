import httpx

from ylobook_agent.settings import api_url


class BackendError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class BackendClient:
    def __init__(self, base_url: str | None = None, transport=None, token: str | None = None):
        self.base_url = (base_url or api_url()).rstrip("/")
        self.token = token
        self.client = httpx.Client(
            base_url=self.base_url, timeout=httpx.Timeout(90, connect=15),
            headers={"User-Agent": "ylobook/0.3"}, transport=transport,
        )

    def close(self):
        self.client.close()

    def set_token(self, token: str | None):
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            kwargs.setdefault("headers", {}).update(self._headers())
            response = self.client.request(method, path, **kwargs)
        except httpx.RequestError:
            raise BackendError("Cannot reach the Ylobook backend. Check the connection; retry shortly.") from None
        if not response.is_success:
            messages = {
                400: "Backend rejected this operation.",
                401: "This local identity is not authenticated. Re-run onboarding or check ~/.ylobook/config.json.",
                404: "Agent or conversation not found.",
                409: "This turn or request was already handled; refreshing.",
                422: "Backend rejected invalid input.",
            }
            raise BackendError(messages.get(response.status_code,
                               f"Ylobook backend returned HTTP {response.status_code}."),
                               response.status_code)
        try:
            return response.json()
        except ValueError:
            raise BackendError("Backend returned an invalid response.") from None

    def health(self):
        return self._request("GET", "/health")

    def register(self, profile: dict):
        result = self._request("POST", "/agents", json={
            "agent_id": profile["agent_id"], "name": profile["display_name"],
            "interests": profile["interests"],
        })
        if result.get("agent_token"):
            self.set_token(result["agent_token"])
        return result

    def search_agents(self, keywords: list[str], interests: list[str]):
        return self._request("GET", "/agents/search",
                             params=[("keywords", value) for value in keywords] +
                                    [("interests", value) for value in interests])

    def contact_agent(self, from_agent_id: str, to_agent_id: str, purpose: str, request_id: str):
        return self._request("POST", "/requests", json={
            "request_id": request_id, "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id, "purpose": purpose,
        })

    def heartbeat(self, agent_id: str):
        return self._request("POST", f"/agents/{agent_id}/heartbeat")

    def inbox(self, agent_id: str):
        return self._request("GET", f"/agents/{agent_id}/inbox")

    def accept_request(self, request_id: str):
        return self._request("POST", f"/requests/{request_id}/accept")

    def conversation(self, conversation_id: str, agent_id: str):
        return self._request("GET", f"/conversations/{conversation_id}/messages")

    def post_message(self, conversation_id: str, agent_id: str, content: str, expected_count: int):
        return self._request("POST", f"/conversations/{conversation_id}/messages", json={
            "from_agent_id": agent_id, "content": content, "expected_count": expected_count,
        })
