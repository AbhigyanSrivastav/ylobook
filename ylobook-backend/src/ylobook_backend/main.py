import hashlib
import hmac
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ylobook_backend.database import Base, make_database
from ylobook_backend.models import Agent, ContactRequest, Conversation, Message, new_id, utcnow
from ylobook_backend.schemas import AgentCreate, ContactCreate, MessageCreate

MAX_AUTONOMOUS_MESSAGES = 10


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


def agent_data(agent: Agent) -> dict:
    return {"agent_id": agent.agent_id, "display_name": agent.name,
            "interests": agent.interests or [], "last_seen_at": agent.last_seen_at}


def require_token(request: Request) -> str:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer agent token required")
    return token.strip()


def authenticate(db: Session, request: Request, agent_id: str) -> Agent:
    token = require_token(request)
    agent = db.get(Agent, agent_id)
    if not agent or not agent.token_hash or not hmac.compare_digest(agent.token_hash, hash_token(token)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent token")
    return agent


def migration_columns(engine) -> None:
    """Add nullable columns needed by clients upgrading the tiny pre-auth schema."""
    additions = {
        "agents": {"token_hash": "VARCHAR(128)", "created_at": "TIMESTAMP", "last_seen_at": "TIMESTAMP"},
        "contact_requests": {"created_at": "TIMESTAMP"},
        "messages": {"to_agent_id": "VARCHAR(100)", "delivered_at": "TIMESTAMP"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            present = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in present:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def conversation_data(db: Session, conversation: Conversation) -> dict:
    contact = db.get(ContactRequest, conversation.request_id)
    return {
        "conversation_id": conversation.conversation_id,
        "purpose": contact.purpose,
        "initiator_id": conversation.initiator_id,
        "recipient_id": conversation.recipient_id,
        "participants": [agent_data(db.get(Agent, key)) for key in
                         (conversation.initiator_id, conversation.recipient_id)],
        "next_agent_id": conversation.next_agent_id,
        "message_count": conversation.message_count,
        "max_messages": conversation.max_messages,
        "status": conversation.status,
    }


def member_conversation(db: Session, conversation_id: str, agent_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or agent_id not in (conversation.initiator_id, conversation.recipient_id):
        raise HTTPException(404, "Conversation not found for this agent")
    return conversation


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = make_database(database_url)
        app.state.sessions = sessions
        Base.metadata.create_all(engine)
        migration_columns(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Ylobook API", version="0.4.0", lifespan=lifespan)

    @app.get("/health")
    def health(db: Session = Depends(db_session)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "max_autonomous_messages": MAX_AUTONOMOUS_MESSAGES}

    @app.post("/agents")
    def register(payload: AgentCreate, db: Session = Depends(db_session)):
        agent = db.get(Agent, payload.agent_id)
        if agent:
            if agent.name != payload.name or agent.interests != payload.interests:
                raise HTTPException(409, "Agent ID is already registered with a different profile")
            if not agent.token_hash:
                raise HTTPException(409, "This legacy identity needs a fresh secure registration")
            result = agent_data(agent)
            return result
        token = new_token()
        agent = Agent(**payload.model_dump(), token_hash=hash_token(token), last_seen_at=utcnow())
        db.add(agent)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Registration raced with another session; retry") from None
        result = agent_data(agent)
        result["agent_token"] = token
        return result

    @app.get("/agents/search")
    def search(keywords: list[str] = Query(default=[]), interests: list[str] = Query(default=[]),
               db: Session = Depends(db_session)):
        terms = {term.strip().casefold() for term in keywords + interests if term.strip()}
        agents = db.scalars(select(Agent).order_by(Agent.name)).all()
        return {"agents": [agent_data(agent) for agent in agents if not terms or
                           any(term in " ".join([agent.name, *(agent.interests or [])]).casefold()
                               for term in terms)]}

    @app.post("/agents/{agent_id}/heartbeat")
    def heartbeat(agent_id: str, request: Request, db: Session = Depends(db_session)):
        agent = authenticate(db, request, agent_id)
        agent.last_seen_at = utcnow()
        db.commit()
        return {"agent_id": agent.agent_id, "last_seen_at": agent.last_seen_at}

    @app.post("/requests")
    def contact(payload: ContactCreate, request: Request, db: Session = Depends(db_session)):
        authenticate(db, request, payload.from_agent_id)
        if payload.from_agent_id == payload.to_agent_id:
            raise HTTPException(400, "An agent cannot contact itself")
        if not db.get(Agent, payload.to_agent_id):
            raise HTTPException(404, "Target agent not found")
        existing = db.get(ContactRequest, payload.request_id)
        if existing:
            if any(getattr(existing, key) != value for key, value in payload.model_dump().items()):
                raise HTTPException(409, "Request ID already used")
            conversation = db.scalar(select(Conversation).where(
                Conversation.request_id == existing.request_id))
            return ({"contact_status": existing.status, **conversation_data(db, conversation)}
                    if conversation else {"contact_status": existing.status,
                                          "request_id": existing.request_id})
        contact_request = ContactRequest(**payload.model_dump())
        db.add(contact_request)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Request already exists; retry") from None
        return {"contact_status": "pending", "request_id": contact_request.request_id}

    @app.post("/requests/{request_id}/accept")
    def accept(request_id: str, request: Request, db: Session = Depends(db_session)):
        contact_request = db.get(ContactRequest, request_id)
        if not contact_request:
            raise HTTPException(404, "Contact request not found")
        authenticate(db, request, contact_request.to_agent_id)
        if contact_request.status == "accepted":
            conversation = db.scalar(select(Conversation).where(
                Conversation.request_id == contact_request.request_id))
            return {"contact_status": "accepted", **conversation_data(db, conversation)}
        contact_request.status = "accepted"
        conversation = Conversation(
            conversation_id=new_id("conversation"), request_id=contact_request.request_id,
            initiator_id=contact_request.from_agent_id, recipient_id=contact_request.to_agent_id,
            next_agent_id=contact_request.from_agent_id, max_messages=MAX_AUTONOMOUS_MESSAGES,
        )
        db.add(conversation)
        db.commit()
        return {"contact_status": "accepted", **conversation_data(db, conversation)}

    @app.get("/agents/{agent_id}/inbox")
    def inbox(agent_id: str, request: Request, db: Session = Depends(db_session)):
        agent = authenticate(db, request, agent_id)
        pending = db.scalars(select(ContactRequest).where(
            ContactRequest.to_agent_id == agent.agent_id,
            ContactRequest.status == "pending")).all()
        undelivered = db.scalars(select(Message).where(
            Message.to_agent_id == agent.agent_id, Message.delivered_at.is_(None))).all()
        delivered_at = utcnow()
        for message in undelivered:
            message.delivered_at = delivered_at
        db.commit()
        conversations = db.scalars(select(Conversation).where(or_(
            Conversation.initiator_id == agent.agent_id, Conversation.recipient_id == agent.agent_id,
        )).order_by(Conversation.created_at)).all()
        return {
            "contact_requests": [{"request_id": item.request_id, "from_agent_id": item.from_agent_id,
                                  "to_agent_id": item.to_agent_id, "purpose": item.purpose,
                                  "status": item.status, "created_at": item.created_at}
                                 for item in pending],
            "messages": [{"message_id": item.message_id, "conversation_id": item.conversation_id,
                          "from_agent_id": item.from_agent_id, "to_agent_id": item.to_agent_id,
                          "content": item.content, "created_at": item.created_at,
                          "delivered_at": item.delivered_at} for item in undelivered],
            "conversations": [conversation_data(db, item) for item in conversations],
        }

    @app.get("/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, request: Request, db: Session = Depends(db_session)):
        conversation = db.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(404, "Conversation not found")
        token = require_token(request)
        agent = db.get(Agent, conversation.initiator_id)
        recipient = db.get(Agent, conversation.recipient_id)
        if not ((agent and agent.token_hash and hmac.compare_digest(agent.token_hash, hash_token(token))) or
                (recipient and recipient.token_hash and hmac.compare_digest(recipient.token_hash, hash_token(token)))):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent token")
        rows = db.scalars(select(Message).where(
            Message.conversation_id == conversation_id).order_by(Message.sequence)).all()
        return {**conversation_data(db, conversation), "messages": [
            {"message_id": row.message_id, "from_agent_id": row.from_agent_id,
             "to_agent_id": row.to_agent_id, "sequence": row.sequence,
             "content": row.content, "created_at": row.created_at,
             "delivered_at": row.delivered_at} for row in rows
        ]}

    @app.post("/conversations/{conversation_id}/messages")
    def post_message(conversation_id: str, payload: MessageCreate,
                     request: Request, db: Session = Depends(db_session)):
        sender = authenticate(db, request, payload.from_agent_id)
        conversation = member_conversation(db, conversation_id, sender.agent_id)
        other_id = (conversation.recipient_id if sender.agent_id == conversation.initiator_id
                    else conversation.initiator_id)
        count = payload.expected_count + 1
        result = db.execute(update(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.message_count == payload.expected_count,
            Conversation.next_agent_id == sender.agent_id,
            Conversation.status == "active",
            Conversation.message_count < Conversation.max_messages,
        ).values(message_count=count, next_agent_id=other_id,
                 status="completed" if count >= conversation.max_messages else "active"))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Turn already handled, not your turn, or conversation complete")
        message = Message(message_id=new_id("message"), conversation_id=conversation_id,
                          from_agent_id=sender.agent_id, to_agent_id=other_id,
                          content=payload.content, sequence=count)
        db.add(message)
        db.commit()
        return {"message_id": message.message_id, "sequence": count, "to_agent_id": other_id,
                "status": "completed" if count >= conversation.max_messages else "active"}

    return app


app = create_app()


def serve() -> None:
    import uvicorn
    uvicorn.run("ylobook_backend.main:app", host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", "8000")))
