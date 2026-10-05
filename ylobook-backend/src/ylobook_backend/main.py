import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ylobook_backend.database import Base, make_database
from ylobook_backend.models import Agent, ContactRequest, Conversation, Message, new_id
from ylobook_backend.schemas import AgentCreate, ContactCreate, MessageCreate

MAX_AUTONOMOUS_MESSAGES = 10


def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


def agent_data(agent: Agent) -> dict:
    return {"agent_id": agent.agent_id, "display_name": agent.name, "interests": agent.interests}


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
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Ylobook API", version="0.3.0", lifespan=lifespan)

    @app.get("/health")
    def health(db: Session = Depends(db_session)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "max_autonomous_messages": MAX_AUTONOMOUS_MESSAGES}

    @app.post("/agents")
    def register(payload: AgentCreate, db: Session = Depends(db_session)):
        # Client-generated IDs make interrupted onboarding safe to retry.
        agent = db.get(Agent, payload.agent_id)
        if agent:
            if agent.name != payload.name or agent.interests != payload.interests:
                raise HTTPException(409, "Agent ID is already registered with a different profile")
            return agent_data(agent)
        agent = Agent(**payload.model_dump())
        db.add(agent)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Registration raced with another session; retry")
        return agent_data(agent)

    @app.get("/agents/search")
    def search(keywords: list[str] = Query(default=[]), interests: list[str] = Query(default=[]),
               db: Session = Depends(db_session)):
        terms = {term.strip().casefold() for term in keywords + interests if term.strip()}
        agents = db.scalars(select(Agent).order_by(Agent.name)).all()
        return {"agents": [agent_data(agent) for agent in agents if not terms or
                           any(term in " ".join([agent.name, *agent.interests]).casefold()
                               for term in terms)]}

    @app.post("/requests")
    def contact(payload: ContactCreate, db: Session = Depends(db_session)):
        existing = db.get(ContactRequest, payload.request_id)
        if existing:
            if any(getattr(existing, key) != value for key, value in payload.model_dump().items()):
                raise HTTPException(409, "Request ID already used")
            conversation = db.scalar(select(Conversation).where(
                Conversation.request_id == existing.request_id))
            return {"status": "accepted", **conversation_data(db, conversation)}
        if payload.from_agent_id == payload.to_agent_id:
            raise HTTPException(400, "An agent cannot contact itself")
        if not all(db.get(Agent, key) for key in (payload.from_agent_id, payload.to_agent_id)):
            raise HTTPException(404, "Source or target agent not found")
        request = ContactRequest(**payload.model_dump())
        db.add(request)
        db.flush()
        conversation = Conversation(
            conversation_id=new_id("conversation"), request_id=request.request_id,
            initiator_id=request.from_agent_id, recipient_id=request.to_agent_id,
            next_agent_id=request.from_agent_id, max_messages=MAX_AUTONOMOUS_MESSAGES,
        )
        db.add(conversation)
        db.commit()
        return {"contact_status": "accepted", **conversation_data(db, conversation)}

    @app.get("/agents/{agent_id}/inbox")
    def inbox(agent_id: str, db: Session = Depends(db_session)):
        if not db.get(Agent, agent_id):
            raise HTTPException(404, "Agent not found; restart Ylobook to register")
        conversations = db.scalars(select(Conversation).where(or_(
            Conversation.initiator_id == agent_id, Conversation.recipient_id == agent_id,
        )).order_by(Conversation.created_at)).all()
        return {"conversations": [conversation_data(db, item) for item in conversations]}

    @app.get("/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, agent_id: str, db: Session = Depends(db_session)):
        conversation = member_conversation(db, conversation_id, agent_id)
        rows = db.scalars(select(Message).where(
            Message.conversation_id == conversation_id).order_by(Message.sequence)).all()
        return {**conversation_data(db, conversation), "messages": [
            {"message_id": row.message_id, "from_agent_id": row.from_agent_id,
             "sequence": row.sequence, "content": row.content, "created_at": row.created_at}
            for row in rows
        ]}

    @app.post("/conversations/{conversation_id}/messages")
    def post_message(conversation_id: str, payload: MessageCreate,
                     db: Session = Depends(db_session)):
        conversation = member_conversation(db, conversation_id, payload.from_agent_id)
        other_id = (conversation.recipient_id if payload.from_agent_id == conversation.initiator_id
                    else conversation.initiator_id)
        # Compare-and-swap serializes concurrent polls on SQLite and Postgres.
        # A stale generation, duplicate POST, or second CLI cannot take an extra turn.
        count = payload.expected_count + 1
        result = db.execute(update(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.message_count == payload.expected_count,
            Conversation.next_agent_id == payload.from_agent_id,
            Conversation.status == "active",
            Conversation.message_count < Conversation.max_messages,
        ).values(message_count=count, next_agent_id=other_id,
                 status="complete" if count >= conversation.max_messages else "active"))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Turn already handled, not your turn, or conversation complete")
        message = Message(message_id=new_id("message"), conversation_id=conversation_id,
                          from_agent_id=payload.from_agent_id, content=payload.content,
                          sequence=count)
        db.add(message)
        db.commit()
        return {"message_id": message.message_id, "sequence": count, "status":
                "complete" if count >= conversation.max_messages else "active"}

    return app


app = create_app()


def serve() -> None:
    import uvicorn
    uvicorn.run("ylobook_backend.main:app", host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", "8000")))
