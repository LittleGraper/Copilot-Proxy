from __future__ import annotations

from contextlib import suppress

from copilot_proxy import cli
from copilot_proxy.settings import Settings, get_settings


def fake_dynamic_model_registry(_: Settings) -> list[dict[str, str]]:
    return [
        {"name": "gpt-4", "upstream": "github_copilot/gpt-4"},
        {"name": "gpt-5.5", "upstream": "github_copilot/gpt-5.5"},
        {"name": "codex", "upstream": "github_copilot/codex", "mode": "responses"},
        {"name": "embed", "upstream": "github_copilot/embed", "mode": "embedding"},
    ]


def write_config(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LOCAL_API_KEY=sk-local-test",
                "COPILOT_PROXY_HOST=127.0.0.1",
                "COPILOT_PROXY_PORT=4321",
                "COPILOT_PROXY_MODELS_CONFIG=models.toml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models.toml").write_text(
        """
[models]
default = "gpt-4"

[[models.aliases]]
name = "gpt-4"
upstream = "github_copilot/gpt-4"

[[models.aliases]]
name = "gpt-5.5"
upstream = "github_copilot/gpt-5.5"

[[models.aliases]]
name = "codex"
upstream = "github_copilot/codex"
mode = "responses"

[[models.aliases]]
name = "embed"
upstream = "github_copilot/embed"
mode = "embedding"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def prepare_config(monkeypatch, tmp_path) -> None:
    write_config(tmp_path)
    monkeypatch.setenv("CPX_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CPX_DISABLE_DYNAMIC_MODELS", "1")
    monkeypatch.setenv("LOCAL_API_KEY", "sk-local-test")
    monkeypatch.setenv("COPILOT_PROXY_HOST", "127.0.0.1")
    monkeypatch.setenv("COPILOT_PROXY_PORT", "4321")
    monkeypatch.setenv("COPILOT_PROXY_MODELS_CONFIG", "models.toml")
    monkeypatch.setattr(Settings, "dynamic_model_registry", fake_dynamic_model_registry)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()


def test_cpx_without_args_prints_help(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    cli.main([])

    output = capsys.readouterr().out
    assert "Local GitHub Copilot proxy" in output
    assert "start" in output
    assert "models" in output


def test_cpx_version_flag_and_command(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "package_version", lambda: "1.2.3")

    cli.main(["-v"])
    cli.main(["version"])

    assert capsys.readouterr().out.count("1.2.3") == 2


def test_cpx_config_is_not_registered(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    try:
        cli.main(["config"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("removed subcommand should not be registered")

    output = capsys.readouterr()
    assert "invalid choice: 'config'" in output.err


def test_cpx_login_runs_device_flow(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    calls: list[bool] = []

    monkeypatch.setattr(cli, "ensure_copilot_authenticated", lambda: calls.append(True))

    cli.main(["login"])

    assert calls == [True]


def test_cpx_whoami_prints_current_github_account(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    access_token = tmp_path / "access-token"
    access_token.write_text("saved-token", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class FakeAuthenticator:
        access_token_file = str(access_token)
        api_key_file = str(tmp_path / "api-key.json")

        def get_access_token(self) -> str:
            return "saved-token"

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"login": "octocat", "id": 12345}

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(cli, "github_copilot_authenticator", lambda: FakeAuthenticator())
    monkeypatch.setattr(cli.httpx, "get", fake_get)

    cli.main(["whoami"])

    output = capsys.readouterr().out
    assert "GitHub Login:       octocat" in output
    assert "GitHub User ID:     12345" in output
    assert calls == [
        {
            "url": "https://api.github.com/user",
            "headers": {
                "accept": "application/vnd.github+json",
                "authorization": "token saved-token",
                "user-agent": "GithubCopilot/1.155.0",
            },
            "timeout": 30,
        }
    ]


def test_cpx_whoami_requires_login_when_access_token_is_missing(
    monkeypatch, tmp_path, capsys
) -> None:
    prepare_config(monkeypatch, tmp_path)

    class FakeAuthenticator:
        access_token_file = str(tmp_path / "missing-access-token")
        api_key_file = str(tmp_path / "api-key.json")

    monkeypatch.setattr(cli, "github_copilot_authenticator", lambda: FakeAuthenticator())

    try:
        cli.main(["whoami"])
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("missing credentials should require cpx login")

    assert "Run `cpx login` first" in capsys.readouterr().out


def test_cpx_api_prints_openai_and_anthropic_settings(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    cli.main(["api"])

    output = capsys.readouterr().out
    assert "OpenAI Compatible:" in output
    assert "API Key:  sk-local-test" in output
    assert "Base URL: http://127.0.0.1:4321/v1" in output
    assert "Anthropic Compatible:" in output
    assert "Base URL: http://127.0.0.1:4321" in output


def test_cpx_logout_removes_saved_copilot_credentials(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    access_token = tmp_path / "access-token"
    api_key = tmp_path / "api-key.json"
    access_token.write_text("token", encoding="utf-8")
    api_key.write_text('{"token":"api-key"}', encoding="utf-8")

    class FakeAuthenticator:
        access_token_file = str(access_token)
        api_key_file = str(api_key)

    monkeypatch.setattr(cli, "github_copilot_authenticator", lambda: FakeAuthenticator())

    cli.main(["logout"])

    assert not access_token.exists()
    assert not api_key.exists()
    assert "GitHub Copilot OAuth credentials removed." in capsys.readouterr().out


def test_require_copilot_login_prompts_for_login_when_credentials_are_missing(
    monkeypatch, tmp_path, capsys
) -> None:
    prepare_config(monkeypatch, tmp_path)

    class FakeAuthenticator:
        access_token_file = str(tmp_path / "missing-access-token")
        api_key_file = str(tmp_path / "missing-api-key.json")

        def get_api_key(self) -> str:
            raise AssertionError("device flow should not start from require_copilot_login")

    monkeypatch.setattr(cli, "github_copilot_authenticator", lambda: FakeAuthenticator())

    try:
        cli.require_copilot_login()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("missing credentials should require cpx login")

    assert "Run `cpx login` first" in capsys.readouterr().out


def test_cpx_update_runs_uv_tool_install(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> None:
        calls.append(command)
        assert check is True

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli.main(["update"])

    assert calls == [["uv", "tool", "install", "--force", cli.GITHUB_INSTALL_URL]]
    assert "Updating cpx from GitHub" in capsys.readouterr().out


class FakeProcess:
    pid = 98765

    def poll(self) -> None:
        return None


def test_cpx_start_prints_urls_key_and_starts_background_server(
    monkeypatch, tmp_path, capsys
) -> None:
    prepare_config(monkeypatch, tmp_path)
    auth_calls: list[bool] = []
    pid_writes: list[tuple[str, int]] = []

    monkeypatch.setattr(cli, "require_copilot_login", lambda: auth_calls.append(True))
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(cli, "start_server_background", lambda settings, config_dir: FakeProcess())
    monkeypatch.setattr(cli, "wait_for_port", lambda host, port, process: True)
    monkeypatch.setattr(
        cli,
        "write_pid_file",
        lambda pid_file, pid: pid_writes.append((str(pid_file), pid)),
    )

    cli.main(["start"])

    output = capsys.readouterr().out
    assert auth_calls == [True]
    assert "OpenAI Base URL:    http://127.0.0.1:4321/v1" in output
    assert "Anthropic Base URL: http://127.0.0.1:4321" in output
    assert "API Key:            sk-local-test" in output
    assert "Default model:      gpt-4" in output
    assert "Proxy is running in the background (pid 98765)." in output
    assert f"Log file:           {tmp_path / 'cpx.log'}" in output
    assert pid_writes == [(str(tmp_path / ".copilot-proxy.pid"), 98765)]


def test_cpx_start_foreground_runs_uvicorn_in_current_process(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    uvicorn_calls: list[dict[str, object]] = []
    pid_writes: list[tuple[str, int]] = []
    cleanup_calls: list[str] = []

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(
        cli,
        "write_pid_file",
        lambda pid_file, pid: pid_writes.append((str(pid_file), pid)),
    )
    monkeypatch.setattr(
        cli, "cleanup_pid_file", lambda pid_file: cleanup_calls.append(str(pid_file))
    )

    def fake_run(app: str, host: str, port: int, log_level: str) -> None:
        uvicorn_calls.append({"app": app, "host": host, "port": port, "log_level": log_level})

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main(["start", "--foreground"])

    assert pid_writes == [(str(tmp_path / ".copilot-proxy.pid"), cli.os.getpid())]
    assert cleanup_calls == [str(tmp_path / ".copilot-proxy.pid")]
    assert uvicorn_calls == [
        {
            "app": "copilot_proxy.main:app",
            "host": "127.0.0.1",
            "port": 4321,
            "log_level": "info",
        }
    ]


def test_cpx_start_can_skip_auth_check(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli,
        "require_copilot_login",
        lambda: (_ for _ in ()).throw(AssertionError("auth should be skipped")),
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda *_, **__: None)
    monkeypatch.setattr(cli, "stop_existing_instance", lambda pid_file: None)
    monkeypatch.setattr(cli, "ensure_port_available", lambda host, port: None)
    monkeypatch.setattr(cli, "start_server_background", lambda settings, config_dir: FakeProcess())
    monkeypatch.setattr(cli, "wait_for_port", lambda host, port, process: True)
    monkeypatch.setattr(cli, "write_pid_file", lambda pid_file, pid: None)

    cli.main(["start", "--skip-auth-check"])


def test_cpx_stop_uses_pid_file(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    pid_file = tmp_path / ".copilot-proxy.pid"
    pid_file.write_text("12345", encoding="utf-8")
    stopped: list[str] = []

    monkeypatch.setattr(cli, "stop_existing_instance", lambda path: stopped.append(str(path)))

    cli.main(["stop"])
    cli.main(["quit"])

    assert stopped == [str(pid_file), str(pid_file)]


def test_cpx_test_checks_configured_models(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    tested: list[str] = []

    class FakeLiteLLM:
        registered: list[dict[str, dict[str, str]]] = []

        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            FakeLiteLLM.registered.append(model_cost)

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            tested.append(f"chat:{model}")
            return object()

        @staticmethod
        def responses(model: str, input: str, max_output_tokens: int, timeout: float) -> object:
            tested.append(f"responses:{model}")
            return object()

        @staticmethod
        def embedding(model: str, input: list[str], timeout: float) -> object:
            tested.append(f"embedding:{model}")
            return object()

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    cli.main(["test"])

    assert FakeLiteLLM.registered == [
        {
            "github_copilot/codex": {
                "litellm_provider": "github_copilot",
                "mode": "responses",
            },
            "github_copilot/embed": {
                "litellm_provider": "github_copilot",
                "mode": "embedding",
            },
        }
    ]
    assert tested == [
        "chat:github_copilot/gpt-4",
        "chat:github_copilot/gpt-5.5",
        "responses:github_copilot/codex",
        "embedding:github_copilot/embed",
    ]
    output = capsys.readouterr().out
    assert "TEST " not in output
    assert "OK   gpt-4 -> github_copilot/gpt-4" in output
    assert "All configured models are reachable." in output


def test_cpx_test_can_filter_models(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    tested: list[str] = []

    class FakeLiteLLM:
        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            return None

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            tested.append(model)
            return object()

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    cli.main(["test", "--model", "gpt-5.5"])

    assert tested == ["github_copilot/gpt-5.5"]


def test_cpx_test_exits_nonzero_on_model_failure(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    class FakeLiteLLM:
        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            return None

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            if model.endswith("gpt-5.5"):
                raise RuntimeError("boom")
            return object()

        @staticmethod
        def responses(model: str, input: str, max_output_tokens: int, timeout: float) -> object:
            return object()

        @staticmethod
        def embedding(model: str, input: list[str], timeout: float) -> object:
            return object()

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    try:
        cli.main(["test"])
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("cpx test should exit non-zero when a model fails")

    assert "FAIL gpt-5.5 -> github_copilot/gpt-5.5: boom" in capsys.readouterr().out


def test_cpx_test_retries_transient_model_failure(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    attempts: dict[str, int] = {}

    class FakeLiteLLM:
        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            return None

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            attempts[model] = attempts.get(model, 0) + 1
            if model.endswith("gpt-5.5") and attempts[model] == 1:
                raise RuntimeError("temporary upstream failure")
            return object()

        @staticmethod
        def responses(model: str, input: str, max_output_tokens: int, timeout: float) -> object:
            return object()

        @staticmethod
        def embedding(model: str, input: list[str], timeout: float) -> object:
            return object()

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    cli.main(["test"])

    assert attempts["github_copilot/gpt-5.5"] == 2
    assert "FAIL" not in capsys.readouterr().out


def test_cpx_test_colorizes_ok_and_fail(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    class FakeLiteLLM:
        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            return None

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            if model.endswith("gpt-5.5"):
                raise RuntimeError("boom")
            return object()

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setattr(cli, "supports_color", lambda: True)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    with suppress(SystemExit):
        cli.main(["test"])

    output = capsys.readouterr().out
    assert "\033[32mOK\033[0m" in output
    assert "\033[31mFAIL\033[0m" in output


def test_cpx_test_handles_keyboard_interrupt_cleanly(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)

    class FakeLiteLLM:
        @staticmethod
        def register_model(model_cost: dict[str, dict[str, str]]) -> None:
            return None

        @staticmethod
        def completion(
            model: str,
            messages: list[dict[str, str]],
            max_tokens: int,
            timeout: float,
        ) -> object:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "require_copilot_login", lambda: None)
    monkeypatch.setitem(cli.sys.modules, "litellm", FakeLiteLLM)

    try:
        cli.main(["test"])
    except SystemExit as exc:
        assert exc.code == 130
    else:
        raise AssertionError("KeyboardInterrupt should exit with code 130")

    assert "Cancelled." in capsys.readouterr().out


def test_cpx_model_non_interactive_prints_choices(monkeypatch, tmp_path, capsys) -> None:
    prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    cli.main(["models"])

    output = capsys.readouterr().out
    assert "* gpt-4 -> github_copilot/gpt-4" in output
    assert "  gpt-5.5 -> github_copilot/gpt-5.5" in output


def test_cpx_model_does_not_accept_list_subcommand(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)

    try:
        cli.main(["models", "list"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("models list should not be accepted")


def test_cpx_model_interactive_uses_arrow_enter(monkeypatch, tmp_path) -> None:
    prepare_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "supports_color", lambda: False)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(cli, "read_key", lambda: next(keys))
    monkeypatch.setattr(cli, "clear_screen", lambda: None)

    cli.main(["model"])

    assert 'default = "gpt-5.5"' in (tmp_path / "models.toml").read_text(encoding="utf-8")


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
