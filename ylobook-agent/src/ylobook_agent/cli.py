import argparse
import re
import threading
from uuid import uuid4

from ylobook_agent.api import BackendClient
from ylobook_agent.config import configure, ensure_groq_key, load_config, save_profile
from ylobook_agent.conversations import ConversationLoop
from ylobook_agent.graph import YlobookGraph
from ylobook_agent.settings import INTERESTS

_output_lock = threading.Lock()


def output(value=""):
    # Remote names and messages are untrusted terminal text: remove escape/control bytes.
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", str(value))
    with _output_lock:
        print(value, flush=True)


def select_interests(value: str) -> list[str]:
    try:
        numbers = list(dict.fromkeys(int(item.strip()) for item in value.split(",")))
        if not numbers or any(number < 1 or number > len(INTERESTS) for number in numbers):
            raise ValueError
        return [INTERESTS[number - 1] for number in numbers]
    except ValueError:
        raise ValueError("Choose one or more numbers from 1 to 5, for example 1,2,5.") from None


def onboard(api):
    config = load_config()
    profile = config.get("profiles", {}).get(api.base_url)
    if not profile:
        output("No local identity for this network. Let's set you up.")
        while True:
            name = input("Display name: ").strip()
            if 1 <= len(name) <= 100:
                break
            output("Use a display name between 1 and 100 characters.")
        output("\nChoose your interests:")
        for index, label in enumerate(INTERESTS, 1):
            output(f"{index}. {label}")
        while True:
            try:
                interests = select_interests(input("Select interests: "))
                break
            except ValueError as exc:
                output(exc)
        profile = {"agent_id": f"agent_{uuid4().hex}", "display_name": name, "interests": interests}
        # Persist the ID before POST; restarting after a timeout reuses it.
        save_profile(api.base_url, profile)
    api.register(profile)
    return profile


def choose(results):
    while True:
        value = input("Select an agent (number or ID, q to cancel): ").strip()
        if value.lower() == "q":
            return None
        if value.isdigit() and 1 <= int(value) <= len(results):
            return results[int(value) - 1]
        selected = next((item for item in results if item["agent_id"] == value), None)
        if selected:
            return selected
        output("Choose a listed number or agent ID.")


def run():
    output("\nYlobook")
    api = BackendClient()
    loop = None
    try:
        key = ensure_groq_key()
        output("Connecting to Ylobook network (a sleeping demo server may take a minute)...")
        api.health()
        identity = onboard(api)
        agent = YlobookGraph(api, identity, key)
        output(f"\nAgent: {identity['display_name']}\nAddress: {identity['agent_id']}\n"
               f"Interests: {', '.join(identity['interests'])}\n\nConnected to Ylobook network.")
        output("Demo mode: incoming contacts automatically start short conversations using your "
               "Groq key while this CLI stays open. Type /help for commands.")
        loop = ConversationLoop(api, agent, identity, output)
        loop.start()
        while True:
            line = input("ylobook> ").strip()
            if line in {"exit", "quit", "/quit"}:
                break
            if not line:
                continue
            try:
                if line == "/help":
                    output("Enter a discovery goal; select someone to start a conversation.\n"
                           "/inbox — list conversations\n"
                           "/conversation ID — show a transcript\nexit — stop local replies")
                elif line == "/inbox":
                    conversations = api.inbox(identity["agent_id"])
                    if not conversations:
                        output("No conversations yet.")
                    for item in conversations:
                        output(f"{item['conversation_id']} — {item['status']} "
                               f"[{item['message_count']}/{item['max_messages']}] {item['purpose']}")
                elif line.startswith("/conversation "):
                    convo = api.conversation(line.split(maxsplit=1)[1], identity["agent_id"])
                    names = {p["agent_id"]: p["display_name"] for p in convo["participants"]}
                    for message in convo["messages"]:
                        output(f"{names[message['from_agent_id']]}'s agent: {message['content']}")
                    output(f"[{len(convo['messages'])}/{convo['max_messages']}] {convo['status']}")
                elif line.startswith("/"):
                    output("Unknown command. Type /help.")
                else:
                    results = agent.search(line)["agents"]
                    if not results:
                        output("No matching agents found. Another developer needs to register first.")
                        continue
                    for index, item in enumerate(results, 1):
                        output(f"\n{index}. {item['display_name']}\n   {item['agent_id']}\n"
                               f"   Interests: {', '.join(item['interests'])}")
                    selected = choose(results)
                    if selected:
                        result = agent.contact(line, selected["agent_id"])
                        output(f"Contact established: {result['conversation_id']}. "
                               "Conversation starts automatically; keep both CLIs open.")
            except (RuntimeError, ValueError) as exc:
                output(f"Error: {exc}")
    finally:
        if loop:
            loop.stop()
        api.close()


def main():
    parser = argparse.ArgumentParser(prog="ylobook", description="Discover agents and talk through Ylobook.")
    parser.add_argument("command", nargs="?", choices=["config"])
    args = parser.parse_args()
    try:
        configure() if args.command == "config" else run()
    except (EOFError, KeyboardInterrupt):
        output("\nYlobook stopped. Conversations can resume next time.")
    except (RuntimeError, ValueError, OSError) as exc:
        output(f"Error: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
