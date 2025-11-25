"""
Discord Bot 配置文件
"""
import os
from typing import Optional, List

# ==================== Discord 配置 ====================

# 服务器ID（用于快速同步命令，留空则全局同步但需要1小时生效）
# 右键服务器图标 -> 复制服务器ID（需要开启开发者模式）
DISCORD_GUILD_ID: Optional[str] = os.getenv("DISCORD_GUILD_ID", None)

# 允许使用命令的频道ID列表（留空则所有频道都可以使用）
# 右键频道 -> 复制频道ID（需要开启开发者模式）
DISCORD_CHANNEL_BOTCOMMAND_ID = 1440543916997873805
DISCORD_CHANNEL_AI_ID = 1440566691863203981
ALLOWED_CHANNELS_BOTCOMMAND: List[int] = [
    DISCORD_CHANNEL_BOTCOMMAND_ID
]
ALLOWED_CHANNELS_AI: List[int] = [
    DISCORD_CHANNEL_AI_ID
]
# ==================== Ollama AI 配置 ====================

OLLAMA_CONFIG = {
    "url": "http://127.0.0.1:11434",
    "model": "qwen3:4b-instruct-2507-q4_K_M",  # 使用的AI模型
    "timeout": 300,  # API超时时间（秒）
    "chat_timeout": 180,  # 对话无活动自动结束时间（秒）
}

# ==================== 数据库配置 ====================

# 数据库文件路径会从 DB.py 中自动导入
# 如需修改，请在 DB.py 中修改 FLIGHTLOG_DB_PATH

# ==================== Bot 行为配置 ====================

# 查询结果显示的最大记录数
MAX_DISPLAY_RECORDS = 20

# 是否启用开发者模式（显示更多调试信息）
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

