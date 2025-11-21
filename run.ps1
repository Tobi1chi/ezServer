# 设置控制台编码为 UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 切换到脚本所在目录
Set-Location $PSScriptRoot

# Using virtual environment
$VENV_PY = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

# Run ezServer.py
Start-Process $VENV_PY "ezServer.py"
Start-Process $VENV_PY "Discord_bot\bot.py"
# Run telnet
Start-Process "telnet" "127.0.0.1 23232"

# Switch to ollama
Set-Location -Path "D:\ollama\ollama-windows-amd64"

Start-Process "./ollama.exe" "serve"

Write-Host "`nPress any key to continue..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")


