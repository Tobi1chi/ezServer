@echo off
chcp 65001 >nul
echo ========================================
echo ezServer Discord Bot 启动脚本
echo ========================================
echo.

REM 检查token文件是否存在
if not exist "..\temp\token.txt" (
    echo [警告] 未找到token文件: ..\temp\token.txt
    echo.
    echo 正在创建token文件...
    
    REM 创建temp目录
    if not exist "..\temp" mkdir "..\temp"
    
    echo 请输入你的Discord Bot Token:
    set /p USER_TOKEN="Token: "
    echo %USER_TOKEN% > "..\temp\token.txt"
    echo.
    echo [成功] Token已保存到 ..\temp\token.txt
    echo.
)

echo [信息] 正在启动Bot...
echo.

python bot.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] Bot启动失败！
    echo.
    pause
)

