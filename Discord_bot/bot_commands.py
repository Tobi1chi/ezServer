"""
Discord Bot 命令处理模块
实现玩家统计查询和AI聊天功能
"""

import sys
from pathlib import Path
import sqlite3
import json
from typing import Optional, Dict, List, Union
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


class PlayerStatsService:
    """玩家统计查询服务"""
    
    def __init__(self, db_path=FLIGHTLOG_DB_PATH):
        self.db = flightlogDB(db_path)
    
    def get_player_by_name(self, player_name: str) -> Optional[Dict]:
        """
        通过玩家名称查找玩家
        :param player_name: 玩家名称
        :return: 玩家信息字典或None
        """
        conn = self.db.get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        try:
            # 在player_names表中搜索包含该名称的记录
            cur.execute("""
                SELECT p.*, pn.name as name_history
                FROM players p
                JOIN player_names pn ON p.id = pn.player_id
                WHERE pn.name LIKE ?
            """, (f'%{player_name}%',))
            
            row = cur.fetchone()
            if row:
                result = dict(row)
                # 解析name_history JSON
                if result.get('name_history'):
                    result['name_history'] = json.loads(result['name_history'])
                return result
            return None
        finally:
            conn.close()
    
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
        Name="玩家名称",
        Steam_ID="玩家Steam ID"
    )
    async def stats(self, interaction: discord.Interaction, Name: Optional[str] = None, Steam_ID: Optional[str] = None):
        """
        查询玩家统计信息
        支持两种查询方式：
        - /stats NAME:玩家名称
        - /stats ID:Steam_ID
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
            if Name is not None:
                if Steam_ID is not None:
                    await interaction.followup.send(
                        "❌ 查询格式错误！请使用 `/stats NAME:玩家名` 或 `/stats ID:Steam_ID`",
                        ephemeral=True
                    )
                    return
                else:
                    player_info = self.stats_service.get_player_by_name(Name)
                    query_value = Name
            elif Steam_ID is not None:
                player_info = self.stats_service.get_player_by_steam_id(Steam_ID)
                query_value = Steam_ID
            else:
                await interaction.followup.send(
                    "❌ 查询格式错误！请使用 `/stats NAME:玩家名` 或 `/stats ID:Steam_ID`",
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
            events = self.stats_service.get_player_events(player_id, limit=20)
            elo_history = self.stats_service.get_player_elo_history(player_id, limit=20)
            
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
                        
                        # create response embed
                        embed = discord.Embed(
                            title="🤖 AI助手",
                            color=discord.Color.green()
                        )
                        embed.add_field(
                            name="💬 你的消息",
                            value=message[:1024],  # discord field limit
                            inline=False
                        )
                        if len(ai_response) > 1024:
                            embed.add_field(
                                name="🔮 AI回复",
                                value=ai_response[:1024],  # discord field limit
                                inline=False
                            )
                            embed.add_field(
                                name="🔮 AI回复",
                                value=ai_response[1024:2048],  # discord field limit
                                inline=False
                            )
                        
                        embed.set_footer(text=f"对话轮数: {(len(self.chat_messages) - 1) // 2} | 3分钟无活动将自动结束")
                        
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

