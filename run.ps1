# 设置控制台编码为 UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 切换到脚本所在目录
Set-Location $PSScriptRoot

# 运行 Python 脚本
python ezServer.py

# 等待用户按键
Write-Host "`n按任意键继续..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

