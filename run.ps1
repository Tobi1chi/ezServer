# 切换到脚本所在路径
Set-Location $PSScriptRoot

# 虚拟环境 Python
$VENV_PY = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

# 组合 Windows Terminal 命令
$cmds = @(
    # Tab 1：ezServer
    "new-tab --title ezServer powershell -NoExit -Command `"$VENV_PY `"`"$PSScriptRoot\ezServer.py`"`"`"",

    # Tab 2：Discord Bot
    "new-tab --title DiscordBot powershell -NoExit -Command `"$VENV_PY `"`"$PSScriptRoot\Discord_bot\bot.py`"`"`"",

    # Tab 3：Telnet
    "new-tab --title Telnet powershell -NoExit -Command `"telnet 127.0.0.1 23232`"",

    # ✅ Tab 4：Ollama（用了绝对路径 + & 调用）
    "new-tab --title Ollama powershell -NoExit -Command `"& 'D:\ollama\ollama-windows-amd64\ollama.exe' serve`""
)

# 用分号拼成一条 wt 命令
$full = $cmds -join " ; "

# 可选：先打印出来看看实际命令
Write-Host "wt.exe -w 0 $full`n"

# 启动 Windows Terminal
Start-Process wt.exe -ArgumentList @("-w", "0", $full)
