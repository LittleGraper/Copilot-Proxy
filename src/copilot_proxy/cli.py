from __future__ import annotations

import argparse
import sys

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
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.validate_runtime()

    if not args.skip_auth_check:
        ensure_copilot_authenticated()

    print_startup_info(settings)
    uvicorn.run(
        "copilot_proxy.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


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
