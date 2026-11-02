import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load the project-root .env regardless of the directory used to start Uvicorn.
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)

class Settings(BaseSettings):
    app_name: str = "AgentOS API"
    database_url: str = "postgresql+psycopg://agentos:agentos_dev_password@localhost:5432/agentos"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    agent_files_dir: Path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgentOS" / "files"

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

settings = Settings()
