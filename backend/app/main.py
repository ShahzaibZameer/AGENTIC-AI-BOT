import json
import logging
import tempfile
from pathlib import Path

from groq import RateLimitError
from fastapi import FastAPI, Depends, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import Base, engine, get_db
from app.files import (
    MAX_FILE_SIZE,
    downloadable_file_path,
    ensure_files_directory,
    execute_approved_operation,
    list_files,
    store_uploaded_file,
)
from app.models import Conversation, Message, PendingApproval
from app.schemas import (
    ApprovalDecision,
    ApprovalOut,
    ApprovalResult,
    ChatRequest,
    ChatResponse,
    ConversationOut,
)
from app.agent import run_agent

logger = logging.getLogger(__name__)

# For this starter only. Use Alembic migrations in production.
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "agentos-api"}


@app.get("/api/files")
def get_files():
    return list_files(settings.agent_files_dir)


@app.post("/api/files", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    temporary_path = None
    try:
        destination_directory = ensure_files_directory(settings.agent_files_dir)
        with tempfile.NamedTemporaryFile(
            dir=destination_directory,
            prefix=".agentos-upload-",
            suffix=Path(filename).suffix.lower(),
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            size = 0
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="Uploads are limited to 10 MB.")
                temporary.write(chunk)
        message = store_uploaded_file(
            destination_directory,
            filename,
            Path(temporary_path),
        )
        return {
            "filename": filename,
            "type": Path(filename).suffix[1:].lower(),
            "message": message,
        }
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        await file.close()


@app.get("/api/files/{filename}")
def download_file(filename: str):
    try:
        path = downloadable_file_path(settings.agent_files_dir, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    if not settings.groq_api_key.strip():
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured. Add it to the project-root .env file and restart the backend.",
        )

    if payload.conversation_id is None:
        conversation = Conversation(title=payload.message[:60])
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    else:
        conversation = db.get(Conversation, payload.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    user_message = Message(
        conversation_id=conversation.id, role="user", content=payload.message
    )
    db.add(user_message)
    db.commit()

    try:
        answer = await run_agent(conversation.id, db)
    except RateLimitError as exc:
        db.rollback()
        logger.warning("Groq rate limit reached for conversation %s", conversation.id)
        raise HTTPException(
            status_code=429,
            detail="Groq rate limit reached. Wait a minute and try again.",
        ) from exc
    except Exception as exc:
        db.rollback()
        # Avoid leaking provider details, secrets, or stack traces to the client.
        logger.exception("Agent execution failed for conversation %s", conversation.id)
        raise HTTPException(status_code=502, detail="Agent execution failed") from exc

    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer))
    db.commit()
    pending_approvals = db.execute(
        select(PendingApproval)
        .where(
            PendingApproval.conversation_id == conversation.id,
            PendingApproval.status == "pending",
        )
        .order_by(PendingApproval.created_at)
    ).scalars().all()
    return ChatResponse(
        conversation_id=conversation.id,
        response=answer,
        pending_approvals=[ApprovalOut.model_validate(item) for item in pending_approvals],
    )


@app.post("/api/approvals/{approval_id}", response_model=ApprovalResult)
def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    db: Session = Depends(get_db),
):
    approval = db.get(PendingApproval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"This approval is already {approval.status}.")

    conversation = db.get(Conversation, approval.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if decision.action == "reject":
        claimed = db.execute(
            update(PendingApproval)
            .where(PendingApproval.id == approval.id, PendingApproval.status == "pending")
            .values(status="rejected")
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="This approval has already been handled.")
        approval.status = "rejected"
        message = "Approval rejected. No file changes were made."
    else:
        claimed = db.execute(
            update(PendingApproval)
            .where(PendingApproval.id == approval.id, PendingApproval.status == "pending")
            .values(status="executing")
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="This approval has already been handled.")
        approval.status = "executing"
        db.commit()
        try:
            answer = execute_approved_operation(
                settings.agent_files_dir,
                approval.operation,
                json.loads(approval.arguments),
                approval.target_hash,
            )
        except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            db.refresh(approval)
            approval.status = "failed"
            db.commit()
            logger.warning("Approved file operation %s failed: %s", approval.id, exc)
            raise HTTPException(status_code=409, detail=f"File operation failed: {exc}") from exc
        except Exception as exc:
            db.refresh(approval)
            approval.status = "failed"
            db.commit()
            logger.exception("Approved file operation %s failed", approval.id)
            raise HTTPException(status_code=500, detail="Approved file operation failed.") from exc
        db.refresh(approval)
        approval.status = "approved"
        message = f"Approved and completed: {answer}"

    db.add(Message(conversation_id=conversation.id, role="assistant", content=message))
    db.commit()
    return ApprovalResult(id=approval.id, status=approval.status, message=message)


@app.get("/api/approvals", response_model=list[ApprovalOut])
def list_pending_approvals(db: Session = Depends(get_db)):
    approvals = db.execute(
        select(PendingApproval)
        .where(PendingApproval.status == "pending")
        .order_by(PendingApproval.created_at)
        .limit(50)
    ).scalars().all()
    return [ApprovalOut.model_validate(approval) for approval in approvals]


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    stmt = (
        select(Conversation)
        .options(joinedload(Conversation.messages))
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    return db.execute(stmt).unique().scalars().all()


@app.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(joinedload(Conversation.messages))
    )
    conversation = db.execute(stmt).unique().scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
