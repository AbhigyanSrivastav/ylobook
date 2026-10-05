from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ylobook_backend.database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Agent(Base):
    __tablename__ = "agents"
    agent_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    interests: Mapped[list[str]] = mapped_column(JSON)


class ContactRequest(Base):
    __tablename__ = "contact_requests"
    request_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    from_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    to_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    purpose: Mapped[str] = mapped_column(Text)
    # Demo policy: no acceptance UI. Every contact immediately opens a conversation.
    status: Mapped[str] = mapped_column(default="accepted")


class Conversation(Base):
    __tablename__ = "conversations"
    conversation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("contact_requests.request_id"), unique=True)
    initiator_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    next_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    message_count: Mapped[int] = mapped_column(default=0)
    max_messages: Mapped[int]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence"),)
    message_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True,
    )
    from_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"))
    sequence: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
