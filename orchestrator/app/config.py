from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://factory:factory@localhost:5432/factory"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    max_fix_attempts: int = 5
    workspace_root: str = "/data/workspaces"
    api_key: str | None = None  # Set in production to require X-API-Key header
    worker_enabled: bool = True
    input_request_timeout_seconds: int = 300  # Auto-resolve after 5 min without human response
    intake_form_timeout_hours: int = 72  # Auto-submit intake with defaults after 72h
    secrets_encryption_key: str | None = None  # Fernet key or passphrase; required in production
    preview_host: str = "localhost"  # Hostname used in live preview URLs shown in the dashboard
    preview_port_start: int = 9010
    preview_port_end: int = 9039
    # Agent backend: cursor_cloud (default), cursor_local, or local (deterministic scaffold)
    agent_backend: str = "cursor_cloud"
    cursor_api_key: str | None = None  # Fallback when no dashboard connection
    cursor_agent_model: str = "composer-2"
    cursor_cloud_poll_seconds: float = 5.0
    cursor_cloud_timeout_seconds: int = 3600
    # Deployment — optional overrides; most settings are auto or configured in the dashboard
    public_host: str | None = None  # Hostname for preview links and public API URLs
    api_port: int = 8000
    dashboard_port: int = 8044
    cors_allow_all: bool = True  # Allow any origin when True (simple self-hosted deploy)
    trust_proxy_headers: bool = True  # Trust X-Forwarded-* from gateway (Caddy)

    @field_validator("trust_proxy_headers", mode="before")
    @classmethod
    def parse_trust_proxy(cls, v):
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return v

    @field_validator("cors_allow_all", mode="before")
    @classmethod
    def parse_cors_allow_all(cls, v):
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return v

    @field_validator("worker_enabled", mode="before")
    @classmethod
    def parse_bool(cls, v):
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v


settings = Settings()
