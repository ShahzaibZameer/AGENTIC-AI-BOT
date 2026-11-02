import json
import secrets

from groq import AsyncGroq
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.files import (
    create_excel_workbook,
    create_word_document,
    file_hash,
    list_files,
    read_excel_cell,
    read_excel_workbook,
    read_word_document,
    validate_file_rename,
    validate_spreadsheet_value,
)
from app.models import Message, PendingApproval, TaskNote

SYSTEM_PROMPT = f"""You are AgentOS, a practical AI automation assistant. Help users plan work clearly.
You can save a task note and manage Word (.docx) and Excel (.xlsx) files in this dedicated folder:
{settings.agent_files_dir}
You may list files in that folder, read their contents, create new documents/workbooks, request edits, and request renames.
The backend restricts every file operation to that folder. Never ask for credentials or access other folders.
Creating a new file never overwrites an existing file. Editing or renaming an existing file only creates a
pending approval; it does not change anything until the user approves the exact action using the app's
approval button. Never claim an edit or rename is complete before the backend confirms approval and success.
Before requesting an edit, make sure the user specified the exact Word text to replace and its replacement,
or the Excel sheet, cell, and new value. Ask a follow-up question instead of guessing. The approval card
shows the exact change for the user to review. If approval is pending, tell the user to approve or reject
it in the app. Excel values are plain text; formulas are not supported. Be honest about limitations and
never claim an action happened unless a tool confirms it."""


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOLS = [
    _function(
        "create_task_note",
        "Save a harmless task note in the AgentOS database.",
        {"title": {"type": "string"}, "description": {"type": "string"}},
        ["title", "description"],
    ),
    _function("list_agent_files", "List Word and Excel files in the dedicated AgentOS files folder.",
              {}, []),
    _function(
        "read_word_document",
        "Read the text from a Word document in the AgentOS files folder so you can answer questions or determine precise requested edits.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),
    _function(
        "read_excel_workbook",
        "Read sheet names and a bounded preview of cell values from an Excel workbook in the AgentOS files folder.",
        {"filename": {"type": "string"}},
        ["filename"],
    ),
    _function(
        "create_word_document",
        "Create a new Word document. It will not overwrite an existing file.",
        {"filename": {"type": "string", "description": "Filename ending in .docx"},
         "title": {"type": "string"}, "content": {"type": "string"}},
        ["filename", "title", "content"],
    ),
    _function(
        "create_excel_workbook",
        "Create a new Excel workbook with a header row and plain-text data. It will not overwrite an existing file.",
        {"filename": {"type": "string", "description": "Filename ending in .xlsx"},
         "sheet_name": {"type": "string"},
         "headers": {"type": "array", "items": {"type": "string"}},
         "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}},
        ["filename", "sheet_name", "headers", "rows"],
    ),
    _function(
        "update_word_document",
        "Request approval to replace exact text in an existing Word document.",
        {"filename": {"type": "string"}, "find_text": {"type": "string"},
         "replace_text": {"type": "string"}},
        ["filename", "find_text", "replace_text"],
    ),
    _function(
        "update_excel_cell",
        "Request approval to replace a cell value in an existing Excel workbook. Values must be plain text, not formulas.",
        {"filename": {"type": "string"}, "sheet_name": {"type": "string"},
         "cell": {"type": "string"}, "value": {"type": "string"}},
        ["filename", "sheet_name", "cell", "value"],
    ),
    _function(
        "rename_agent_file",
        "Request approval to rename an existing Word document or Excel workbook without changing its type.",
        {"filename": {"type": "string"}, "new_filename": {"type": "string"}},
        ["filename", "new_filename"],
    ),
]

_APPROVAL_OPERATIONS = {"update_word_document", "update_excel_cell", "rename_agent_file"}
MAX_OUTPUT_TOKENS = 800


def _create_approval(name: str, arguments: dict, conversation_id: int, db: Session) -> str:
    filename = arguments.get("filename")
    if not isinstance(filename, str):
        raise ValueError("A filename is required.")
    digest = file_hash(settings.agent_files_dir, filename)
    if name == "update_word_document":
        find_text = arguments.get("find_text")
        replace_text = arguments.get("replace_text")
        if not isinstance(find_text, str) or not find_text:
            raise ValueError("Text to find must not be empty.")
        if not isinstance(replace_text, str):
            raise ValueError("Replacement text must be text.")
        summary = (
            f"Replace { _preview(find_text) } with { _preview(replace_text) } in {filename}"
        )
    elif name == "update_excel_cell":
        new_value = arguments.get("value")
        if not isinstance(new_value, str):
            raise ValueError("The replacement cell value must be text.")
        validate_spreadsheet_value(new_value)
        old_value = read_excel_cell(
            settings.agent_files_dir,
            filename,
            arguments.get("sheet_name"),
            arguments.get("cell"),
        )
        summary = (
            f"Change {filename} {arguments.get('sheet_name')}!{arguments.get('cell')} "
            f"from { _preview(old_value) } to { _preview(new_value) }"
        )
    else:
        new_filename = arguments.get("new_filename")
        if not isinstance(new_filename, str):
            raise ValueError("A new filename is required.")
        validate_file_rename(settings.agent_files_dir, filename, new_filename)
        summary = f"Rename {filename} to {new_filename}"
    approval = PendingApproval(
        id=secrets.token_urlsafe(32),
        conversation_id=conversation_id,
        operation=name,
        arguments=json.dumps(arguments),
        summary=summary[:500],
        target_hash=digest,
    )
    db.add(approval)
    db.flush()
    return json.dumps({
        "status": "approval_required",
        "approval_id": approval.id,
        "summary": approval.summary,
        "message": "No file has been changed. The user must approve this exact action in the app.",
    })


def _preview(value: str, limit: int = 100) -> str:
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    if len(value) > limit:
        value = value[:limit] + "…"
    return json.dumps(value, ensure_ascii=False)


def execute_tool(name: str, arguments: dict, conversation_id: int, db: Session) -> str:
    if name == "create_task_note":
        title = str(arguments.get("title", "")).strip()[:200]
        description = str(arguments.get("description", "")).strip()[:10000]
        if not title:
            return "Error: title cannot be empty."
        note = TaskNote(title=title, description=description)
        db.add(note)
        db.flush()
        return f"Saved note #{note.id}: {note.title}"
    if name == "list_agent_files":
        return json.dumps(list_files(settings.agent_files_dir))
    if name == "read_word_document":
        return read_word_document(settings.agent_files_dir, **arguments)
    if name == "read_excel_workbook":
        return read_excel_workbook(settings.agent_files_dir, **arguments)
    if name == "create_word_document":
        return create_word_document(settings.agent_files_dir, **arguments)
    if name == "create_excel_workbook":
        return create_excel_workbook(settings.agent_files_dir, **arguments)
    if name in _APPROVAL_OPERATIONS:
        return _create_approval(name, arguments, conversation_id, db)
    return "Error: this tool is not allowed."


async def run_agent(conversation_id: int, db: Session) -> str:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured. Add it to the project .env file.")
    client = AsyncGroq(api_key=settings.groq_api_key)
    history = db.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).scalars().all()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": item.role, "content": item.content}
                    for item in history if item.role in ("user", "assistant"))

    for _ in range(6):
        result = await client.chat.completions.create(
            model=settings.groq_model, messages=messages, tools=TOOLS, tool_choice="auto",
            temperature=0.3, max_tokens=MAX_OUTPUT_TOKENS
        )
        assistant_message = result.choices[0].message
        if not assistant_message.tool_calls:
            return assistant_message.content or "I couldn't produce a response. Please try again."
        messages.append({
            "role": "assistant",
            "content": assistant_message.content,
            "tool_calls": [call.model_dump(exclude_none=True) for call in assistant_message.tool_calls]
        })
        for call in assistant_message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                output = execute_tool(call.function.name, args, conversation_id, db)
            except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
                output = f"Error: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
    return "I reached the tool-call limit for this request. Please ask me to continue."
