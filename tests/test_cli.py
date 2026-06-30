from __future__ import annotations

from copilot_proxy import cli
from copilot_proxy.settings import get_settings


def test_cli_prints_urls_key_and_starts_server(monkeypatch, capsys) -> None:
    auth_calls: list[bool] = []
    uvicorn_calls: list[dict[str, object]] = []

    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    monkeypatch.setenv("COPILOT_PROXY_HOST", "127.0.0.1")
    monkeypatch.setenv("COPILOT_PROXY_PORT", "4321")
    monkeypatch.setenv("COPILOT_PROXY_DEFAULT_MODEL", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: auth_calls.append(True))

    def fake_run(app: str, host: str, port: int, log_level: str) -> None:
        uvicorn_calls.append({"app": app, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main([])

    output = capsys.readouterr().out

    assert auth_calls == [True]
    assert "OpenAI Base URL:    http://127.0.0.1:4321/v1" in output
    assert "Anthropic Base URL: http://127.0.0.1:4321" in output
    assert "API Key:            sk-local-test" in output
    assert uvicorn_calls == [
        {
            "app": "copilot_proxy.main:app",
            "host": "127.0.0.1",
            "port": 4321,
            "log_level": "info",
        }
    ]


def test_cli_can_skip_auth_check(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    get_settings.cache_clear()

    monkeypatch.setattr(
        cli,
        "ensure_copilot_authenticated",
        lambda: (_ for _ in ()).throw(AssertionError("auth should be skipped")),
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **__: None)

    cli.main(["--skip-auth-check"])
