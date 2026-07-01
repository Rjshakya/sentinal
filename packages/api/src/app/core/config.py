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

    @property
    def workos_configured(self) -> bool:
        return bool(
            self.workos_api_key
            and self.workos_client_id
            and self.workos_cookie_password
        )

    @property
    def cookie_secure(self) -> bool:
        return self.frontend_url.startswith("https://")


print(f"DEBUG: Looking for .env at: {BASE_DIR / '.env'}")
print(f"DEBUG: File exists: {(BASE_DIR / '.env').exists()}")

settings = Settings()
