from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
AgentID = Annotated[str, StringConstraints(pattern=r"^agent_[a-zA-Z0-9_\-]{1,90}$")]
RequestID = Annotated[str, StringConstraints(pattern=r"^request_[a-zA-Z0-9_\-]{1,90}$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentCreate(Input):
    agent_id: AgentID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    interests: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]] = Field(min_length=1, max_length=5)


class ContactCreate(Input):
    request_id: RequestID
    from_agent_id: AgentID
    to_agent_id: AgentID
    purpose: Text


class MessageCreate(Input):
    from_agent_id: AgentID
    content: Text
    expected_count: int = Field(ge=0)
