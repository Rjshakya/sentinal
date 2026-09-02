import os
import socket
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.llm import LLMConfig

BASE_DIR = Path(__file__).resolve().parents[3]


# Provider prefix -> env-var name expected by the underlying SDK.
# Used by :meth:`Settings.llm_configured` to decide whether the active
# provider can pick up its API key from the environment when
# ``LLM_API_KEY`` is blank.
_PROVIDER_ENV_KEY: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "google_vertexai": "GOOGLE_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "azure_ai": "AZURE_AI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "perplexity": "PPLX_API_KEY",
    "upstage": "UPSTAGE_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "ibm": "IBM_API_KEY",
    "huggingface": "HUGGINGFACEHUB_API_TOKEN",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "anthropic_bedrock": "AWS_ACCESS_KEY_ID",
    "bedrock_converse": "AWS_ACCESS_KEY_ID",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = Field(default=8000, description="Port")

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
        default="",
        description="E2B API key.",
    )
    e2b_template: str = Field(
        default="code-interpreter-v1",
        description=(
            "E2B template name. The default is the E2B-hosted "
            "'code-interpreter-v1' template, which requires no "
            "build. Set to a custom template slug to use a "
            "pre-baked image."
        ),
    )
    e2b_cpu_count: int = Field(
        default=2,
        description="vCPU count for newly created E2B sandboxes.",
    )
    e2b_memory_mb: int = Field(
        default=2048,
        description="Memory (MB) for newly created E2B sandboxes.",
    )
    e2b_timeout_s: int = Field(
        default=1200,
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

    # --- Embeddings (read by the in-sandbox indexing script) ---
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key. Read by the in-sandbox indexing "
        "script's LanceDB embedding function (``text-embedding-3-large``). "
        "Forwarded into the sandbox via the step's ``envs=`` kwarg — "
        "it never has to live in the API process env. Leave empty to "
        "disable indexing-dependent routes.",
    )

    # --- Indexing pipeline ---
    index_s3_bucket: str = Field(
        default="",
        description="S3 bucket holding the LanceDB vector datasets "
        "(``s3://<bucket>/<prefix>/<owner>/<repo>``). Required for "
        ":attr:`indexing_configured`.",
    )
    index_s3_prefix: str = Field(
        default="sentinel/lance",
        description="Key prefix under the S3 bucket for LanceDB datasets.",
    )

    aws_access_key_id: str = Field(
        default="",
        alias="AWS_ACCESS_KEY_ID",
        description="AWS access key id (forwarded into the indexing sandbox).",
    )
    aws_secret_access_key: str = Field(
        default="",
        alias="AWS_SECRET_ACCESS_KEY",
        description="AWS secret access key (forwarded into the indexing sandbox).",
    )
    aws_region: str = Field(
        default="",
        alias="AWS_REGION",
        description="AWS region (forwarded into the indexing sandbox).",
    )
    aws_endpoint_url: str = Field(
        default="",
        alias="AWS_ENDPOINT_URL",
        description="AWS endpoint URL for non-AWS S3 (MinIO, R2, etc.); "
        "forwarded into the indexing sandbox.",
    )
    aws_session_token: str = Field(
        default="",
        alias="AWS_SESSION_TOKEN",
        description="Optional AWS session token for temporary credentials.",
    )

    # --- LLM (review agent) ---
    # The combined "provider:model" string consumed by
    # langchain.chat_models.init_chat_model. Examples:
    #   LLM_MODEL=openai:gpt-5.5
    #   LLM_MODEL=anthropic:claude-opus-4-6
    #   LLM_MODEL=google_genai:gemini-3.6-flash
    # For OpenAI-compatible proxies / gateways (Cloudflare AI
    # Gateway, OpenCode Zen, Baseten, OpenRouter, Ollama, …) also
    # set LLM_BASE_URL and LLM_API_KEY; the provider prefix in
    # LLM_MODEL stays the same.
    llm_model: str = Field(
        default="",
        description=(
            'The combined "provider:model" string consumed by '
            "langchain.chat_models.init_chat_model. Examples: "
            "'openai:gpt-5.5', 'anthropic:claude-opus-4-6', "
            "'google_genai:gemini-3.6-flash'. Leave empty to "
            "disable review routes."
        ),
    )
    llm_api_key: str = Field(
        default="",
        description=(
            "API key for the active provider. When blank, the "
            "provider's native env-var resolution is used "
            "(OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY / "
            "…)."
        ),
    )
    llm_base_url: str = Field(
        default="",
        description=(
            "Base URL for the chat model. Required when proxying "
            "through an OpenAI-compatible gateway (Cloudflare AI "
            "Gateway, OpenCode Zen, Baseten, OpenRouter, Ollama, "
            "…). Leave empty for direct provider calls."
        ),
    )
    llm_default_headers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "JSON-encoded dict of HTTP headers attached to every "
            "LLM request (e.g. gateway identifiers, project tags). "
            "Forwarded as default_headers to providers that accept "
            "the kwarg; ignored by providers that don't."
        ),
    )
    llm_max_retries: int = Field(
        default=3,
        ge=0,
        description=(
            "Number of retries the underlying SDK will attempt on "
            "transient errors. 0 disables retries."
        ),
    )
    llm_rate_limit_rps: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "Client-side requests-per-second rate limit applied via "
            "langchain_core.rate_limiters.InMemoryRateLimiter. "
            "0 disables the limiter."
        ),
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

    # --- DBOS durable execution ---
    dbos_executor_id: str = Field(
        default=socket.gethostname(),
        description="Unique executor ID for this DBOS process. Must be "
        "unique per running API instance when self-hosting multiple workers.",
    )

    dbos_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/aicode",
        description="Async SQLAlchemy database URL.",
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

    # --- Telemetry (OpenLLMetry / traceloop-sdk) ---
    # Standard OTLP/HTTP trace export. The env vars keep the SDK-native
    # TRACELOOP_* names so they work even outside this settings object;
    # the fields are the telemetry_* surface consumed by
    # app.core.telemetry.
    telemetry_api_key: str = Field(
        default="",
        alias="TRACELOOP_API_KEY",
        description=(
            "Bearer token for the OTLP endpoint (Traceloop Cloud or any "
            "authenticated collector). Leave empty for unauthenticated "
            "endpoints."
        ),
    )
    telemetry_base_url: str = Field(
        default="",
        alias="TRACELOOP_BASE_URL",
        description=(
            "OTLP/HTTP endpoint for trace export, e.g. "
            "'http://localhost:4318'. The SDK appends '/v1/traces'; an "
            "http(s) prefix selects the OTLP/HTTP protocol. Leave both "
            "this and TRACELOOP_API_KEY empty to disable telemetry "
            "entirely (the SDK is never initialised)."
        ),
    )
    telemetry_trace_content: bool = Field(
        default=True,
        alias="TRACELOOP_TRACE_CONTENT",
        description=(
            "Capture prompts / completions / embeddings as span "
            "attributes. True (default) gives full visibility into what "
            "the review agents sent and received; set false to keep "
            "message bodies out of the traces (metadata only)."
        ),
    )
    telemetry_disable_batch: bool = Field(
        default=False,
        alias="TRACELOOP_DISABLE_BATCH",
        description=(
            "Send spans immediately instead of batching them. Useful in "
            "dev to see traces in real time; leave false in production."
        ),
    )
    telemetry_fastapi: bool = Field(
        default=True,
        description=(
            "Instrument the FastAPI app (one HTTP span per request) "
            "when telemetry is configured. Set false to disable the "
            "HTTP layer while keeping LLM trace export."
        ),
    )

    review_e2e_installation_id: str = Field(
        description="github installations id for e2e review test"
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
    def indexing_configured(self) -> bool:
        """True when the indexing pipeline can run end-to-end.

        Requires:

        - An OpenAI key (for the in-sandbox embedding function).
        - A configured sandbox provider (clone + chunking).
        - An S3 bucket (``INDEX_S3_BUCKET``) with full AWS credentials
          (``AWS_ACCESS_KEY_ID`` + ``AWS_SECRET_ACCESS_KEY`` +
          ``AWS_REGION`` + ``AWS_ENDPOINT_URL``) so
          :func:`app.services.indexing.steps.run_index.resolve_index_env`
          can forward them into the in-sandbox ingestion script. Missing
          any of those raises ``IndexingConfigError`` at step time.
        """
        return bool(
            self.openai_api_key
            and self.sandbox_configured
            and self.index_s3_bucket
            and self.aws_access_key_id
            and self.aws_secret_access_key
            and self.aws_region
            and self.aws_endpoint_url
        )

    @property
    def llm_configured(self) -> bool:
        """True when the review-agent LLM is fully configured.

        Requires a non-empty ``llm_model`` (``"provider:model"``
        string) and an API key, either the dedicated
        ``llm_api_key`` or a provider-native env var
        (``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` /
        ``GOOGLE_API_KEY`` / …). ``llm_base_url`` is not required
        for direct provider calls.
        """
        if not self.llm_model:
            return False
        if self.llm_api_key:
            return True
        return self._env_key_for(self.llm_model)

    def _env_key_for(self, model: str) -> bool:
        """True when a provider-native env var is set for ``model``.

        Lets ``llm_configured`` treat ``LLM_API_KEY=…`` and the
        provider's own env var (``OPENAI_API_KEY`` etc.) as
        equivalent, since :func:`langchain.chat_models.init_chat_model`
        does its own env-var resolution.
        """
        provider = model.split(":", 1)[0]
        env_key = _PROVIDER_ENV_KEY.get(provider, "")
        return bool(env_key) and bool(os.environ.get(env_key))

    @property
    def llm_config(self) -> LLMConfig:
        """The :class:`LLMConfig` value object for the review agent.

        Frozen, DBOS-serializable. A single value object replaces
        the four scattered fields (provider / base_url / api_key /
        model) that used to cross the webhook → workflow → step
        boundary.
        """
        return LLMConfig(
            model=self.llm_model,
            api_key=self.llm_api_key or None,
            base_url=self.llm_base_url or None,
            headers=dict(self.llm_default_headers),
            max_retries=self.llm_max_retries,
            rate_limit_rps=self.llm_rate_limit_rps,
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

    @property
    def telemetry_configured(self) -> bool:
        """True when OpenLLMetry has an OTLP endpoint or API key to export to.

        Both ``telemetry_api_key`` and ``telemetry_base_url`` default to
        empty so the module imports safely in tests and the SDK is never
        initialised (no auto-generated Traceloop-cloud key) unless the
        operator opts in.
        """
        return bool(self.telemetry_api_key or self.telemetry_base_url)


settings = Settings()
