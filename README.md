# AgentOS — Groq starter project

A beginner-friendly local starter for a dark SaaS AI workspace: Next.js + Tailwind frontend, FastAPI backend, Groq chat completions with tool calling, PostgreSQL persistence, and Redis in Docker.

> **Scope:** This is a local MVP starter, not a finished autonomous production agent. It supports chat history, task notes, and limited Word/Excel file tools. File access is restricted to `%LOCALAPPDATA%\AgentOS\files` on Windows (or the equivalent local data directory on other platforms). Creating a file never overwrites an existing file; editing or renaming an existing file requires approval in the chat UI. It does not include login, multi-user isolation, external integrations, or production-grade audit/rate-limit controls. Do not expose it publicly.

## Requirements (Windows 11)
- Python 3.11 or newer
- Node.js LTS (20.9 or newer)
- Git (optional for the first run)
- Docker Desktop with the WSL 2 backend
- Visual Studio Code (recommended)
- A Groq API key from https://console.groq.com/

## 1. Configure your private environment file
1. In File Explorer, open the `AgentOS` project folder.
2. Copy `.env.example` and rename the copy to `.env`. (Make sure it is not named `.env.txt`.)
3. Open `.env` in VS Code and replace `replace_with_your_groq_api_key` with your Groq key.
4. Check the currently supported model IDs at https://console.groq.com/docs/models. If the example model is unavailable, change `GROQ_MODEL` to an available chat model.
5. Save the file. **Never paste your key into chat, frontend code, screenshots, or Git.**

## 2. Start PostgreSQL and Redis
Open PowerShell in the project folder and run:

```powershell
docker compose up -d db redis
```

This starts the database and Redis in the background. The database data is kept in a Docker volume.

## 3. Set up and start the Python backend
Open a new PowerShell window in the project folder and run these commands one at a time:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

If PowerShell blocks virtual-environment activation, run this once in that PowerShell window, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Backend health check: http://localhost:8000/health
API documentation: http://localhost:8000/docs

## 4. Set up and start the Next.js frontend
Keep the backend window running. Open a **second** PowerShell window in the project folder:

```powershell
cd frontend
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

## 5. Stop the services
- In each PowerShell window running the backend or frontend, press `Ctrl+C`.
- To stop the Docker database and Redis containers, run from the project folder:

```powershell
docker compose down
```

To also delete the local database volume and all saved development data, use `docker compose down -v`. Do not run that unless you really want to erase the data.

## Project layout

```text
AgentOS/
├── backend/
│   ├── app/
│   │   ├── core/config.py       # Environment and Groq settings
│   │   ├── db/session.py        # PostgreSQL connection
│   │   ├── agent.py             # Groq tool-calling loop and allowlist
│   │   ├── files.py             # Restricted Word and Excel file operations
│   │   ├── models.py            # Conversations, messages, notes, approvals
│   │   ├── schemas.py           # API request/response validation
│   │   └── main.py              # FastAPI endpoints
│   └── requirements.txt
├── frontend/
│   ├── app/                     # Next.js pages and styles
│   ├── package.json
│   └── .env.local.example
├── docker-compose.yml           # PostgreSQL and Redis
├── .env.example                 # Private backend configuration template
└── README.md
```

## Current API endpoints
- `GET /health` — backend health check
- `POST /api/chat` — send a chat message (optional `conversation_id`)
- `POST /api/approvals/{id}` — approve or reject one exact pending file edit/rename
- `GET /api/approvals` — list pending file changes awaiting approval
- `GET /api/files` — list Word and Excel files in the private AgentOS folder
- `POST /api/files` — upload a validated `.docx` or `.xlsx` file (10 MB maximum; existing files are never overwritten)
- `GET /api/files/{filename}` — download a Word document or Excel workbook from the private AgentOS folder
- `GET /api/conversations` — list recent conversations
- `GET /api/conversations/{id}` — get one conversation and its messages

## File tools and safety
- Ask AgentOS to list its files, create a Word document or Excel workbook, edit a document/cell, or rename a file.
- Use the **+** button beside the chat input to upload a `.docx` or `.xlsx` file (up to 10 MB). AgentOS validates the Office file, places it in the dedicated folder without overwriting an existing file, and can then inspect it to help with a requested edit.
- To edit an existing file, click **Update** next to it in the app and describe the exact change. For Word, specify the text to find and its replacement. For Excel, specify the sheet, cell, and new value. The app asks the model to clarify rather than guess when those details are missing.
- New and uploaded files are stored only in `%LOCALAPPDATA%\AgentOS\files` on Windows. The backend accepts filenames only and blocks path traversal and unsupported extensions.
- An existing file is never silently overwritten on creation. Edits and renames create an exact pending approval; the backend performs them only when the user clicks **Approve change**. If the file changed after the approval request, approval is rejected and must be requested again.
- Word text replacement operates on paragraph text and may simplify mixed character formatting in paragraphs it edits. Excel tools support plain text values, not formulas.

The model is not a security boundary. This MVP still has no user accounts or production-grade audit/rate-limit controls. Do not expose it publicly, and never give the model unrestricted shell or filesystem access.
