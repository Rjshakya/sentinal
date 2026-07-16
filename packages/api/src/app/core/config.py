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

    # --- LLM (review agent) ---
    llm_provider: str = Field(
        default="openai",
        description="Active LLM provider tag for the review/setup agent "
        "('openai', 'anthropic', or 'google'). Validated at call time "
        "by build_chat_model; unknown values raise ValueError.",
    )
    llm_base_url: str = Field(
        default="",
        description="Base URL for the chat model used by the review agent "
        "(e.g. https://api.openai.com/v1, or a custom OpenAI-compatible "
        "endpoint). Leave empty to disable review routes.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for the review-agent chat model. Falls back to "
        "openai_api_key when blank.",
    )
    llm_model: str = Field(
        default="",
        description="Model name passed to ChatOpenAI (e.g. gpt-5.5, "
        "claude-sonnet-4-6 via a proxy, etc.).",
    )

    # --- GitHub App ---
    github_app_id: str = Field(
        default="",
        description="GitHub App numeric id.",
    )
    github_app_client_id: str = Field(
        default="",
        description="GitHub App OAuth client id.",
    )
    github_app_client_secret: str = Field(
        default="",
        description="GitHub App OAuth client secret.",
    )
    github_app_slug: str = Field(
        default="",
        description="GitHub App slug (the human-readable url segment).",
    )
    github_app_private_key: str = Field(
        default="",
        description=(
            "GitHub App private key (PEM). Newlines may be encoded as "
            "the literal sequence '\\n' in the env var."
        ),
    )
    github_app_private_key_path: str = Field(
        default="",
        description=(
            "Filesystem path to the GitHub App private key. When set, "
            "takes precedence over GITHUB_APP_PRIVATE_KEY."
        ),
    )

    # --- GitHub webhook ---
    github_webhook_secret: str = Field(
        default="",
        description="Shared secret used to verify GitHub webhook "
        "deliveries via the X-Hub-Signature-256 header. Leave empty to "
        "reject all webhook deliveries.",
    )

    # --- GitHub App install flow ---
    github_install_state_secret: str = Field(
        default="",
        description="HMAC secret used to sign the GitHub App install "
        "flow's state token. Falls back to workos_cookie_password when "
        "blank.",
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
    def llm_configured(self) -> bool:
        """True when the review-agent LLM is fully configured.

        Requires a model name, a base URL, and an API key (either the
        dedicated ``llm_api_key`` or a fallback to ``openai_api_key``).
        """
        return bool(
            self.llm_model
            and self.llm_base_url
            and (self.llm_api_key or self.openai_api_key)
        )

    @property
    def github_webhook_configured(self) -> bool:
        """True when a webhook secret is set and deliveries can be verified."""
        return bool(self.github_webhook_secret)

    @property
    def github_install_state_effective_secret(self) -> str:
        """The HMAC secret used to sign and verify install-flow state tokens."""
        return self.github_install_state_secret or self.workos_cookie_password

    @property
    def github_app_configured(self) -> bool:
        """True when the four required GitHub App fields are set."""
        return bool(
            self.github_app_id
            and self.github_app_client_id
            and self.github_app_client_secret
            # and self.github_app_private_key
            and self.github_app_slug
        )

    @property
    def github_app_install_url(self) -> str:
        """The github.com URL the dashboard's Connect button points at."""
        return f"https://github.com/apps/{self.github_app_slug}/installations/new"

    @property
    def cookie_secure(self) -> bool:
        return self.frontend_url.startswith("https://")

    @property
    def cognee_dataset_prefix(self) -> str:
        return "sentinel:repo:"


settings = Settings()
