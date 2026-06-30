from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

import uvicorn

from .github_copilot_patch import apply_github_copilot_oauth_patch
from .settings import get_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Start the local GitHub Copilot proxy.")
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Start the proxy without checking GitHub Copilot OAuth first.",
    )
    parser.add_argument(
        "--no-restart-existing",
        action="store_true",
        help="Do not stop a previous proxy instance recorded in .copilot-proxy.pid.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.validate_runtime()
    pid_file = Path(".copilot-proxy.pid")
    if not args.no_restart_existing:
        stop_existing_instance(pid_file)
    ensure_port_available(settings.host, settings.port)

    if not args.skip_auth_check:
        ensure_copilot_authenticated()

    print_startup_info(settings)
    write_pid_file(pid_file)
    try:
        uvicorn.run(
            "copilot_proxy.main:app",
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
    finally:
        cleanup_pid_file(pid_file)


def ensure_copilot_authenticated() -> None:
    apply_github_copilot_oauth_patch()

    from litellm.llms.github_copilot.authenticator import Authenticator

    print("Checking GitHub Copilot OAuth credentials...", flush=True)
    print(
        "If this machine is not authenticated yet, follow the GitHub device link "
        "and enter the code printed below.",
        flush=True,
    )
    Authenticator().get_api_key()
    print("GitHub Copilot OAuth credentials are ready.", flush=True)


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


def write_pid_file(pid_file: Path) -> None:
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


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
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)
    else:
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


if __name__ == "__main__":
    main(sys.argv[1:])
