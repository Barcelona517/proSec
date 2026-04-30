# Mini OpenClaw 作业实现说明

本项目是一个基于 Python 的“迷你版 OpenClaw”实现，对应工作目录中的作业文档《OpenClaw 个人 Mini 实现-作业2.docx》。

它完成了作业要求中的核心能力：

- 接入大模型 API，支持多轮对话
- 支持 Function Calling / 工具调用
- 实现 ReAct 风格循环：`Thought -> Action -> Observation`
- 提供本地工具执行与基本安全隔离
- 支持对话历史持久化
- 提供 Web 聊天界面
- 扩展实现了文件解析、视觉识图、工具插件化、流式输出等能力

## 项目目录

下面是当前工作目录中和作业实现最相关的文件：

```text
proSec/
├─ config.py
├─ llm_client.py
├─ main.py
├─ tooling.py
├─ vision_agent.py
├─ web_ui.py
├─ requirements.txt
├─ README.md
├─ conversations.json
├─ chat_history.json
├─ OpenClaw 个人 Mini 实现-作业2.docx
├─ _docx_extracted.txt
├─ tools_plugins/
│  └─ sample_notify_plugin.py
├─ uploads/
│  └─ ... 上传的图片/文档缓存
├─ web_ui.log
├─ web_ui.err
└─ check_prime.py
```

## 文件说明

### 核心代码文件

- [config.py](/c:/Users/tyy86/Desktop/proSec/config.py)
  负责读取 `.env` 和环境变量，集中管理：
  - 工作目录 `WORKSPACE_ROOT`
  - 文本模型 `MODEL_NAME`
  - 视觉模型 `VISION_MODEL`
  - 最大工具轮数 `MAX_TURNS`
  - 历史文件路径 `HISTORY_FILE`
  - 系统提示词 `SYSTEM_PROMPT`

- [llm_client.py](/c:/Users/tyy86/Desktop/proSec/llm_client.py)
  负责创建大模型客户端：
  - `build_client()`：文本对话模型
  - `build_vision_client()`：视觉模型
  统一使用 OpenAI 兼容接口。

- [main.py](/c:/Users/tyy86/Desktop/proSec/main.py)
  是命令行智能体主流程，完成：
  - 对话历史读写
  - 用户输入预处理
  - ReAct 风格消息循环
  - 多轮工具调用
  - 结构化轨迹记录
  - 流式对话版本 `run_agent_stream_with_trace`

- [tooling.py](/c:/Users/tyy86/Desktop/proSec/tooling.py)
  是工具系统核心，定义：
  - `Tool` 数据结构
  - `ToolRegistry`
  - 工具注册 / 执行 / 参数解析
  - 路径安全检查
  - 插件动态加载

- [vision_agent.py](/c:/Users/tyy86/Desktop/proSec/vision_agent.py)
  负责图片输入：
  - 将本地图片转成 `data URL`
  - 调用视觉模型完成识图、读题、图片问答

- [web_ui.py](/c:/Users/tyy86/Desktop/proSec/web_ui.py)
  是 Gradio 网页端，负责：
  - 聊天界面渲染
  - 多会话历史管理
  - 文件/图片上传
  - 流式回答显示
  - 插件中心 UI

### 配置与依赖

- [requirements.txt](/c:/Users/tyy86/Desktop/proSec/requirements.txt)
  记录项目运行依赖：
  - `openai`
  - `python-dotenv`
  - `gradio`
  - `pypdf`
  - `python-docx`
  - `openpyxl`
  - `python-pptx`

### 数据与缓存文件

- [conversations.json](/c:/Users/tyy86/Desktop/proSec/conversations.json)
  网页端多会话历史记录。

- [chat_history.json](/c:/Users/tyy86/Desktop/proSec/chat_history.json)
  命令行或当前活动会话的历史持久化文件。

- [uploads](/c:/Users/tyy86/Desktop/proSec/uploads)
  网页端上传图片、PDF、DOCX、PPTX 等文件时的缓存目录。

- [web_ui.log](/c:/Users/tyy86/Desktop/proSec/web_ui.log)、[web_ui.err](/c:/Users/tyy86/Desktop/proSec/web_ui.err)
  网页端运行日志文件。

### 作业文档与辅助文件

- [OpenClaw 个人 Mini 实现-作业2.docx](</c:/Users/tyy86/Desktop/proSec/OpenClaw 个人 Mini 实现-作业2.docx>)
  作业原始要求文档。

- [_docx_extracted.txt](/c:/Users/tyy86/Desktop/proSec/_docx_extracted.txt)
  从 docx 提取出的文本内容，便于程序读取。

- [check_prime.py](/c:/Users/tyy86/Desktop/proSec/check_prime.py)
  独立的小测试脚本，不属于主实现链路。

### 插件目录

- [tools_plugins](/c:/Users/tyy86/Desktop/proSec/tools_plugins)
  工具插件目录，支持无需修改核心代码，动态添加新工具。

- [sample_notify_plugin.py](/c:/Users/tyy86/Desktop/proSec/tools_plugins/sample_notify_plugin.py)
  示例插件，实现了一个简单的本地笔记追加工具。

## 当前已实现的工具

在 [tooling.py](/c:/Users/tyy86/Desktop/proSec/tooling.py) 中，当前已内置以下工具：

- `get_current_time`
  查询当前时间或指定时区时间。

- `get_weather`
  查询天气。

- `search_web`
  搜索网络信息，辅助回答名词解释、时效性问题等。

- `list_files`
  列出工作目录下的文件和目录。

- `read_text_file`
  读取文本与常见文档内容。
  当前支持：
  - `.txt`
  - `.md`
  - `.json`
  - `.csv`
  - `.tsv`
  - `.pdf`
  - `.docx`
  - `.xlsx`
  - `.pptx`

- `write_text_file`
  写入或追加文本文件。

- `run_shell_command`
  受限 shell 执行工具，带白名单和参数校验。

- `delegate_subagent`
  多 Agent 雏形工具，可把子任务委托给轻量分析 Agent。

## 作业要求与实现对应

### 1. 大模型接入与多轮对话

作业要求：

- 接入至少一种大模型 API
- 接收自然语言输入
- 支持多轮对话，维护上下文

实现方式：

- 模型接入由 [llm_client.py](/c:/Users/tyy86/Desktop/proSec/llm_client.py) 完成
- 对话历史由 [main.py](/c:/Users/tyy86/Desktop/proSec/main.py) 中的 `load_history` / `save_history` 管理
- 在 `run_agent` 和 `run_agent_stream_with_trace` 中，将系统消息、历史消息、当前用户消息拼接后发给模型

### 2. Function Calling / 工具调用

作业要求：

- 至少实现 3 个自定义工具函数
- 大模型可自主判断是否调用工具、调用哪个工具、传什么参数
- 工具结果能返回给大模型

实现方式：

- [tooling.py](/c:/Users/tyy86/Desktop/proSec/tooling.py) 中定义 `ToolRegistry`
- `all_for_openai()` 将工具描述转换为 OpenAI 兼容函数定义
- [main.py](/c:/Users/tyy86/Desktop/proSec/main.py) 中把工具列表通过 `tools=` 传给模型
- 当模型返回 `tool_calls` 后，程序逐个执行，再把结果作为 `role=tool` 消息补回对话上下文

### 3. ReAct 推理循环

作业要求：

- 实现 `Thought -> Action -> Observation`
- 支持多轮工具调用
- 具备终止条件

实现方式：

- [main.py](/c:/Users/tyy86/Desktop/proSec/main.py) 的 `_run_agent_core`
  中实现循环：
  1. 发消息给模型
  2. 读取模型回答或工具调用
  3. 执行工具
  4. 把工具结果回填给模型
  5. 若模型不再请求工具，则结束

- `MAX_TURNS` 控制最大轮数，避免无限循环
- `trace_steps` 记录每轮的 `thought / actions / observation`

### 4. 本地执行与安全隔离

作业要求：

- 工具执行时要有基本安全检查
- 异常要捕获并友好提示

实现方式：

- [tooling.py](/c:/Users/tyy86/Desktop/proSec/tooling.py) 中：
  - `safe_resolve_path()` 强制文件操作限制在 `WORKSPACE_ROOT` 内
  - `run_shell_command` 仅允许白名单程序与有限参数
  - 对所有工具执行异常统一抛出 `ToolExecutionError`

- [main.py](/c:/Users/tyy86/Desktop/proSec/main.py) 中：
  - 捕获工具错误
  - 将错误包装为结构化 JSON 返回给模型
  - 必要时生成最终友好报错

## 2.2 扩展建议完成情况

根据作业文档中的“扩展建议”，本项目当前完成情况如下：

- 对话历史持久化：已实现
  - `chat_history.json`
  - `conversations.json`

- 工具插件化：已实现
  - [tooling.py](/c:/Users/tyy86/Desktop/proSec/tooling.py) 启动时自动扫描 `tools_plugins/*.py`
  - 插件通过 `register_tools(registry)` 动态注册

- 流式输出：已实现
  - [main.py](/c:/Users/tyy86/Desktop/proSec/main.py) 中 `run_agent_stream_with_trace`
  - [web_ui.py](/c:/Users/tyy86/Desktop/proSec/web_ui.py) 中进行前端流式展示

- 多轮规划展示：已实现
  - 控制台输出每轮 `Thought / Action / Observation`
  - 网页端可渲染轨迹卡片

- 更安全的 shell 沙箱：已实现
  - `run_shell_command` 带命令白名单、参数限制、超时和输出截断

- 多 Agent 协作雏形：已实现
  - `delegate_subagent`

## 网页端额外能力

除了作业最小要求，网页端还额外支持：

- 多会话历史列表
- 重命名 / 置顶 / 删除历史会话
- 图片上传并交给视觉模型分析
- 文件上传并自动抽取内容
- 插件中心（上传 `.py` / `.zip` 插件）

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

## 总结

这个项目已经覆盖了作业文档中的主要必做项，并完成了多项扩展能力。  
如果把它作为课程作业提交，README 可以帮助老师快速看到：

- 项目目录结构
- 每个关键文件的职责
- 各项作业要求的代码落点
- 当前已经完成的扩展功能
