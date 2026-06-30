from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import uvicorn

from .config_files import active_config_dir, ensure_config_files, resolve_config_path
from .github_copilot_patch import apply_github_copilot_oauth_patch
from .litellm_registry import register_litellm_model_metadata
from .model_store import write_default_model
from .settings import get_settings

GITHUB_INSTALL_URL = "git+https://github.com/LittleGraper/Copilot-Proxy.git"


def main(argv: list[str] | None = None) -> None:
    ensure_config_files()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.version:
            print(package_version())
            return

        command = args.command or "help"
        if command == "help":
            parser.print_help()
        elif command == "version":
            print(package_version())
        elif command == "start":
            start(args)
        elif command in {"stop", "quit"}:
            stop()
        elif command == "login":
            login()
        elif command == "logout":
            logout()
        elif command in {"model", "models"}:
            handle_models(args)
        elif command == "update":
            update(args)
        elif command == "test":
            test_models(args)
    except KeyboardInterrupt as exc:
        print("\nCancelled.", flush=True)
        raise SystemExit(130) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local GitHub Copilot proxy.")
    parser.add_argument("-v", "--version", action="store_true", help="Show cpx version and exit.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("help", help="Show this help message.")
    subparsers.add_parser("version", help="Show cpx version.")
    subparsers.add_parser("login", help="Authenticate GitHub Copilot with device flow.")
    subparsers.add_parser("logout", help="Remove saved GitHub Copilot OAuth credentials.")
    subparsers.add_parser("stop", help="Stop the running proxy instance.")
    subparsers.add_parser("quit", help="Stop the running proxy instance.")
    subparsers.add_parser("update", help="Update cpx from GitHub using uv tool install.")

    test_parser = subparsers.add_parser("test", help="Test connectivity for configured models.")
    test_parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Only test a specific configured model. Can be passed multiple times.",
    )
    test_parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Run model tests without checking GitHub Copilot OAuth first.",
    )
    test_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-model test timeout in seconds. Default: 60.",
    )

    start_parser = subparsers.add_parser("start", help="Start the local proxy.")
    start_parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Start the proxy without checking GitHub Copilot OAuth first.",
    )
    start_parser.add_argument(
        "--no-restart-existing",
        action="store_true",
        help="Do not stop a previous proxy instance recorded in .copilot-proxy.pid.",
    )
    start_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run uvicorn in the current terminal instead of starting a background process.",
    )

    for name in ("model", "models"):
        subparsers.add_parser(name, help="Interactively change the default model.")

    return parser


def start(args: argparse.Namespace) -> None:
    settings = get_settings()
    settings.validate_runtime()
    config_dir = active_config_dir()
    pid_file = config_dir / ".copilot-proxy.pid"
    if not args.no_restart_existing:
        stop_existing_instance(pid_file)
    ensure_port_available(settings.host, settings.port)

    if not args.skip_auth_check:
        require_copilot_login()

    print_startup_info(settings)
    if args.foreground:
        run_server_foreground(settings, pid_file)
        return

    process = start_server_background(settings, config_dir)
    write_pid_file(pid_file, process.pid)
    log_file = config_dir / "cpx.log"
    if wait_for_port(settings.host, settings.port, process):
        print(f"Proxy is running in the background (pid {process.pid}).", flush=True)
    else:
        print(
            f"Proxy was started in the background (pid {process.pid}), "
            "but the port did not become ready yet.",
            flush=True,
        )
    print(f"Log file:           {log_file}", flush=True)


def update(args: argparse.Namespace) -> None:
    command = ["uv", "tool", "install", "--force", GITHUB_INSTALL_URL]
    print("Updating cpx from GitHub...", flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def login() -> None:
    ensure_copilot_authenticated()


def logout() -> None:
    authenticator = github_copilot_authenticator()
    removed = 0
    for path in (authenticator.access_token_file, authenticator.api_key_file):
        token_file = Path(path)
        try:
            token_file.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    if removed:
        print("GitHub Copilot OAuth credentials removed.", flush=True)
    else:
        print("No saved GitHub Copilot OAuth credentials found.", flush=True)


def test_models(args: argparse.Namespace) -> None:
    settings = get_settings()
    settings.validate_runtime()
    selected = set(args.models or [])
    registry = [
        entry for entry in settings.model_registry() if not selected or entry["name"] in selected
    ]
    missing = selected - {entry["name"] for entry in registry}
    if missing:
        msg = f"Unknown configured model(s): {', '.join(sorted(missing))}"
        raise RuntimeError(msg)
    if not registry:
        raise RuntimeError("No models configured.")

    if not args.skip_auth_check:
        require_copilot_login()

    import litellm

    register_litellm_model_metadata(litellm, registry)

    failures = 0
    print("Testing configured models...", flush=True)
    for entry in registry:
        try:
            test_model_entry_with_retry(litellm, entry, timeout=args.timeout)
            print(f"{green('OK')}   {entry['name']} -> {entry['upstream']}", flush=True)
        except Exception as exc:
            failures += 1
            print(
                f"{red('FAIL')} {entry['name']} -> {entry['upstream']}: {short_error(exc)}",
                flush=True,
            )
    if failures:
        raise SystemExit(1)
    print("All configured models are reachable.", flush=True)


def test_model_entry_with_retry(litellm, entry: dict[str, str], *, timeout: float) -> None:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            test_model_entry(litellm, entry, timeout=timeout)
            return
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1)
    if last_error is not None:
        raise last_error


def test_model_entry(litellm, entry: dict[str, str], *, timeout: float) -> None:
    mode = entry.get("mode", "chat")
    if mode == "responses":
        litellm.responses(
            model=entry["upstream"],
            input="Reply with exactly: OK",
            max_output_tokens=16,
            timeout=timeout,
        )
        return
    if mode == "embedding":
        litellm.embedding(model=entry["upstream"], input=["connectivity test"], timeout=timeout)
        return
    litellm.completion(
        model=entry["upstream"],
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=8,
        timeout=timeout,
    )


def short_error(exc: Exception) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    prefixes = [
        "litellm.BadRequestError: ",
        "litellm.AuthenticationError: ",
        "litellm.APIConnectionError: ",
    ]
    for prefix in prefixes:
        if message.startswith(prefix):
            return message.removeprefix(prefix)
    return message


def stop() -> None:
    pid_file = active_config_dir() / ".copilot-proxy.pid"
    pid = read_pid_file(pid_file)
    if pid is None:
        print("No running Copilot Proxy instance was recorded.")
        return
    stop_existing_instance(pid_file)


def run_server_foreground(settings, pid_file: Path) -> None:
    write_pid_file(pid_file, os.getpid())
    try:
        uvicorn.run(
            "copilot_proxy.main:app",
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
    finally:
        cleanup_pid_file(pid_file)


def start_server_background(settings, config_dir: Path) -> subprocess.Popen:
    log_file = config_dir / "cpx.log"
    env = os.environ.copy()
    env["CPX_CONFIG_DIR"] = str(config_dir)
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "copilot_proxy.main:app",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--log-level",
        settings.log_level,
    ]
    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        start_new_session = True
    with log_file.open("ab") as log_handle:
        return subprocess.Popen(
            command,
            cwd=config_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )


def wait_for_port(host: str, port: int, process: subprocess.Popen, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if is_port_open(host, port):
            return True
        time.sleep(0.1)
    return False


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def handle_models(args: argparse.Namespace) -> None:
    select_model_interactively()


def set_default_model(name: str) -> None:
    settings = get_settings()
    models_path = resolve_config_path(settings.models_config)
    registry = settings.model_registry()
    names = {entry["name"] for entry in registry}
    if name not in names:
        msg = f"Unknown model '{name}'. Run `cpx models` to see configured models."
        raise RuntimeError(msg)
    write_default_model(models_path, name)
    get_settings.cache_clear()
    print(f"Default model set to {green(name)}.")


def select_model_interactively() -> None:
    settings = get_settings()
    registry = settings.model_registry()
    if not registry:
        raise RuntimeError("No models configured.")

    selected = next(
        (index for index, entry in enumerate(registry) if entry["name"] == settings.default_model),
        0,
    )
    if not sys.stdin.isatty():
        print_model_choices(registry, settings.default_model)
        return

    while True:
        clear_screen()
        print("Select default model with Up/Down and Enter. Press q to cancel.\n")
        for index, entry in enumerate(registry):
            pointer = ">" if index == selected else " "
            is_default = entry["name"] == settings.default_model
            line = format_model_line(entry, is_default)
            print(f"{pointer} {line}")
        key = read_key()
        if key == "up":
            selected = (selected - 1) % len(registry)
        elif key == "down":
            selected = (selected + 1) % len(registry)
        elif key == "enter":
            set_default_model(registry[selected]["name"])
            return
        elif key in {"q", "ctrl_c"}:
            print("Cancelled.")
            return


def print_model_choices(registry: list[dict[str, str]], default_model: str) -> None:
    for entry in registry:
        is_default = entry["name"] == default_model
        print(format_model_line(entry, is_default))


def ensure_copilot_authenticated() -> None:
    apply_github_copilot_oauth_patch()

    print("Checking GitHub Copilot OAuth credentials...", flush=True)
    print(
        "If this machine is not authenticated yet, follow the GitHub device link "
        "and enter the code printed below.",
        flush=True,
    )
    github_copilot_authenticator().get_api_key()
    print("GitHub Copilot OAuth credentials are ready.", flush=True)


def require_copilot_login() -> None:
    apply_github_copilot_oauth_patch()
    authenticator = github_copilot_authenticator()
    if not has_valid_api_key(authenticator) and not has_access_token(authenticator):
        print("GitHub Copilot is not authenticated. Run `cpx login` first.", flush=True)
        raise SystemExit(1)
    try:
        authenticator.get_api_key()
    except Exception as exc:
        print(
            f"GitHub Copilot credentials are invalid or expired: {short_error(exc)}",
            flush=True,
        )
        print("Run `cpx login` to authenticate again.", flush=True)
        raise SystemExit(1) from exc


def github_copilot_authenticator():
    apply_github_copilot_oauth_patch()

    from litellm.llms.github_copilot.authenticator import Authenticator

    return Authenticator()


def has_access_token(authenticator) -> bool:
    try:
        return bool(Path(authenticator.access_token_file).read_text(encoding="utf-8").strip())
    except OSError:
        return False


def has_valid_api_key(authenticator) -> bool:
    try:
        data = json.loads(Path(authenticator.api_key_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    token = data.get("token")
    expires_at = data.get("expires_at", 0)
    return (
        bool(token)
        and isinstance(expires_at, int | float)
        and expires_at > datetime.now().timestamp()
    )


def stop_existing_instance(pid_file: Path) -> None:
    pid = read_pid_file(pid_file)
    if pid is None:
        return
    if not is_process_running(pid):
        cleanup_pid_file(pid_file)
        return

    print(f"Stopping previous Copilot Proxy instance (pid {pid})...", flush=True)
    terminate_process(pid)
    for _ in range(50):
        if not is_process_running(pid):
            cleanup_pid_file(pid_file)
            print("Previous Copilot Proxy instance stopped.", flush=True)
            return
        time.sleep(0.1)

    msg = f"Previous Copilot Proxy instance (pid {pid}) did not stop in time."
    raise RuntimeError(msg)


def read_pid_file(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid_file(pid_file: Path, pid: int) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid), encoding="utf-8")


def cleanup_pid_file(pid_file: Path) -> None:
    try:
        pid_file.unlink()
    except FileNotFoundError:
        return


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def ensure_port_available(host: str, port: int) -> None:
    if is_port_available(host, port):
        return
    msg = (
        f"Port {port} on {host} is already in use, but no restartable Copilot Proxy "
        "instance was found. Stop the process using that port or change COPILOT_PROXY_PORT."
    )
    raise RuntimeError(msg)


def is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError:
        return False
    return True


def print_startup_info(settings) -> None:
    root_base_url = f"http://{settings.host}:{settings.port}"
    openai_base_url = f"{root_base_url}/v1"

    print("", flush=True)
    print("Copilot Proxy is starting...", flush=True)
    print(f"OpenAI Base URL:    {openai_base_url}", flush=True)
    print(f"Anthropic Base URL: {root_base_url}", flush=True)
    print(f"API Key:            {settings.local_api_key}", flush=True)
    print(f"Default model:      {settings.default_model}", flush=True)
    print("", flush=True)


def format_model_line(entry: dict[str, str], is_default: bool) -> str:
    prefix = "*" if is_default else " "
    mode = f" ({entry['mode']})" if entry.get("mode") else ""
    line = f"{prefix} {entry['name']} -> {entry['upstream']}{mode}"
    return green(line) if is_default else line


def green(text: str) -> str:
    if not supports_color():
        return text
    return f"\033[32m{text}\033[0m"


def red(text: str) -> str:
    if not supports_color():
        return text
    return f"\033[31m{text}\033[0m"


def package_version() -> str:
    try:
        return version("cpx")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def supports_color() -> bool:
    return sys.stdout.isatty() and not os.getenv("NO_COLOR")


def clear_screen() -> None:
    if supports_color():
        print("\033[2J\033[H", end="")
    else:
        print("\n" * 2)


def read_key() -> str:
    if sys.platform == "win32":
        import msvcrt

        char = msvcrt.getch()
        if char in {b"\x00", b"\xe0"}:
            second = msvcrt.getch()
            if second == b"H":
                return "up"
            if second == b"P":
                return "down"
        if char == b"\r":
            return "enter"
        if char == b"\x03":
            return "ctrl_c"
        return char.decode(errors="ignore").lower()

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
        if char == "\x1b":
            sequence = sys.stdin.read(2)
            if sequence == "[A":
                return "up"
            if sequence == "[B":
                return "down"
        if char in {"\r", "\n"}:
            return "enter"
        if char == "\x03":
            return "ctrl_c"
        return char.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    main(sys.argv[1:])
