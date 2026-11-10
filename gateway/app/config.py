from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+asyncpg://maskgate:maskgate@localhost:5432/maskgate",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    admin_token: str = Field(default="change-me", alias="ADMIN_TOKEN")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")
    log_raw_payloads: bool = Field(default=False, alias="LOG_RAW_PAYLOADS")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    mock_provider_url: str = Field(default="http://localhost:9000", alias="MOCK_PROVIDER_URL")

    request_timeout_seconds: int = Field(default=60, alias="REQUEST_TIMEOUT_SECONDS")
    provider_attempt_timeout_seconds: int = Field(
        default=20, alias="PROVIDER_ATTEMPT_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(default=2, alias="MAX_RETRIES")
    max_prompt_chars: int = Field(default=200000, alias="MAX_PROMPT_CHARS")

    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    models_config_path: str = Field(default="models.yaml", alias="MODELS_CONFIG_PATH")

    def resolve_models_path(self) -> Path:
        candidate = Path(self.models_config_path)
        if candidate.is_file():
            return candidate
        # Try relative to parent directories
        for parent in [Path.cwd(), Path(__file__).resolve().parent.parent]:
            p = parent / self.models_config_path
            if p.is_file():
                return p
        return candidate


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
