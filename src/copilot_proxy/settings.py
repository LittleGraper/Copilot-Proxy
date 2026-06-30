import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

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
    default_model_override: str | None = Field(
        default=None,
        validation_alias="COPILOT_PROXY_DEFAULT_MODEL",
    )
    model_aliases_override: str | None = Field(
        default=None,
        validation_alias="COPILOT_PROXY_MODEL_ALIASES",
    )
    models_config: Path = Field(
        default=Path("models.toml"),
        validation_alias="COPILOT_PROXY_MODELS_CONFIG",
    )
    litellm_config: Path = Field(
        default=Path("litellm.yaml"),
        validation_alias="COPILOT_PROXY_LITELLM_CONFIG",
    )
    log_level: str = Field(default="info", validation_alias="COPILOT_PROXY_LOG_LEVEL")
    copilot_token_dir: str | None = Field(default=None, validation_alias="GITHUB_COPILOT_TOKEN_DIR")

    @property
    def aliases(self) -> list[str]:
        if self.model_aliases_override:
            return [
                alias.strip() for alias in self.model_aliases_override.split(",") if alias.strip()
            ]
        return [model["name"] for model in self.model_registry()]

    @property
    def default_model(self) -> str:
        if self.default_model_override:
            return self.default_model_override
        data = self._models_data()
        default = data.get("models", {}).get("default")
        if isinstance(default, str) and default:
            return default
        aliases = self.aliases
        return aliases[0] if aliases else "gpt-4"

    def upstream_model(self, model: str | None) -> str:
        selected = model or self.default_model
        if "/" in selected:
            return selected
        for entry in self.model_registry():
            if entry["name"] == selected:
                return entry["upstream"]
        return f"github_copilot/{selected}"

    def model_registry(self) -> list[dict[str, str]]:
        if self.model_aliases_override:
            return [
                {"name": alias, "upstream": self._default_upstream(alias)} for alias in self.aliases
            ]

        aliases = self._models_data().get("models", {}).get("aliases", [])
        registry: list[dict[str, str]] = []
        for entry in aliases:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            upstream = entry.get("upstream")
            if not isinstance(upstream, str) or not upstream:
                upstream = self._default_upstream(name)
            normalized = {"name": name, "upstream": upstream}
            mode = entry.get("mode")
            if isinstance(mode, str) and mode:
                normalized["mode"] = mode
            registry.append(normalized)
        return registry

    def validate_runtime(self) -> None:
        if not self.local_api_key:
            msg = "LOCAL_API_KEY is required. Copy .env.example to .env and set a local key."
            raise RuntimeError(msg)
        if not self.aliases:
            msg = f"No models configured. Add aliases to {self.models_config}."
            raise RuntimeError(msg)

    def _models_data(self) -> dict[str, Any]:
        config_path = self.models_config
        if not config_path.exists() and config_path.name == "models.toml":
            example_path = config_path.with_name("models.toml.example")
            if example_path.exists():
                config_path = example_path
        if not config_path.exists():
            return {"models": {"default": "gpt-4", "aliases": []}}
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)

    def _default_upstream(self, model: str) -> str:
        if "/" in model:
            return model
        return f"github_copilot/{model}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
