from __future__ import annotations

from fastapi.testclient import TestClient

from copilot_proxy.main import app
from copilot_proxy.settings import get_settings


class FailingLiteLLM:
    async def acompletion(self, **_: object) -> None:
        raise RuntimeError("upstream exploded in C:\\secret\\.venv\\path")


def test_openai_route_shapes_upstream_errors(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr("copilot_proxy.main._litellm", lambda: FailingLiteLLM())

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-test"},
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "message": "Upstream provider request failed.",
            "type": "upstream_error",
            "code": None,
        }
    }


def test_anthropic_route_shapes_upstream_errors(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "sk-test")
    get_settings.cache_clear()
    monkeypatch.setattr("copilot_proxy.main._litellm", lambda: FailingLiteLLM())

    client = TestClient(app)
    response = client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer sk-test"},
        json={"model": "gpt-4", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 502
    assert response.json() == {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "Upstream provider request failed.",
        },
    }
