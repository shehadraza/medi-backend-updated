
import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    MEDI_SUPER_ADMIN_EMAIL: str = ""
    APP_NAME: str = "MEDI API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/medi_db"

    SECRET_KEY: str = "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET"
    ENCRYPTION_KEY: str = ""

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    FRONTEND_URL: str = "http://localhost:3000"

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_USE_TLS: bool = True

    # Background reminder worker
    REMINDER_WORKER_INTERVAL_SECONDS: int = 30
    REMINDER_DOSE_GRACE_MINUTES: int = 60
    REMINDER_GENERATION_HORIZON_MINUTES: int = 1440
    REMINDER_GENERATION_LOOKBACK_MINUTES: int = 1440

    # Optional AI integrations. Ollama is contacted only when selected.
    AI_LLM_PROVIDER: str = "ollama"
    AI_CHAT_MODEL: str = ""
    AI_EMBEDDING_PROVIDER: str = "ollama"
    AI_EMBEDDING_MODEL: str = "bge-m3:latest"
    AI_PROVIDER_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0, le=300)
    AI_MAX_OUTPUT_TOKENS: int = Field(default=1024, ge=1, le=8192)
    AI_RAG_TOP_K: int = Field(default=5, ge=1, le=20)
    AI_RAG_CHUNK_SIZE: int = Field(default=1200, ge=100, le=10000)
    AI_RAG_CHUNK_OVERLAP: int = Field(default=180, ge=0, le=2000)
    AI_RATE_LIMIT_REQUESTS: int = Field(default=20, ge=1, le=1000)
    AI_RATE_LIMIT_WINDOW_SECONDS: float = Field(default=60.0, gt=0, le=3600)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    AI_KNOWLEDGE_SYNC_ENABLED: bool = False
    AI_KNOWLEDGE_SYNC_INTERVAL_HOURS: int = Field(default=24, ge=1, le=720)
    AI_KNOWLEDGE_SYNC_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0, le=120)
    AI_KNOWLEDGE_SYNC_RETRY_SECONDS: int = Field(default=60, ge=5, le=3600)
    # NCBI asks API clients to identify themselves with a valid contact address.
    # PubMed synchronization stays unavailable until an operator configures one.
    AI_NCBI_CONTACT_EMAIL: str = ""
    AI_MEDICINE_MAX_AGE_DAYS: int = Field(default=365, ge=1, le=3650)

    model_config = SettingsConfigDict(
        env_file=None if os.environ.get("MEDI_TEST_MODE") == "1" else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        
    )


settings = Settings()
MEDI_SUPER_ADMIN_EMAIL: str = ""
