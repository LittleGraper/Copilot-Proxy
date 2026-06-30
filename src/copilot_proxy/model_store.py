from __future__ import annotations

import tomllib
from pathlib import Path


def load_model_config(path: Path) -> tuple[str, list[dict[str, str]]]:
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)
    models = data.get("models", {})
    default = models.get("default")
    aliases = models.get("aliases", [])
    registry: list[dict[str, str]] = []
    for entry in aliases:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        upstream = entry.get("upstream")
        if not isinstance(name, str) or not isinstance(upstream, str):
            continue
        normalized = {"name": name, "upstream": upstream}
        mode = entry.get("mode")
        if isinstance(mode, str) and mode:
            normalized["mode"] = mode
        registry.append(normalized)
    if not isinstance(default, str) or not default:
        default = registry[0]["name"] if registry else "gpt-4"
    return default, registry


def write_model_config(path: Path, default: str, registry: list[dict[str, str]]) -> None:
    lines = ["[models]", f'default = "{_escape(default)}"', ""]
    for entry in registry:
        lines.append("[[models.aliases]]")
        lines.append(f'name = "{_escape(entry["name"])}"')
        lines.append(f'upstream = "{_escape(entry["upstream"])}"')
        mode = entry.get("mode")
        if mode:
            lines.append(f'mode = "{_escape(mode)}"')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
