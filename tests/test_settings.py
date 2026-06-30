from __future__ import annotations

from copilot_proxy.settings import Settings


def test_models_toml_drives_aliases_default_and_upstream(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("COPILOT_PROXY_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("COPILOT_PROXY_MODEL_ALIASES", raising=False)

    config = tmp_path / "models.toml"
    config.write_text(
        """
[models]
default = "gpt-4o"

[[models.aliases]]
name = "gpt-4o"
upstream = "github_copilot/gpt-4o"

[[models.aliases]]
name = "custom-alias"
upstream = "github_copilot/gpt-5.5"
mode = "chat"
""".strip(),
        encoding="utf-8",
    )

    settings = Settings(
        LOCAL_API_KEY="sk-test",
        COPILOT_PROXY_MODELS_CONFIG=config,
        COPILOT_PROXY_DEFAULT_MODEL="",
        COPILOT_PROXY_MODEL_ALIASES="",
    )

    assert settings.aliases == ["gpt-4o", "custom-alias"]
    assert settings.default_model == "gpt-4o"
    assert settings.upstream_model("custom-alias") == "github_copilot/gpt-5.5"
    assert settings.model_registry()[1] == {
        "name": "custom-alias",
        "upstream": "github_copilot/gpt-5.5",
        "mode": "chat",
    }


def test_env_alias_override_takes_precedence(tmp_path) -> None:
    config = tmp_path / "models.toml"
    config.write_text(
        """
[models]
default = "gpt-4o"

[[models.aliases]]
name = "gpt-4o"
upstream = "github_copilot/gpt-4o"
""".strip(),
        encoding="utf-8",
    )

    settings = Settings(
        LOCAL_API_KEY="sk-test",
        COPILOT_PROXY_MODELS_CONFIG=config,
        COPILOT_PROXY_DEFAULT_MODEL="gpt-5.5",
        COPILOT_PROXY_MODEL_ALIASES="gpt-5.5,gpt-4.1",
    )

    assert settings.aliases == ["gpt-5.5", "gpt-4.1"]
    assert settings.default_model == "gpt-5.5"
    assert settings.upstream_model("gpt-4.1") == "github_copilot/gpt-4.1"


def test_models_toml_example_is_used_as_default_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    example = tmp_path / "models.toml.example"
    example.write_text(
        """
[models]
default = "example-model"

[[models.aliases]]
name = "example-model"
upstream = "github_copilot/example-model"
""".strip(),
        encoding="utf-8",
    )

    settings = Settings(
        LOCAL_API_KEY="sk-test",
        COPILOT_PROXY_MODELS_CONFIG="models.toml",
        COPILOT_PROXY_DEFAULT_MODEL="",
        COPILOT_PROXY_MODEL_ALIASES="",
    )

    assert settings.aliases == ["example-model"]
    assert settings.default_model == "example-model"
    assert settings.upstream_model("example-model") == "github_copilot/example-model"
