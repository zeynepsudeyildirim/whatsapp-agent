"""Runtime configuration, read from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WA_", extra="ignore")

    env: str = "dev"  # dev | staging | production

    # Meta WhatsApp Cloud API
    graph_api_version: str = "v23.0"
    graph_api_base: str = "https://graph.facebook.com"
    app_secret: SecretStr  # used to verify X-Hub-Signature-256
    verify_token: SecretStr  # used for the GET webhook handshake
    access_token: SecretStr  # system-user token for sending messages

    # Database
    database_url: str = "postgresql+asyncpg://localhost/waagent"

    # Queue: "inline" runs the worker in-process (dev/tests); "cloud_tasks" in staging/prod
    queue_backend: str = "inline"
    worker_url: str = "http://localhost:8080/tasks/process-message"
    cloud_tasks_queue: str = ""  # projects/<p>/locations/europe-west3/queues/<q>
    worker_auth_token: SecretStr = SecretStr("")  # shared secret checked by the worker endpoint


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
