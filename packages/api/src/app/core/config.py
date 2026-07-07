from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aicode",
        description="Async SQLAlchemy database URL.",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Allowed CORS origins (JSON array in env).",
    )
    api_prefix: str = Field(
        default="/api",
        description="URL prefix for all API routes.",
    )

    # --- WorkOS User Management ---
    workos_api_key: str = Field(
        default="",
        description="WorkOS API key. Leave empty to disable WorkOS-dependent routes.",
    )
    workos_client_id: str = Field(
        default="",
        description="WorkOS client id (User Management).",
    )
    workos_redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/callback",
        description="OAuth callback URL registered in WorkOS.",
    )
    workos_cookie_password: str = Field(
        default="",
        description="Password used to seal the WorkOS session cookie (>=32 chars).",
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Where to send the browser after a successful login.",
    )
    session_cookie_name: str = Field(
        default="wos_session",
        description="Name of the sealed session cookie.",
    )
    session_max_age_seconds: int = Field(
        default=60 * 60 * 24 * 7,
        description="Cookie / session lifetime in seconds.",
    )

    # --- Sandbox provider ---
    sandbox_provider: str = Field(
        default="e2b",
        description="Active sandbox provider tag ('e2b' or 'daytona').",
    )

    # --- E2B sandbox ---
    e2b_api_key: str = Field(
        # default="",
        description="E2B API key.",
    )
    e2b_template: str = Field(
        default="sentinel-indexing",
        description="E2B template name.",
    )
    e2b_cpu_count: int = Field(
        default=1,
        description="vCPU count for newly created E2B sandboxes.",
    )
    e2b_memory_mb: int = Field(
        default=1024,
        description="Memory (MB) for newly created E2B sandboxes.",
    )
    e2b_timeout_s: int = Field(
        default=600,
        description="Timeout (seconds) for newly created E2B sandboxes.",
    )

    # --- Daytona sandbox (kept for the adapter; the active provider is e2b by default) ---
    daytona_api_key: str = Field(
        default="",
        description="Daytona API key.",
    )
    daytona_template: str = Field(
        default="",
        description="Daytona image name.",
    )

    # --- Embeddings ---
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key. Injected into the indexing sandbox as "
        "OPENAI_API_KEY and used to compute text-embedding-3-large vectors. "
        "Leave empty to disable embedding-dependent routes.",
    )

    @property
    def daytona_configured(self) -> bool:
        return bool(self.daytona_api_key)

    @property
    def sandbox_configured(self) -> bool:
        """True when the active provider's API key is set."""
        if self.sandbox_provider == "e2b":
            return bool(self.e2b_api_key)
        if self.sandbox_provider == "daytona":
            return bool(self.daytona_api_key)
        return False

    @property
    def workos_configured(self) -> bool:
        return bool(
            self.workos_api_key
            and self.workos_client_id
            and self.workos_cookie_password
        )

    @property
    def embeddings_configured(self) -> bool:
        """True when an OpenAI key is set and embeddings can be computed."""
        return bool(self.openai_api_key)

    @property
    def cookie_secure(self) -> bool:
        return self.frontend_url.startswith("https://")

    @property
    def cognee_dataset_prefix(self) -> str:
        return "sentinel:repo:"


print(f"DEBUG: Looking for .env at: {BASE_DIR / '.env'}")
print(f"DEBUG: File exists: {(BASE_DIR / '.env').exists()}")

settings = Settings()
