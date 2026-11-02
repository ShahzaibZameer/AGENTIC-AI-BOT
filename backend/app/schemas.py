from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation_id: int | None = None


class ApprovalOut(BaseModel):
    id: str
    conversation_id: int
    operation: str
    summary: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    conversation_id: int
    response: str
    pending_approvals: list[ApprovalOut] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")


class ApprovalResult(BaseModel):
    id: str
    status: str
    message: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    messages: list[MessageOut]
    model_config = ConfigDict(from_attributes=True)
