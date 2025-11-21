# 设置控制台编码为 UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 切换到脚本所在目录
Set-Location $PSScriptRoot

# 运行 Python 脚本
Start-Process py "ezServer.py"
Start-Process telnet "127.0.0.1 23232"

#change directory to ollama server
Set-Location -Path "D:\ollama\ollama-windows-amd64"

#start ollama server
Start-Process ./ollama.exe "serve"

# 等待用户按键
Write-Host "`n按任意键继续..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

