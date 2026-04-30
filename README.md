# Mini OpenClaw (Python)

这是一个按作业要求实现的极简智能体框架，具备：

- 大模型接入（OpenAI 兼容接口）
- 多轮对话上下文
- 3 个本地工具（列目录、读文件、写文件）
- ReAct 风格循环（Thought/Reply -> Action -> Observation）
- 基本安全隔离（工具操作限定在指定目录）
- 异常捕获与友好返回
- 对话历史持久化（JSON）

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 配置环境变量

至少配置：

- `OPENAI_API_KEY`

可选配置：

- `OPENAI_BASE_URL`：切换到兼容 OpenAI 协议的平台（如部分 DeepSeek 网关）
- `MODEL_NAME`：默认 `deepseek-chat`（对应 DeepSeek V3.1）
- `MAX_TURNS`：默认 `8`
- `AGENT_WORKSPACE_ROOT`：工具允许访问的根目录，默认当前项目目录
- `HISTORY_FILE`：对话历史文件，默认 `chat_history.json`

推荐方式（写在项目根目录 `.env` 文件中）：

OPENAI_API_KEY=你的Key
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat

程序启动时会自动读取 `.env`（已集成 python-dotenv）。

PowerShell 示例：

```powershell
$env:OPENAI_API_KEY = "你的Key"
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:MODEL_NAME = "deepseek-chat"
```

## 3. 运行

```bash
python main.py
```

输入 `exit` 退出。

## 3.1 网页聊天界面（类似豆包/DeepSeek）

安装依赖后运行：

```bash
python web_ui.py
```

默认会在本机启动 `http://127.0.0.1:7860`，可在浏览器中连续多轮对话。

## 4. 与作业要求对应

- 必做 1（模型接入+多轮）：`main.py` + `llm_client.py`
- 必做 2（Function Calling + >=3 工具）：`tooling.py`
- 必做 3（ReAct 循环+终止条件）：`main.py` 中 `run_agent`
- 必做 4（安全与异常）：`tooling.py` 中 `safe_resolve_path` 与错误处理
- 扩展项（历史持久化）：`chat_history.json` 读写逻辑
# Tool Plugins (Dynamic Registration)

You can now add tools without editing core files.

1. Create plugin files under `tools_plugins/`, for example:
`tools_plugins/my_tools.py`

2. Export a function in plugin file:

```python
def register_tools(registry):
    registry.register(...)
```

3. Restart app; plugins are auto-loaded by `ToolRegistry`.

4. Optional: limit loaded plugins via `.env`:

```env
ENABLED_TOOL_PLUGINS=my_tools,another_tools
```

If `ENABLED_TOOL_PLUGINS` is empty, all `tools_plugins/*.py` (except `_*.py`) are loaded.
