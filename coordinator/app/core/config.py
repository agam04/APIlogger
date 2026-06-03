from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Service identity
    SERVICE_NAME: str = "apilogger-coordinator"
    ENV: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://apilogger:apilogger@localhost:5432/apilogger"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 h

    # Quorum: fraction of active checker nodes that must agree on 'down'
    QUORUM_FRACTION: float = 0.51
    # Window (seconds) in which quorum votes are counted
    QUORUM_WINDOW_SECS: int = 120

    # AI — provider is chosen automatically:
    #   1. Anthropic if ANTHROPIC_API_KEY is set
    #   2. Groq (free tier) if GROQ_API_KEY is set
    #   3. Disabled otherwise
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-sonnet-4-6"          # used when Anthropic is active
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"  # fast, free-tier Groq model
    AI_ENABLED: bool = True

    # Alerting
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_FROM_EMAIL: str = "alerts@apilogger.dev"

    # Redis stream names
    TASKS_STREAM: str = "apilogger:tasks"
    RESULTS_STREAM: str = "apilogger:results"
    TASKS_GROUP: str = "checkers"
    RESULTS_GROUP: str = "coordinator"
    EVENTS_CHANNEL: str = "apilogger:events"  # pub/sub for SSE

    # Scheduler
    SCHEDULER_JITTER_SECS: int = 5  # randomise start times to spread load

    @field_validator("QUORUM_FRACTION")
    @classmethod
    def validate_quorum(cls, v: float) -> float:
        if not 0.0 < v <= 1.0:
            raise ValueError("QUORUM_FRACTION must be in (0, 1]")
        return v


settings = Settings()
