import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    REDIS_URL: str = "redis://localhost:6379/0"
    TASKS_STREAM: str = "apilogger:tasks"
    RESULTS_STREAM: str = "apilogger:results"
    TASKS_GROUP: str = "checkers"

    # Unique identity for this node — set via env var in docker-compose
    NODE_ID: str = f"checker-{socket.gethostname()}"

    # How many check tasks to process concurrently
    CONCURRENCY: int = 20

    # Block time waiting for new tasks (ms)
    BLOCK_MS: int = 2_000

    # Retry config for HTTP probes
    MAX_PROBE_RETRIES: int = 2
    RETRY_BACKOFF_BASE_MS: int = 200

    ENV: str = "development"


settings = Settings()
