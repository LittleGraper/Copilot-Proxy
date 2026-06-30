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
Copy-Item models.toml.example models.toml
```

编辑 `.env`，把 `LOCAL_API_KEY` 替换成本地使用的密钥。不要提交 `.env`。

模型清单由本地 `models.toml` 维护，`.env` 默认只保存密钥、端口、日志级别等运行环境配置。`models.toml` 是本地配置，已被 `.gitignore` 忽略；仓库只提交 `models.toml.example` 作为模板。

## 一键启动

推荐直接使用跨平台 Python CLI：

```bash
uv run copilot-proxy
```

它会先检查 GitHub Copilot OAuth 凭据。如果当前机器还没有完成授权，终端会显示 GitHub device link 和需要输入的验证码，例如：

```text
Please visit https://github.com/login/device and enter code XXXX-XXXX to authenticate.
```

完成授权后，启动脚本会显示两种客户端格式使用的 Base URL 和本地 API Key：

```text
OpenAI Base URL:    http://127.0.0.1:4000/v1
Anthropic Base URL: http://127.0.0.1:4000
API Key:            <LOCAL_API_KEY>
```

重复运行启动脚本时，启动器会先读取 `.copilot-proxy.pid`，如果发现上一次由本项目启动的代理实例仍在运行，会先停止旧实例，再使用配置端口重新启动。也就是说，默认行为是“重启本项目代理”，不是开多个实例。

```text
Stopping previous Copilot Proxy instance (pid 12345)...
Previous Copilot Proxy instance stopped.
OpenAI Base URL:    http://127.0.0.1:4000/v1
Anthropic Base URL: http://127.0.0.1:4000
```

如果配置端口被其他无关进程占用，启动器不会误杀该进程，会直接报错。请手动释放端口，或者修改 `.env` 里的 `COPILOT_PROXY_PORT`。

如果你不希望启动器停止上一次记录的本项目实例：

```bash
uv run copilot-proxy --no-restart-existing
```

也可以使用仓库里的薄脚本：

```powershell
# Windows PowerShell
.\scripts\start.ps1
```

```cmd
:: Windows cmd.exe
scripts\start.cmd
```

```bash
# macOS / Linux / Git Bash / WSL
sh ./scripts/start.sh
```

如果你只想启动服务、不做 Copilot OAuth 预检查：

```bash
uv run copilot-proxy --skip-auth-check
```

## 运行细节

启动带 OpenAI 和 Anthropic 路由的 FastAPI wrapper：

```bash
copilot-proxy
```

等价的开发命令：

```bash
uvicorn copilot_proxy.main:app --host 127.0.0.1 --port 4000 --reload
```

如果只需要 LiteLLM 原生路由，也可以直接运行 LiteLLM Proxy：

```bash
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

模型别名配置在本地 `models.toml` 中。首次使用时从模板复制：

```bash
cp models.toml.example models.toml
```

Windows PowerShell：

```powershell
Copy-Item models.toml.example models.toml
```

| 本地模型名 | 上游模型名 |
| --- | --- |
| `gpt-4` | `github_copilot/gpt-4` |
| `gpt-4o` | `github_copilot/gpt-4o` |
| `gpt-5.1-codex` | `github_copilot/gpt-5.1-codex` |
| `text-embedding-3-small` | `github_copilot/text-embedding-3-small` |

不同账号和订阅可用的 Copilot 模型可能不同。如果你的账号暴露的模型名不一样，请编辑本地 `models.toml`。

示例：

```toml
[models]
default = "gpt-4"

[[models.aliases]]
name = "gpt-4"
upstream = "github_copilot/gpt-4"

[[models.aliases]]
name = "gpt-5.5"
upstream = "github_copilot/gpt-5.5"
```

字段说明：

- `name`：客户端请求时看到和传入的模型名
- `upstream`：实际传给 LiteLLM 的上游模型名
- `mode`：可选，用于标记 `responses`、`embedding` 等模型用途

`.env` 仍然支持临时覆盖：

```env
COPILOT_PROXY_DEFAULT_MODEL=gpt-5.5
COPILOT_PROXY_MODEL_ALIASES=gpt-5.5,gpt-4o
```

正常使用时更推荐维护 `models.toml`，避免模型配置散落在环境变量里。若本地 `models.toml` 不存在，程序会回退读取 `models.toml.example`，方便刚克隆仓库时直接启动。

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