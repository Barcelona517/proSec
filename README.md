# Mini OpenClaw 作业实现说明

本项目是一个基于 Python 的“迷你版 OpenClaw”实现。

它的核心能力：

- 接入大模型 API，支持多轮对话
- 支持 Function Calling / 工具调用
- 实现 ReAct 风格循环：`Thought -> Action -> Observation`
- 提供本地工具执行与基本安全隔离
- 支持对话历史持久化
- 提供 Web 聊天界面
- 扩展实现了文件解析、视觉识图、工具插件化、流式输出等能力

## 项目目录

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

