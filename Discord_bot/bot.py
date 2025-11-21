"""
ezServer Discord Bot 主程序
玩家统计查询和AI聊天功能
"""

import os
import sys
from pathlib import Path
import discord
from discord.ext import commands
import asyncio

# 添加父目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 从文件读取Token
TOKEN_FILE = Path(__file__).parent.parent / "temp" / "token.txt"

try:
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        BOT_TOKEN = f.read().strip()
except FileNotFoundError:
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    print(f"[警告] 未找到token文件: {TOKEN_FILE}")
except Exception as e:
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    print(f"[警告] 读取token文件失败: {e}")

# Bot配置
BOT_CONFIG = {
    "token": BOT_TOKEN,
    "command_prefix": "!",  # 传统命令前缀（主要用斜杠命令）
    "activity_name": "ezServer",  # Bot显示的活动
    "activity_type": discord.ActivityType.watching,  # 活动类型
}

# 创建Bot实例
intents = discord.Intents.default()
intents.message_content = True  # 启用消息内容意图
intents.members = True  # 启用成员意图（用于获取用户信息）

bot = commands.Bot(
    command_prefix=BOT_CONFIG["command_prefix"],
    intents=intents,
    help_command=None,  # 禁用默认的help命令
)


@bot.event
async def on_ready():
    """Bot启动完成事件"""
    print("=" * 50)
    print(f"✅ Bot已成功登录")
    print(f"📛 Bot名称: {bot.user.name}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print(f"🌐 已连接到 {len(bot.guilds)} 个服务器")
    print("=" * 50)
    
    # 设置Bot状态
    activity = discord.Activity(
        type=BOT_CONFIG["activity_type"],
        name=BOT_CONFIG["activity_name"]
    )
    await bot.change_presence(activity=activity, status=discord.Status.online)
    
    # 同步斜杠命令
    try:
        print("🔄 正在同步斜杠命令...")
        synced = await bot.tree.sync()
        print(f"✅ 成功同步 {len(synced)} 个斜杠命令")
        
        # 显示已同步的命令
        for cmd in synced:
            print(f"   - /{cmd.name}: {cmd.description}")
        
    except Exception as e:
        print(f"❌ 同步命令失败: {e}")
    
    print("=" * 50)
    print("🤖 Bot已准备就绪，等待命令...")
    print("=" * 50)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Bot加入新服务器事件"""
    print(f"📥 Bot已加入新服务器: {guild.name} (ID: {guild.id})")
    print(f"   成员数: {guild.member_count}")
    
    # 尝试向服务器发送欢迎消息
    try:
        # 找到第一个可以发送消息的频道
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="👋 感谢邀请 ezServer Bot！",
                    description="我是ezServer的助手，可以帮助你查询玩家统计和与AI聊天。",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="📋 可用命令",
                    value=(
                        "• `/stats NAME:玩家名` - 通过名称查询玩家\n"
                        "• `/stats ID:Steam_ID` - 通过Steam ID查询玩家\n"
                        "• `/chatwithAI 消息` - 与AI助手对话\n"
                        "• `/endAIchat` - 结束AI对话"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="💡 提示",
                    value="使用 `/` 可以查看所有可用的斜杠命令",
                    inline=False
                )
                embed.set_footer(text="ezServer Bot | Powered by Discord.py")
                
                await channel.send(embed=embed)
                break
    except Exception as e:
        print(f"⚠️ 无法发送欢迎消息: {e}")


@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Bot被移出服务器事件"""
    print(f"📤 Bot已被移出服务器: {guild.name} (ID: {guild.id})")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """传统命令错误处理"""
    if isinstance(error, commands.CommandNotFound):
        return  # 忽略未找到命令的错误
    
    print(f"❌ 命令错误: {error}")


@bot.event
async def on_application_command_error(interaction: discord.Interaction, error: Exception):
    """斜杠命令错误处理"""
    print(f"❌ 斜杠命令错误: {error}")
    
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ 命令执行出错：{str(error)}",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ 命令执行出错：{str(error)}",
                ephemeral=True
            )
    except Exception as e:
        print(f"❌ 发送错误消息失败: {e}")


@bot.command(name="help", aliases=["帮助"])
async def help_command(ctx: commands.Context):
    """显示帮助信息（传统命令）"""
    embed = discord.Embed(
        title="🤖 ezServer Bot 帮助",
        description="以下是所有可用的命令",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📊 玩家统计",
        value=(
            "`/stats NAME:玩家名` - 通过玩家名称查询\n"
            "`/stats ID:Steam_ID` - 通过Steam ID查询\n"
            "例如：`/stats NAME:Tobiichi` 或 `/stats ID:76561198012345678`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🤖 AI聊天",
        value=(
            "`/chatwithAI 消息` - 与AI助手对话\n"
            "`/endAIchat` - 结束当前AI对话\n"
            "注意：同时只能有一个用户与AI对话，3分钟无活动自动结束"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💡 使用提示",
        value=(
            "• 斜杠命令输入 `/` 后会自动显示提示\n"
            "• AI对话一次只能一个用户使用\n"
            "• 查询结果会显示最近20条记录"
        ),
        inline=False
    )
    
    embed.set_footer(text="ezServer Bot | 输入 / 查看所有命令")
    
    await ctx.send(embed=embed)


@bot.command(name="ping")
async def ping_command(ctx: commands.Context):
    """测试Bot延迟"""
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"延迟: **{latency}ms**",
        color=discord.Color.green() if latency < 200 else discord.Color.orange()
    )
    
    await ctx.send(embed=embed)


@bot.command(name="info", aliases=["信息"])
async def info_command(ctx: commands.Context):
    """显示Bot信息"""
    embed = discord.Embed(
        title="ℹ️ Bot信息",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📛 Bot名称",
        value=bot.user.name,
        inline=True
    )
    
    embed.add_field(
        name="🆔 Bot ID",
        value=bot.user.id,
        inline=True
    )
    
    embed.add_field(
        name="🌐 服务器数量",
        value=len(bot.guilds),
        inline=True
    )
    
    embed.add_field(
        name="👥 用户数量",
        value=sum(guild.member_count for guild in bot.guilds),
        inline=True
    )
    
    embed.add_field(
        name="🏓 延迟",
        value=f"{round(bot.latency * 1000)}ms",
        inline=True
    )
    
    embed.add_field(
        name="🐍 Python版本",
        value=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        inline=True
    )
    
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    embed.set_footer(text="ezServer Bot | Powered by Discord.py")
    
    await ctx.send(embed=embed)


async def load_extensions():
    """加载扩展（Cogs）"""
    try:
        print("🔄 正在加载命令模块...")
        await bot.load_extension("Discord_bot.bot_commands")
        print("✅ 命令模块加载成功")
    except Exception as e:
        print(f"❌ 加载命令模块失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def main():
    """主函数"""
    # 检查TOKEN
    if BOT_CONFIG["token"] == "YOUR_BOT_TOKEN_HERE":
        print("=" * 50)
        print("❌ 错误：未设置Discord Bot Token！")
        print("=" * 50)
        print(f"请在以下文件中设置Token：")
        print(f"  文件路径: {TOKEN_FILE}")
        print(f"\n步骤：")
        print(f"  1. 创建 temp 文件夹（如果不存在）")
        print(f"  2. 在 temp 文件夹中创建 token.txt 文件")
        print(f"  3. 将你的Discord Bot Token粘贴到文件中")
        print(f"  4. 保存文件后重新运行Bot")
        print("\n如何获取Token：")
        print("  1. 访问 https://discord.com/developers/applications")
        print("  2. 创建或选择你的应用")
        print("  3. 进入 Bot 标签页")
        print("  4. 点击 'Reset Token' 复制新Token")
        print("=" * 50)
        return
    
    async with bot:
        # 加载扩展
        await load_extensions()
        
        # 启动Bot
        print("🚀 正在启动Bot...")
        try:
            await bot.start(BOT_CONFIG["token"])
        except discord.LoginFailure:
            print("=" * 50)
            print("❌ 登录失败：Token无效！")
            print("=" * 50)
            print("请检查你的Discord Bot Token是否正确")
        except Exception as e:
            print(f"❌ Bot启动失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    try:
        # 运行Bot
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ 收到中断信号，正在关闭Bot...")
    except Exception as e:
        print(f"❌ 程序异常退出: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("👋 Bot已关闭")

