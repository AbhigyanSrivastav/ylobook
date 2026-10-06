from ylobook_agent.conversations import ConversationLoop
from ylobook_agent.policy import ReceivingPolicy


class YlobookRuntime:
    """Local network runtime: transport, policy, polling, and local agent."""

    def __init__(self, api, agent, identity, emit=print, policy=None):
        self.loop = ConversationLoop(api, agent, identity, emit, policy or ReceivingPolicy())

    def start(self) -> None:
        self.loop.start()

    def stop(self) -> None:
        self.loop.stop()

    def poll_once(self) -> None:
        self.loop.tick()
