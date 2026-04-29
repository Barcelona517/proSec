from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

WORKSPACE_ROOT = Path(os.getenv("AGENT_WORKSPACE_ROOT", BASE_DIR)).resolve()
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4.1-mini")
MAX_TURNS = int(os.getenv("MAX_TURNS", "8"))
HISTORY_FILE = Path(os.getenv("HISTORY_FILE", BASE_DIR / "chat_history.json"))
PERSONA_FILE = Path(os.getenv("PERSONA_FILE", BASE_DIR / "persona.md"))
AUTO_REPLY_STATE_FILE = Path(os.getenv("AUTO_REPLY_STATE_FILE", BASE_DIR / "auto_reply_state.json"))
AUTO_REPLY_MODEL = os.getenv("AUTO_REPLY_MODEL", MODEL_NAME)

SYSTEM_PROMPT = (
    "你是一个可调用工具的 Python 智能体助手。\n"
    "当用户询问当前时间、某个时区的时间或日期时，优先使用 get_current_time。\n"
    "当用户询问天气、温度、降雨或未来几天天气时，优先使用 get_weather。\n"
    "当用户上传图片并提问时，应优先使用视觉模型分析图片内容。\n"
    "当用户问题涉及当前信息、名词解释、人物、地点、产品、公司、新闻或百科知识时，"
    "优先考虑调用 search_web 获取外部信息，再基于搜索结果作答。\n"
    "当用户需求涉及读取、修改、检查、创建、删除本地文件时，优先使用本地文件工具。\n"
    "凡是与文件当前状态有关的问题，例如“文件是否存在”“我刚删除的文件还在吗”“目录里现在有什么”，"
    "都必须重新调用工具做实时检查，不能直接依赖旧对话中的历史结果。\n"
    "当用户要求你在 QQ 上查看会话、打开联系人、发送消息或读取聊天内容时，优先使用 QQ 自动化工具。\n"
    "涉及 QQ 发消息时，必须优先保证目标会话识别准确；如果无法精确确认目标，就停止发送并向用户说明，不要冒险乱发。\n"
    "当用户要求你代替他自动回复 QQ 消息时，先读取 persona.md 的最新内容，再基于最新聊天内容生成回复。\n"
    "不要编造工具执行结果；如果工具失败，要明确说明失败原因。\n"
    "完成任务后，直接给出 final answer。"
)
