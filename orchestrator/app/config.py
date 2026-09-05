from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://factory:factory@localhost:5432/factory"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    max_fix_attempts: int = 5
    max_enrichment_passes: int = 4
    max_features_per_enrichment_pass: int = 8
    enrichment_features_per_agent: int = 4
    enrichment_fix_attempts_per_pass: int = 3
    post_production_enrichment_passes: int = 3
    post_production_features_per_pass: int = 8
    post_production_milestones_per_pass: int = 2
    post_production_interval_hours: int = 24
    default_token_budget_per_cycle: int = 500_000
    workspace_root: str = "/data/workspaces"
    factory_config_dir: str = "/data/config"  # Persistent config (encryption key, local.env)
    api_key: str | None = None  # Set in production to require X-API-Key header
    worker_enabled: bool = True
    input_request_timeout_seconds: int = 300  # Auto-resolve after 5 min without human response
    intake_form_timeout_hours: int = 72  # Auto-submit intake with defaults after 72h
    secrets_encryption_key: str | None = None  # Fernet key or passphrase; required in production
    preview_host: str = "localhost"  # Hostname used in live preview URLs shown in the dashboard
    preview_internal_port_start: int = 10000
    preview_internal_port_end: int = 10099
    preview_docker_network: str = "factory-preview"
    preview_port_start: int = 9010  # legacy — not published on host in gateway deploys
    preview_port_end: int = 9039
    # Agent backend: cursor_cloud (default), cursor_local, or local (deterministic scaffold)
    agent_backend: str = "cursor_cloud"
    cursor_api_key: str | None = None  # Fallback when no dashboard connection
    github_token: str | None = None  # Factory-wide GitHub PAT for pushing branches (or use project secret)
    cursor_agent_model: str = "composer-2"
    cursor_cloud_poll_seconds: float = 5.0
    cursor_cloud_timeout_seconds: int = 3600
    cursor_api_timeout_seconds: float = 120.0  # HTTP timeout for Cursor Cloud API calls
    # Parallel agent limits — factory stays under Cursor subscription concurrent agent caps
    max_parallel_agents: int = 4
    cursor_concurrent_agent_limit: int = 8  # Typical Pro plan; override via dashboard or env
    cursor_agent_headroom: int = 2  # Reserve slots for agents you start outside the factory
    # Verification & measurement
    adversary_enabled: bool = True  # Adversarial verification stage before acceptance
    user_journey_testing_enabled: bool = True  # Simulated user session before production review
    agent_tester_enabled: bool = True  # LLM tester writes tests/acceptance/ when a backend is available
    deploy_observation_seconds: int = 30  # Post-deploy health observation window
    deploy_observation_polls: int = 3  # Health checks spread across the window
    auto_promote_to_production: bool = True  # Promote to production after review without manual click
    change_budget_files: int = 8  # Soft threshold when enforcement is enabled
    change_budget_lines: int = 500
    enforce_change_budget: bool = False  # Default: unlimited — no review blocks on change size
    disable_docker: bool = False  # Force simulated docker paths (benchmarks / CI)
    # Resource caps for factory-launched preview/staging containers ("" disables)
    preview_memory_limit: str = "768m"
    preview_cpus: str = "1.0"
    preview_pids_limit: int = 256
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
