from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    local_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LOCAL_API_KEY", "COPILOT_PROXY_LOCAL_API_KEY"),
    )
    host: str = Field(default="127.0.0.1", validation_alias="COPILOT_PROXY_HOST")
    port: int = Field(default=4000, validation_alias="COPILOT_PROXY_PORT")
    default_model: str = Field(default="gpt-4", validation_alias="COPILOT_PROXY_DEFAULT_MODEL")
    model_aliases: str = Field(
        default="gpt-4,gpt-4o,gpt-5.1-codex,text-embedding-3-small",
        validation_alias="COPILOT_PROXY_MODEL_ALIASES",
    )
    litellm_config: Path = Field(
        default=Path("litellm.yaml"),
        validation_alias="COPILOT_PROXY_LITELLM_CONFIG",
    )
    log_level: str = Field(default="info", validation_alias="COPILOT_PROXY_LOG_LEVEL")
    copilot_token_dir: str | None = Field(default=None, validation_alias="GITHUB_COPILOT_TOKEN_DIR")

    @property
    def aliases(self) -> list[str]:
        return [alias.strip() for alias in self.model_aliases.split(",") if alias.strip()]

    def upstream_model(self, model: str | None) -> str:
        selected = model or self.default_model
        if "/" in selected:
            return selected
        return f"github_copilot/{selected}"

    def validate_runtime(self) -> None:
        if not self.local_api_key:
            msg = "LOCAL_API_KEY is required. Copy .env.example to .env and set a local key."
            raise RuntimeError(msg)


@lru_cache
def get_settings() -> Settings:
    return Settings()
