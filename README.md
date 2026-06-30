# Copilot-Proxy

用于 GitHub Copilot Models 的本地 LiteLLM 代理。它会暴露一个本地 Base URL 和 API Key，并支持 OpenAI 兼容格式与 Anthropic 兼容格式的请求。

默认上游是 LiteLLM 的 `github_copilot/` provider。第一次真实调用模型时，LiteLLM 会启动 GitHub OAuth device flow，并把 Copilot 凭据保存在本地。

## 当前状态

当前仓库已经包含初始实现：

- OpenAI 兼容路由：`/v1/models`、`/v1/chat/completions`、`/v1/embeddings`、`/v1/responses`
- Anthropic 兼容路由：`/v1/messages`、`/messages`
- 通过 `LOCAL_API_KEY` 使用固定的本地 Bearer Key
- 提供 `litellm.yaml`，可直接使用 `litellm --config litellm.yaml` 启动 LiteLLM Proxy
- 支持 Anthropic 文本、工具、图片块、文档块的请求和响应转换

定位：这是本机自用版本，默认只绑定 `127.0.0.1`。不要把它直接暴露到公网；如果需要多人或公网使用，请先补充密钥轮换、限流、TLS、反向代理和访问审计。

实现中包含一个 GitHub Copilot OAuth 兼容补丁，用于规避当前 LiteLLM 版本在本环境中 device flow 轮询过早返回 `incorrect_device_code` 的问题。补丁只在本代理调用 LiteLLM 前应用；如果以后 LiteLLM 官方修复了该问题，可以移除这个补丁。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，把 `LOCAL_API_KEY` 替换成本地使用的密钥。不要提交 `.env`。

## 运行

启动带 OpenAI 和 Anthropic 路由的 FastAPI wrapper：

```powershell
copilot-proxy
```

等价的开发命令：

```powershell
uvicorn copilot_proxy.main:app --host 127.0.0.1 --port 4000 --reload
```

如果只需要 LiteLLM 原生路由，也可以直接运行 LiteLLM Proxy：

```powershell
litellm --config litellm.yaml --host 127.0.0.1 --port 4000
```

Base URL：

```text
http://127.0.0.1:4000/v1
```

鉴权方式：

```text
Authorization: Bearer <LOCAL_API_KEY>
```

## OpenAI 客户端示例

```python
from openai import OpenAI

client = OpenAI(
	base_url="http://127.0.0.1:4000/v1",
	api_key="sk-local-change-me",
)

response = client.chat.completions.create(
	model="gpt-4",
	messages=[{"role": "user", "content": "写一个简短的 Python 斐波那契函数。"}],
)

print(response.choices[0].message.content)
```

## Anthropic 客户端示例

```python
from anthropic import Anthropic

client = Anthropic(
	base_url="http://127.0.0.1:4000",
	api_key="sk-local-change-me",
)

message = client.messages.create(
	model="gpt-4",
	max_tokens=500,
	messages=[{"role": "user", "content": "解释 Python 里的 async/await。"}],
)

print(message.content[0].text)
```

## 模型别名

模型别名配置在 `litellm.yaml` 和 `.env.example` 中：

| 本地模型名 | 上游模型名 |
| --- | --- |
| `gpt-4` | `github_copilot/gpt-4` |
| `gpt-4o` | `github_copilot/gpt-4o` |
| `gpt-5.1-codex` | `github_copilot/gpt-5.1-codex` |
| `text-embedding-3-small` | `github_copilot/text-embedding-3-small` |

不同账号和订阅可用的 Copilot 模型可能不同。如果你的账号暴露的模型名不一样，请编辑 `litellm.yaml` 和 `COPILOT_PROXY_MODEL_ALIASES`。

## 验证

```powershell
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
```

设置 `LOCAL_API_KEY` 后，可以手动做一次 smoke test：

```powershell
curl.exe http://127.0.0.1:4000/v1/models -H "Authorization: Bearer $env:LOCAL_API_KEY"
```

## 注意事项

- 需要可用的 GitHub Copilot 权限。
- 第一次真实模型调用可能会触发 GitHub OAuth device flow。
- 工具、图片和文件支持还取决于所选 Copilot 模型本身的能力。
- 本代理会区分本地鉴权和上游 Copilot 鉴权；`LOCAL_API_KEY` 只用于调用这个本地服务的客户端。