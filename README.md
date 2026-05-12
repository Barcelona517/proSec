# Mini OpenClaw 作业实现说明

本项目是一个基于 Python 的“迷你版 OpenClaw”实现，包含命令行智能体、Gradio 网页端、工具调用、对话持久化和视觉识图能力。

## 工作目录结构

```text
proSec/
├─ config.py                     配置中心，集中管理模型名、工作目录、历史文件和系统提示词
├─ llm_client.py                大模型客户端封装，负责创建文本模型和视觉模型客户端
├─ main.py                      命令行智能体主流程，负责消息循环、工具调用和历史记录
├─ tooling.py                   工具注册与执行核心，包含参数解析和安全校验
├─ skill_manager.py             skill 扫描、安装、删除和展示逻辑
├─ vision_agent.py              图片输入处理与视觉模型调用
├─ web_ui.py                    Gradio 网页界面、上传、会话管理和流式输出
├─ requirements.txt             Python 依赖列表
├─ README.md                    项目说明文档
├─ conversations.json           网页端会话历史记录
├─ chat_history.json            命令行或当前会话历史记录
├─ OpenClaw 个人 Mini 实现-作业2.docx  原始作业要求文档
├─ _docx_extracted.txt          从 docx 提取出的文本内容
├─ generate_ppt.py              生成 PPT 的辅助脚本
├─ check_prime.py               独立测试脚本
├─ uploads/                     上传文件缓存目录
├─ web_ui.log                   网页端运行日志
├─ web_ui.err                   网页端错误日志
└─ __pycache__/                 Python 缓存目录
```

## 代码文件说明

- [config.py](config.py) 负责读取 `.env` 和环境变量，统一管理工作目录、模型名、历史文件路径和系统提示词。
- [llm_client.py](llm_client.py) 负责封装大模型客户端，提供文本对话和视觉识图所需的 API 初始化。
- [main.py](main.py) 是命令行智能体核心，负责历史读写、消息构造、ReAct 循环和多轮工具调用。
- [tooling.py](tooling.py) 是工具系统核心，负责工具注册、执行、参数解析和路径安全检查。
- [skill_manager.py](skill_manager.py) 负责 skill 的扫描、导入、安装、删除和 skill 列表渲染。
- [vision_agent.py](vision_agent.py) 负责将本地图片交给视觉模型，完成读图、识图和图片问答。
- [web_ui.py](web_ui.py) 是网页端界面，负责聊天 UI、上传、会话列表、技能面板和流式输出。
- [requirements.txt](requirements.txt) 记录项目依赖，便于环境安装和复现。

## 功能实现说明

#### 1. 大模型接入与对话能力

怎么实现：
- 在 [llm_client.py](llm_client.py) 中封装 OpenAI 兼容客户端。
- 在 [main.py](main.py) 中维护对话历史，并把历史上下文一起发给模型。
- 在 [web_ui.py](web_ui.py) 中提供网页聊天入口。

涉及文件：
- [llm_client.py](llm_client.py)
- [main.py](main.py)
- [web_ui.py](web_ui.py)
- [config.py](config.py)

#### 2. 工具调用（Function Calling）能力

怎么实现：
- 在 [tooling.py](tooling.py) 中注册本地工具并统一执行。
- 在 [main.py](main.py) 中把工具列表传给模型，并处理工具返回结果。
- 项目当前已有时间、天气、搜索、读写文件、shell 执行等工具，可满足“至少 3 个自定义工具”的要求。

涉及文件：
- [tooling.py](tooling.py)
- [main.py](main.py)
- [config.py](config.py)

#### 3. ReAct 推理循环

怎么实现：
- 在 [main.py](main.py) 中实现 `Thought -> Action -> Observation` 的循环。
- 每轮把模型输出的工具调用执行掉，再把结果回传给模型。
- 通过 `MAX_TURNS` 控制最大轮数，避免死循环。

涉及文件：
- [main.py](main.py)
- [tooling.py](tooling.py)

#### 4. 本地执行与安全隔离

怎么实现：
- 在 [tooling.py](tooling.py) 中对路径做工作目录限制，避免越界访问。
- 对 shell 执行加白名单和参数校验，降低危险命令风险。
- 在 [main.py](main.py) 中捕获工具异常并返回友好错误。

涉及文件：
- [tooling.py](tooling.py)
- [main.py](main.py)
- [config.py](config.py)

### 扩展要求

#### 1. 对话历史持久化

怎么实现：
- 用 [chat_history.json](chat_history.json) 和 [conversations.json](conversations.json) 保存历史记录。
- 在 [main.py](main.py) 和 [web_ui.py](web_ui.py) 中分别处理命令行与网页端的加载和保存。

涉及文件：
- [main.py](main.py)
- [web_ui.py](web_ui.py)
- [chat_history.json](chat_history.json)
- [conversations.json](conversations.json)

#### 2. 工具插件化 / skill 化

怎么实现：
- 通过 [skill_manager.py](skill_manager.py) 扫描、导入和安装 skill。
- 在 [main.py](main.py) 中根据用户输入动态注入 skill 提示词。
- 在 [web_ui.py](web_ui.py) 中提供 skill 面板、安装入口和删除入口。

涉及文件：
- [skill_manager.py](skill_manager.py)
- [main.py](main.py)
- [web_ui.py](web_ui.py)

#### 3. 流式输出

怎么实现：
- 在 [main.py](main.py) 中提供 `run_agent_stream_with_trace`。
- 在 [web_ui.py](web_ui.py) 中把流式增量结果实时渲染到页面。

涉及文件：
- [main.py](main.py)
- [web_ui.py](web_ui.py)

#### 4. 多轮规划展示

怎么实现：
- 在 [main.py](main.py) 中记录每轮 thought、action 和 observation。
- 在控制台打印每一轮执行过程，便于调试和展示推理链路。

涉及文件：
- [main.py](main.py)

#### 5. 安全的 shell 执行沙箱

怎么实现：
- 在 [tooling.py](tooling.py) 中限制可执行命令范围。
- 对参数进行白名单校验，避免危险命令直接透传。

涉及文件：
- [tooling.py](tooling.py)

#### 6. 多 Agent 协作雏形

怎么实现：
- 在 [tooling.py](tooling.py) 中提供 `delegate_subagent`。
- 在 [main.py](main.py) 中将部分分析任务委托给子 Agent。

涉及文件：
- [tooling.py](tooling.py)
- [main.py](main.py)

## 当前已实现的工具

在 [tooling.py](tooling.py) 中，当前已内置以下工具：

- `get_current_time`：查询当前时间或指定时区时间。
- `get_weather`：查询天气。
- `search_web`：搜索网络信息，辅助回答名词解释、时效性问题等。
- `list_files`：列出工作目录下的文件和目录。
- `read_text_file`：读取文本与常见文档内容，支持 `.txt`、`.md`、`.json`、`.csv`、`.tsv`、`.pdf`、`.docx`、`.xlsx`、`.pptx`。
- `write_text_file`：写入或追加文本文件。
- `run_shell_command`：受限 shell 执行工具，带白名单和参数校验。
- `delegate_subagent`：多 Agent 雏形工具，可把子任务委托给轻量分析 Agent。

## 网页端额外能力

除了作业最小要求，网页端还额外支持：

- 多会话历史列表
- 重命名 / 置顶 / 删除历史会话
- 图片上传并交给视觉模型分析
- 文件上传并自动抽取内容

## 运行方式

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

建议在项目根目录新建 `.env`，至少包含：

```env
OPENAI_API_KEY=你的文本模型Key
OPENAI_BASE_URL=你的文本模型Base URL
MODEL_NAME=deepseek-chat
```

如果要启用视觉模型，再补：

```env
VISION_API_KEY=你的视觉模型Key
VISION_BASE_URL=你的视觉模型Base URL
VISION_MODEL=qwen3-vl-235b-a22b-thinking
```

### 3. 运行命令行版本

```bash
python main.py
```

### 4. 运行网页版本

```bash
python web_ui.py
```

默认会在本机启动一个 Gradio 页面。

