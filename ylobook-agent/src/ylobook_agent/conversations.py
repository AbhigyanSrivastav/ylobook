"""HTTP polling belongs to the application, not to the model's tool registry."""

import threading

from ylobook_agent.api import BackendError
from ylobook_agent.settings import POLL_SECONDS


class ConversationLoop:
    def __init__(self, api, agent, identity, emit=print):
        self.api, self.agent, self.identity, self.emit = api, agent, identity, emit
        self.stop_event = threading.Event()
        self.seen = {}
        self.finished = set()
        self.thread = None
        self.last_error = None

    def display(self, conversation):
        cid = conversation["conversation_id"]
        participants = {item["agent_id"]: item["display_name"]
                        for item in conversation["participants"]}
        other = next(name for key, name in participants.items() if key != self.identity["agent_id"])
        if cid not in self.seen:
            self.emit(f"\nConversation with {other} ({cid})\nPurpose: {conversation['purpose']}")
        seen = self.seen.get(cid, 0)
        for message in conversation["messages"]:
            if message["sequence"] <= seen:
                continue
            speaker = ("Your agent" if message["from_agent_id"] == self.identity["agent_id"]
                       else f"{participants[message['from_agent_id']]}'s agent")
            self.emit(f"\n{speaker}:\n{message['content']}\n"
                      f"[{message['sequence']} / {conversation['max_messages']} messages]")
        self.seen[cid] = len(conversation["messages"])
        if conversation["status"] == "complete":
            self.finished.add(cid)
            self.emit("Conversation finished automatically.")

    def tick(self):
        for item in self.api.inbox(self.identity["agent_id"]):
            cid = item["conversation_id"]
            if cid in self.finished or self.stop_event.is_set():
                continue
            conversation = self.api.conversation(cid, self.identity["agent_id"])
            self.display(conversation)
            if (conversation["status"] != "active" or
                    conversation["next_agent_id"] != self.identity["agent_id"]):
                continue
            # Take the count from the actual history, not a potentially older summary.
            count = len(conversation["messages"])
            if count >= conversation["max_messages"]:
                continue
            reply = self.agent.reply(conversation)
            if self.stop_event.is_set():
                return
            try:
                self.api.post_message(cid, self.identity["agent_id"], reply, count)
            except BackendError as exc:
                if exc.status == 409:
                    continue  # Another local session took this turn; refetch next poll.
                raise
            self.display(self.api.conversation(cid, self.identity["agent_id"]))

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                if self.last_error:
                    self.emit("Ylobook connection resumed.")
                self.last_error = None
            except (RuntimeError, ValueError) as exc:
                if str(exc) != self.last_error:
                    self.emit(f"Conversation paused: {exc} Retrying while Ylobook is open.")
                self.last_error = str(exc)
            self.stop_event.wait(15 if self.last_error else POLL_SECONDS)

    def start(self):
        self.thread = threading.Thread(target=self._run, name="ylobook-poll", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
