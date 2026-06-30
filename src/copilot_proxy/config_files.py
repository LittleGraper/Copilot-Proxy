from __future__ import annotations

import os
import secrets
import sys
from importlib.resources import files
from pathlib import Path

DEFAULT_ENV_TEMPLATE = """LOCAL_API_KEY={api_key}
COPILOT_PROXY_HOST=127.0.0.1
COPILOT_PROXY_PORT=4000
COPILOT_PROXY_MODELS_CONFIG=models.toml
COPILOT_PROXY_LITELLM_CONFIG=litellm.yaml
COPILOT_PROXY_LOG_LEVEL=info

# Optional: choose where LiteLLM stores GitHub Copilot OAuth tokens.
# GITHUB_COPILOT_TOKEN_DIR=~/.config/litellm/github_copilot
"""

DEFAULT_MODELS_TOML = """[models]
default = "gpt-4"

[[models.aliases]]
name = "gpt-4"
upstream = "github_copilot/gpt-4"
"""


def active_config_dir() -> Path:
    configured = os.getenv("CPX_CONFIG_DIR") or os.getenv("COPILOT_PROXY_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    current = Path.cwd()
    if (current / ".env").exists() or (current / "models.toml").exists():
        return current

    return user_config_dir()


def user_config_dir() -> Path:
    if sys.platform == "win32":
        root = os.getenv("APPDATA")
        if root:
            return Path(root) / "cpx"
    root = os.getenv("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "cpx"
    return Path.home() / ".config" / "cpx"


def ensure_config_files() -> Path:
    config_dir = active_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    env_file = config_dir / ".env"
    if not env_file.exists():
        api_key = f"sk-local-{secrets.token_urlsafe(24)}"
        env_file.write_text(DEFAULT_ENV_TEMPLATE.format(api_key=api_key), encoding="utf-8")

    models_file = config_dir / "models.toml"
    if not models_file.exists():
        models_file.write_text(default_models_toml(), encoding="utf-8")

    return config_dir


def env_file_for_settings() -> Path:
    return active_config_dir() / ".env"


def default_models_toml() -> str:
    source_tree_example = Path(__file__).resolve().parents[2] / "models.toml.example"
    if source_tree_example.exists():
        return source_tree_example.read_text(encoding="utf-8")
    try:
        return files("copilot_proxy").joinpath("models.toml.example").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        return DEFAULT_MODELS_TOML


def resolve_config_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return active_config_dir() / path
