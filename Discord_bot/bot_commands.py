"""
Discord Bot 命令处理模块
实现玩家统计查询和AI聊天功能
"""

import sys
from pathlib import Path
import sqlite3
import json
from typing import Optional, Dict, List, Tuple
import asyncio
import time
import requests
import discord
from discord import app_commands
from discord.ext import commands, tasks

# 添加父目录到路径以导入DB模块
sys.path.append(str(Path(__file__).parent.parent))
from DB import flightlogDB, FLIGHTLOG_DB_PATH, ELO_TYPE

# 导入配置
from Discord_bot.config import OLLAMA_CONFIG, ALLOWED_CHANNELS_BOTCOMMAND, ALLOWED_CHANNELS_AI, MAX_DISPLAY_RECORDS

# 导入RAG系统
from Discord_bot.rag_system import RAGSystem


class PlayerStatsService:
    """玩家统计查询服务"""
    
    def __init__(self, db_path=FLIGHTLOG_DB_PATH):
        self.db = flightlogDB(db_path)
    
    def _load_all_players_with_names(self) -> List[Dict]:
        conn = self.db.get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT p.*, pn.name AS name_history
                FROM players p
                LEFT JOIN player_names pn ON p.id = pn.player_id
                WHERE p.is_archived = 0
            """)

            players = []
            for row in cur.fetchall():
                result = dict(row)
                raw_history = result.get("name_history")
                if raw_history:
                    try:
                        result["name_history"] = json.loads(raw_history)
                    except json.JSONDecodeError:
                        result["name_history"] = []
                else:
                    result["name_history"] = []
                players.append(result)
            return players
        finally:
            conn.close()

    def _score_name_match(self, query: str, player: Dict) -> Tuple[Optional[int], Optional[str]]:
        query_norm = query.strip().casefold()
        names = [player.get("steam_name", ""), *player.get("name_history", [])]

        best_score = None
        best_name = None
        for name in names:
            candidate = (name or "").strip()
            if not candidate:
                continue
            candidate_norm = candidate.casefold()
            if candidate_norm == query_norm:
                score = 0
            elif candidate_norm.startswith(query_norm):
                score = 1
            elif query_norm in candidate_norm:
                score = 2
            else:
                continue

            if best_score is None or score < best_score or (score == best_score and len(candidate) < len(best_name or candidate)):
                best_score = score
                best_name = candidate

        return best_score, best_name

    def resolve_player_by_name(self, player_name: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        通过玩家名称查找玩家。
        优先精确匹配，其次前缀匹配，再次子串匹配；如果最佳结果不唯一，则返回歧义提示。
        """
        candidates = []
        for player in self._load_all_players_with_names():
            score, matched_name = self._score_name_match(player_name, player)
            if score is not None:
                candidates.append((score, matched_name or "", player))

        if not candidates:
            return None, None

        candidates.sort(key=lambda item: (item[0], len(item[1]), item[2]["steam_name"].casefold()))
        best_score = candidates[0][0]
        best_group = [item for item in candidates if item[0] == best_score]
        if len(best_group) > 1:
            preview = " / ".join(item[2]["steam_name"] for item in best_group[:5])
            return None, f"匹配到多个玩家：{preview}，请改用更完整的名称或 Steam ID。"

        return best_group[0][2], None
    
    def get_player_by_steam_id(self, steam_id: str) -> Optional[Dict]:
        """
        通过Steam ID查找玩家
        :param steam_id: Steam ID
        :return: 玩家信息字典或None
        """
        conn = self.db.get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,))
            row = cur.fetchone()
            
            if row:
                result = dict(row)
                # 获取历史昵称
                cur.execute("""
                    SELECT name FROM player_names WHERE player_id = ?
                """, (result['id'],))
                name_row = cur.fetchone()
                if name_row:
                    result['name_history'] = json.loads(name_row['name'])
                else:
                    result['name_history'] = []
                return result
            return None
        finally:
            conn.close()
    
    def get_player_events(self, player_id: int, limit: int = 20) -> List[Dict]:
        """
        获取玩家相关的事件记录
        :param player_id: 玩家ID
        :param limit: 返回记录数量限制
        :return: 事件列表
        """
        conn = self.db.get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT 
                    e.*,
                    pe.role,
                    r.map_name,
                    r.played_at,
                    ed.details
                FROM events e
                JOIN player_events pe ON e.id = pe.event_id
                JOIN replays r ON e.replay_id = r.id
                LEFT JOIN event_details ed ON e.id = ed.event_id
                WHERE pe.player_id = ?
                ORDER BY r.played_at DESC
                LIMIT ?
            """, (player_id, limit))
            
            events = []
            for row in cur.fetchall():
                event_dict = dict(row)
                # 解析details JSON
                if event_dict.get('details'):
                    event_dict['details'] = json.loads(event_dict['details'])
                events.append(event_dict)
            
            return events
        finally:
            conn.close()
    
    def get_player_elo_history(self, player_id: int, limit: int = 20) -> List[Dict]:
        """
        获取玩家ELO历史记录
        :param player_id: 玩家ID
        :param limit: 返回记录数量限制
        :return: ELO历史列表
        """
        conn = self.db.get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT 
                    peh.*,
                    e.event_type,
                    e.weapon,
                    r.map_name
                FROM player_elo_history peh
                LEFT JOIN events e ON peh.event_id = e.id
                LEFT JOIN replays r ON peh.replay_id = r.id
                WHERE peh.player_id = ?
                ORDER BY peh.at_time DESC
                LIMIT ?
            """, (player_id, limit))
            
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    
    def format_player_stats(self, player_info: Dict, events: List[Dict], elo_history: List[Dict]) -> discord.Embed:
        """
        格式化玩家统计信息为Discord Embed
        :param player_info: 玩家基本信息
        :param events: 事件列表
        :param elo_history: ELO历史列表
        :return: Discord Embed对象
        """
        embed = discord.Embed(
            title=f"📊 玩家统计 - {player_info['steam_name']}",
            color=discord.Color.blue()
        )
        
        # 基本信息
        embed.add_field(
            name="🆔 基本信息",
            value=f"**Steam ID:** `{player_info['steam_id']}`\n"
                  f"**创建时间:** {player_info.get('created_at', 'N/A')}\n"
                  f"**历史昵称:** {', '.join(player_info.get('name_history', [])[:5])}",
            inline=False
        )
        
        # ELO信息
        embed.add_field(
            name="🎯 当前 ELO",
            value=f"**BVR:** {player_info['current_elo_BVR']:.2f}\n"
                  f"**BFM:** {player_info['current_elo_BFM']:.2f}\n"
                  f"**PVE:** {player_info['current_elo_PVE']:.2f}",
            inline=True
        )
        
        # 统计击杀/死亡
        kills = sum(1 for e in events if e.get('role') == 'killer')
        deaths = sum(1 for e in events if e.get('role') == 'victim')
        kd_ratio = kills / deaths if deaths > 0 else kills
        
        embed.add_field(
            name="⚔️ 战斗统计",
            value=f"**击杀:** {kills}\n"
                  f"**死亡:** {deaths}\n"
                  f"**K/D:** {kd_ratio:.2f}",
            inline=True
        )
        
        # 最近事件
        if events:
            recent_events_text = ""
            for i, event in enumerate(events[:5], 1):
                event_type = event.get('event_type', 'Unknown')
                role = event.get('role', 'Unknown')
                weapon = event.get('weapon', 'N/A')
                map_name = event.get('map_name', 'Unknown')
                
                emoji = "🔫" if role == "killer" else "💀"
                recent_events_text += f"{emoji} `{event_type}` - {weapon} @ {map_name}\n"
            
            embed.add_field(
                name="📋 最近事件 (前5条)",
                value=recent_events_text or "暂无记录",
                inline=False
            )
        
        # ELO变化趋势
        if elo_history:
            elo_trend_text = ""
            for i, record in enumerate(elo_history[:5], 1):
                elo_change = record['elo_after'] - (record['elo_before'] or record['elo_after'])
                change_emoji = "📈" if elo_change > 0 else "📉"
                elo_trend_text += f"{change_emoji} {record['elo_before']:.1f} → {record['elo_after']:.1f} ({elo_change:+.1f})\n"
            
            embed.add_field(
                name="📊 ELO变化趋势 (前5条)",
                value=elo_trend_text or "暂无记录",
                inline=False
            )
        
        embed.set_footer(text="数据来源: ezServer Flight Log Database")
        return embed


class BotCommands(commands.Cog):
    """Discord Bot 命令集合"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.stats_service = PlayerStatsService()
        
        # RAG系统初始化
        self.rag_system = RAGSystem()
        
        # AI聊天相关状态管理
        self.current_chat_user: Optional[int] = None  # 当前对话的用户ID
        self.current_chat_channel: Optional[int] = None  # 当前对话的频道ID
        self.chat_messages: List[Dict] = []  # 当前对话的消息历史
        self.last_activity_time: float = 0  # 最后活动时间
        self.chat_lock = asyncio.Lock()  # 对话锁
        
        # 启动超时检查任务
        self.check_chat_timeout.start()
    
    def check_channel_permission(self, channel_id: int, allowed_channels: List[int]) -> bool:
        """
        检查频道是否允许使用命令
        :param channel_id: 频道ID
        :return: True表示允许，False表示不允许
        """
        # 如果没有配置频道白名单，则所有频道都允许
        if not allowed_channels:
            return True
        # 检查当前频道是否在白名单中
        return channel_id in allowed_channels
    
    @app_commands.command(name="stats", description="查询玩家统计信息")
    @app_commands.describe(
        name="玩家名称",
        steam_id="玩家Steam ID"
    )
    async def stats(self, interaction: discord.Interaction, name: Optional[str] = None, steam_id: Optional[str] = None):
        """
        查询玩家统计信息
        支持两种查询方式：
        - /stats name:玩家名称
        - /stats steam_id:玩家SteamID
        """
        # 检查频道权限
        if not self.check_channel_permission(interaction.channel_id, ALLOWED_CHANNELS_BOTCOMMAND):
            await interaction.response.send_message(
                "❌ 此命令不能在当前频道使用！",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            # 查询玩家信息
            player_info = None
            query_value = None
            if name is not None:
                if steam_id is not None:
                    await interaction.followup.send(
                        "❌ 查询格式错误！请使用 `/stats name:玩家名` 或 `/stats steam_id:玩家SteamID`",
                        ephemeral=True
                    )
                    return
                else:
                    player_info, name_error = self.stats_service.resolve_player_by_name(name)
                    query_value = name
                    if name_error:
                        await interaction.followup.send(
                            f"❌ {name_error}",
                            ephemeral=True
                        )
                        return
            elif steam_id is not None:
                player_info = self.stats_service.get_player_by_steam_id(steam_id)
                query_value = steam_id
            else:
                await interaction.followup.send(
                    "❌ 查询格式错误！请使用 `/stats name:玩家名` 或 `/stats steam_id:玩家SteamID`",
                    ephemeral=True
                )
                return
            # 检查是否找到玩家
            if not player_info:
                await interaction.followup.send(
                    f"❌ 未找到玩家：`{query_value}`",
                    ephemeral=True
                )
                return
            
            # 获取玩家事件和ELO历史
            player_id = player_info['id']
            events = self.stats_service.get_player_events(player_id, limit=MAX_DISPLAY_RECORDS)
            elo_history = self.stats_service.get_player_elo_history(player_id, limit=MAX_DISPLAY_RECORDS)
            
            # 生成统计信息Embed
            embed = self.stats_service.format_player_stats(player_info, events, elo_history)
            
            # 发送结果
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ 查询出错：{str(e)}",
                ephemeral=True
            )
            print(f"[ERROR] Stats command error: {e}")
    
    @app_commands.command(name="ai", description="使用AI智能查询数据库")
    @app_commands.describe(
        query="你的自然语言查询，例如：查一下最近的BVR表现、谁在排行榜第一"
    )
    async def ai_query(self, interaction: discord.Interaction, query: str):
        """
        RAG智能查询命令
        用户输入自然语言 -> AI自动生成SQL -> 查询数据库 -> AI总结结果
        """
        # 检查频道权限
        if not self.check_channel_permission(interaction.channel_id, ALLOWED_CHANNELS_AI):
            await interaction.response.send_message(
                "❌ 此命令不能在当前频道使用！",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            user_name = interaction.user.display_name
            print(f"[RAG Query] 用户 {user_name} 查询: {query}")
            
            # 1. 使用RAG系统处理查询
            rag_result = self.rag_system.process_query(query)
            
            if not rag_result["success"]:
                await interaction.followup.send(
                    "❌ 没有找到相关数据，请尝试其他查询方式",
                    ephemeral=True
                )
                return
            
            # 2. 调用Ollama API生成自然语言总结
            try:
                # 构建AI提示词
                system_prompt = (
                    "你是ezServer游戏服务器的数据分析AI助手。"
                    "你会收到数据库查询结果，请根据这些数据生成简洁清晰的中文总结或战报。"
                    "要求：\n"
                    "1. 突出关键数据和趋势\n"
                    "2. 使用适当的emoji增强可读性\n"
                    "3. 保持专业和友好的语气\n"
                    "4. 如果是战报，要有叙事感\n"
                )
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": rag_result["llm_context"]}
                ]
                
                ai_summary = await self._call_ollama_api(messages)
                
                if not ai_summary:
                    # 如果AI总结失败，返回原始数据摘要
                    ai_summary = self._format_data_fallback(rag_result["data"], rag_result["intent"])
                
            except Exception as e:
                print(f"[ERROR] AI总结失败: {e}")
                ai_summary = self._format_data_fallback(rag_result["data"], rag_result["intent"])
            
            # 3. 构建Discord响应
            embed = discord.Embed(
                title="🤖 AI 智能查询结果",
                color=discord.Color.blue()
            )
            
            # 显示用户查询
            embed.add_field(
                name="💬 你的查询",
                value=f"`{query}`",
                inline=False
            )
            
            # 显示识别的意图
            intent_name = rag_result["intent"].get("intent", "未知")
            embed.add_field(
                name="🎯 识别意图",
                value=f"`{intent_name}`",
                inline=True
            )
            
            # 显示数据条数
            embed.add_field(
                name="📊 数据条数",
                value=f"`{len(rag_result['data'])}` 条",
                inline=True
            )
            
            # 显示AI总结（分段处理，避免超过Discord字段限制）
            summary_chunks = self._split_text(ai_summary, 1024)
            for i, chunk in enumerate(summary_chunks[:3], 1):  # 最多3段
                field_name = "🔮 AI 分析" if i == 1 else f"🔮 AI 分析 (续{i-1})"
                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )
            
            # 显示生成的SQL（可选，调试用）
            if len(rag_result["sql"]) < 500:
                embed.add_field(
                    name="🔧 生成的SQL",
                    value=f"```sql\n{rag_result['sql'][:500]}\n```",
                    inline=False
                )
            
            embed.set_footer(text=f"查询用户: {user_name} | RAG系统 v1.0")
            
            await interaction.followup.send(embed=embed)
            print(f"[RAG Query] 查询完成，返回 {len(rag_result['data'])} 条数据")
            
        except requests.exceptions.ConnectionError:
            await interaction.followup.send(
                "❌ 无法连接到AI服务，请确保Ollama服务正在运行\n"
                f"💡 Ollama地址: {OLLAMA_CONFIG['url']}",
                ephemeral=True
            )
            print(f"[ERROR] 无法连接到Ollama服务: {OLLAMA_CONFIG['url']}")
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ 查询处理出错：{str(e)}",
                ephemeral=True
            )
            print(f"[ERROR] AI query error: {e}")
            import traceback
            traceback.print_exc()
    
    def _split_text(self, text: str, max_length: int) -> List[str]:
        """
        将长文本分割成多个段落
        :param text: 原始文本
        :param max_length: 每段最大长度
        :return: 文本段落列表
        """
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        for line in text.split('\n'):
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _format_data_fallback(self, data: List[Dict], intent: Dict) -> str:
        """
        当AI总结失败时的备用格式化方法
        :param data: 查询结果数据
        :param intent: 查询意图
        :return: 格式化的文本
        """
        if not data:
            return "没有找到相关数据。"
        
        result = f"查询到 {len(data)} 条记录：\n\n"
        
        for i, row in enumerate(data[:10], 1):  # 最多显示10条
            result += f"**记录 {i}:**\n"
            for key, value in row.items():
                result += f"  • {key}: {value}\n"
            result += "\n"
        
        if len(data) > 10:
            result += f"... 还有 {len(data) - 10} 条记录未显示\n"
        
        return result

    def _build_chat_response_embed(self, message: str, ai_response: str) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 AI助手",
            color=discord.Color.green()
        )
        embed.add_field(
            name="💬 你的消息",
            value=message[:1024],
            inline=False
        )

        response_chunks = self._split_text(ai_response, 1024)
        for index, chunk in enumerate(response_chunks[:5], start=1):
            field_name = "🔮 AI回复" if index == 1 else f"🔮 AI回复 (续{index - 1})"
            embed.add_field(
                name=field_name,
                value=chunk,
                inline=False
            )

        embed.set_footer(text=f"对话轮数: {(len(self.chat_messages) - 1) // 2} | 3分钟无活动将自动结束")
        return embed
    
    @app_commands.command(name="chatwithai", description="与AI聊天")
    @app_commands.describe(
        message="要发送给AI的消息"
    )
    async def chat_with_ai(self, interaction: discord.Interaction, message: str):
        """
        与AI聊天功能
        一次只能有一个用户对话，3分钟无活动自动结束
        """
        # 检查频道权限
        if not self.check_channel_permission(interaction.channel_id, ALLOWED_CHANNELS_AI):
            await interaction.response.send_message(
                "❌ 此命令不能在当前频道使用！",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            user_id = interaction.user.id
            user_name = interaction.user.display_name
            channel_id = interaction.channel_id
            
            async with self.chat_lock:
                # 检查是否有其他用户正在对话
                if self.current_chat_user is not None and self.current_chat_user != user_id:
                    current_user = await self.bot.fetch_user(self.current_chat_user)
                    await interaction.followup.send(
                        f"❌ AI当前正在与 {current_user.display_name} 对话中，请稍后再试！\n"
                        f"💡 提示：使用 `/endaichat` 可以结束对话",
                        ephemeral=True
                    )
                    return
                
                # 初始化对话（如果是新对话）
                if self.current_chat_user != user_id:
                    self.current_chat_user = user_id
                    self.current_chat_channel = channel_id

                    self.chat_messages = [
                        {
                            "role": "system",
                            "content": (
                                "你是ezServer游戏服务器的AI助手。你可以帮助玩家查询统计数据、"
                                "回答游戏相关问题。请用简洁清晰的中文回答。"
                            )
                        }
                    ] #preset system prompt
                    print(f"[AI Chat] 开始与用户 {user_name} ({user_id}) 的新对话")
                
                # 更新活动时间
                self.last_activity_time = time.time()
                
                # 添加用户消息到历史
                self.chat_messages.append({
                    "role": "user",
                    "content": message
                }) #add user message into context
                
                # call ollama api to get ai response
                try:
                    ai_response = await self._call_ollama_api(self.chat_messages)
                    
                    if ai_response:
                        # add ai response into context
                        self.chat_messages.append({
                            "role": "assistant",
                            "content": ai_response
                        })
                        embed = self._build_chat_response_embed(message, ai_response)
                        await interaction.followup.send(embed=embed)
                        print(f"[AI Chat] User {user_name}: {message[:50]}...")
                        print(f"[AI Chat] AI: {ai_response[:50]}...")
                    else:
                        await interaction.followup.send(
                            "❌ AI未返回响应，请重试",
                            ephemeral=True
                        )
                        self.chat_messages.pop()  # 移除用户消息
                        
                except requests.exceptions.ConnectionError:
                    await interaction.followup.send(
                        "❌ 无法连接到AI服务，请确保Ollama服务正在运行\n"
                        f"💡 Ollama地址: {OLLAMA_CONFIG['url']}",
                        ephemeral=True
                    )
                    self.chat_messages.pop()
                    print(f"[ERROR] 无法连接到Ollama服务: {OLLAMA_CONFIG['url']}")
                    
                except Exception as e:
                    await interaction.followup.send(
                        f"❌ AI处理出错：{str(e)}",
                        ephemeral=True
                    )
                    self.chat_messages.pop()
                    print(f"[ERROR] AI处理错误: {e}")
                    
        except Exception as e:
            await interaction.followup.send(
                f"❌ 处理消息时出错：{str(e)}",
                ephemeral=True
            )
            print(f"[ERROR] Chat with AI error: {e}")
    
    @app_commands.command(name="endaichat", description="结束当前AI对话")
    async def end_ai_chat(self, interaction: discord.Interaction):
        """
        手动结束AI对话，清理上下文
        """
        # 检查频道权限
        if not self.check_channel_permission(interaction.channel_id, ALLOWED_CHANNELS_AI):
            await interaction.response.send_message(
                "❌ 此命令不能在当前频道使用！",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        try:
            user_id = interaction.user.id
            user_name = interaction.user.display_name
            
            async with self.chat_lock:
                # 检查是否有正在进行的对话
                if self.current_chat_user is None:
                    await interaction.followup.send(
                        "ℹ️ 当前没有进行中的AI对话",
                        ephemeral=True
                    )
                    return
                
                # 检查是否是当前对话的用户
                if self.current_chat_user != user_id:
                    current_user = await self.bot.fetch_user(self.current_chat_user)
                    await interaction.followup.send(
                        f"❌ 只有 {current_user.display_name} 可以结束当前对话",
                        ephemeral=True
                    )
                    return
                
                # 统计对话信息
                rounds = (len(self.chat_messages) - 1) // 2
                
                # 清理对话状态
                self._clear_chat_session()
                
                embed = discord.Embed(
                    title="✅ AI对话已结束",
                    description=f"与 {user_name} 的对话已结束并清理上下文",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="📊 对话统计",
                    value=f"对话轮数: {rounds}",
                    inline=False
                )
                
                await interaction.followup.send(embed=embed)
                print(f"[AI Chat] 用户 {user_name} ({user_id}) 手动结束对话，共 {rounds} 轮")
                
        except Exception as e:
            await interaction.followup.send(
                f"❌ 结束对话时出错：{str(e)}",
                ephemeral=True
            )
            print(f"[ERROR] End AI chat error: {e}")
    
    async def _call_ollama_api(self, messages: List[Dict]) -> Optional[str]:
        """
        调用Ollama API获取AI响应
        :param messages: 消息历史
        :return: AI响应文本
        """
        url = f"{OLLAMA_CONFIG['url']}/api/chat"
        payload = {
            "model": OLLAMA_CONFIG["model"],
            "messages": messages,
            "stream": False,  # 使用非流式响应以简化处理
        }
        
        try:
            # 在异步环境中运行同步请求
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    url,
                    json=payload,
                    timeout=OLLAMA_CONFIG["timeout"]
                )
            )
            
            response.raise_for_status()
            data = response.json()
            
            # 提取响应内容
            message = data.get("message", {})
            content = message.get("content", "")
            
            return content.strip() if content else None
            
        except requests.exceptions.Timeout:
            print(f"[ERROR] Ollama API 超时")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Ollama API 请求错误: {e}")
            raise
        except Exception as e:
            print(f"[ERROR] 处理Ollama响应时出错: {e}")
            return None
    
    def _clear_chat_session(self):
        """清理对话会话状态"""
        self.current_chat_user = None
        self.current_chat_channel = None
        self.chat_messages = []
        self.last_activity_time = 0
        print("[AI Chat] 对话会话已清理")
    
    @tasks.loop(seconds=30)
    async def check_chat_timeout(self):
        """定期检查对话超时（每30秒检查一次）"""
        try:
            # 如果有正在进行的对话
            if self.current_chat_user is not None and self.last_activity_time > 0:
                idle_time = time.time() - self.last_activity_time
                
                # 如果超过设定的超时时间
                if idle_time > OLLAMA_CONFIG["chat_timeout"]:
                    async with self.chat_lock:
                        if self.current_chat_user is not None:  # 再次检查
                            user_id = self.current_chat_user
                            channel_id = self.current_chat_channel
                            rounds = (len(self.chat_messages) - 1) // 2
                            
                            try:
                                # 获取用户和频道对象
                                user = await self.bot.fetch_user(user_id)
                                channel = self.bot.get_channel(channel_id)
                                
                                if channel:
                                    embed = discord.Embed(
                                        title="⏰ AI对话已自动结束",
                                        description=f"由于3分钟无活动，与 {user.display_name} 的对话已自动结束",
                                        color=discord.Color.orange()
                                    )
                                    embed.add_field(
                                        name="📊 对话统计",
                                        value=f"对话轮数: {rounds}",
                                        inline=False
                                    )
                                    await channel.send(embed=embed)
                                
                                print(f"[AI Chat] 对话超时，自动结束与用户 {user.display_name} ({user_id}) 的对话")
                                
                            except Exception as e:
                                print(f"[ERROR] 发送超时通知时出错: {e}")
                            
                            finally:
                                # 清理会话
                                self._clear_chat_session()
                                
        except Exception as e:
            print(f"[ERROR] 检查对话超时时出错: {e}")
    
    @check_chat_timeout.before_loop
    async def before_check_timeout(self):
        """等待bot准备就绪"""
        await self.bot.wait_until_ready()
    
    def cog_unload(self):
        """卸载Cog时停止任务"""
        self.check_chat_timeout.cancel()


async def setup(bot: commands.Bot):
    """
    加载Cog到Bot
    """
    await bot.add_cog(BotCommands(bot))
    print("[Bot Commands] Commands loaded successfully!")
