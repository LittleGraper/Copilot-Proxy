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
    monkeypatch.setenv("COPILOT_PROXY_MODEL_ALIASES", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: auth_calls.append(True))
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(cli, "write_pid_file", lambda pid_file: None)
    monkeypatch.setattr(cli, "cleanup_pid_file", lambda pid_file: None)

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
    monkeypatch.setenv("COPILOT_PROXY_MODEL_ALIASES", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(
        cli,
        "ensure_copilot_authenticated",
        lambda: (_ for _ in ()).throw(AssertionError("auth should be skipped")),
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **__: None)
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(cli, "write_pid_file", lambda pid_file: None)
    monkeypatch.setattr(cli, "cleanup_pid_file", lambda pid_file: None)

    cli.main(["--skip-auth-check"])


def test_cli_stops_previous_instance_before_starting(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    monkeypatch.setenv("COPILOT_PROXY_PORT", "4000")
    monkeypatch.setenv("COPILOT_PROXY_MODEL_ALIASES", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: None)

    calls: list[str] = []
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: calls.append("stop"))
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: calls.append("port"))
    monkeypatch.setattr(cli, "write_pid_file", lambda pid_file: calls.append("write"))
    monkeypatch.setattr(cli, "cleanup_pid_file", lambda pid_file: calls.append("cleanup"))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **__: calls.append("run"))

    cli.main([])

    assert calls == ["stop", "port", "write", "run", "cleanup"]


def test_cli_can_skip_stopping_previous_instance(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    monkeypatch.setenv("COPILOT_PROXY_MODEL_ALIASES", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: None)
    monkeypatch.setattr(
        cli,
        "stop_existing_instance",
        lambda pid_file: (_ for _ in ()).throw(AssertionError("old instance should not stop")),
    )
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(cli, "write_pid_file", lambda pid_file: None)
    monkeypatch.setattr(cli, "cleanup_pid_file", lambda pid_file: None)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **__: None)

    cli.main(["--no-restart-existing"])


def test_stop_existing_instance_terminates_recorded_process(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / ".copilot-proxy.pid"
    pid_file.write_text("12345", encoding="utf-8")

    states = iter([True, False])
    terminated: list[int] = []

    monkeypatch.setattr(cli, "is_process_running", lambda pid: next(states))
    monkeypatch.setattr(cli, "terminate_process", lambda pid: terminated.append(pid))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    cli.stop_existing_instance(pid_file)

    assert terminated == [12345]
    assert not pid_file.exists()


def test_ensure_port_available_fails_for_unmanaged_process(monkeypatch) -> None:
    monkeypatch.setattr(cli, "is_port_available", lambda host, port: False)

    try:
        cli.ensure_port_available("127.0.0.1", 4000)
    except RuntimeError as exc:
        assert "no restartable Copilot Proxy instance was found" in str(exc)
    else:
        raise AssertionError("occupied unmanaged port should fail")


def test_cli_writes_and_cleans_pid_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    monkeypatch.setenv("COPILOT_PROXY_MODEL_ALIASES", "gpt-test")
    get_settings.cache_clear()

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: None)
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)

    events: list[str] = []

    def fake_run(*_: object, **__: object) -> None:
        events.append("run")
        assert (tmp_path / ".copilot-proxy.pid").exists()

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.chdir(tmp_path)

    cli.main([])

    assert events == ["run"]
    assert not (tmp_path / ".copilot-proxy.pid").exists()
