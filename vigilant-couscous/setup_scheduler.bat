@echo off
chcp 65001 >nul
title 自进化交易系统 - 定时任务安装

echo ============================================================
echo   自进化交易系统 - 每7天自动升级迭代
echo ============================================================
echo.

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "EVOLVE_SCRIPT=%PROJECT_DIR%\weekly_evolve.py"
set "TASK_NAME=SelfEvolveTrading_WeeklyUpdate"

echo 项目目录: %PROJECT_DIR%
echo Python: %PYTHON_EXE%
echo.

:: 检查 Python 是否存在
if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到虚拟环境 Python，请先运行安装脚本
    pause
    exit /b 1
)

:: 删除旧任务（如果存在）
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

:: 创建新的计划任务 - 每7天运行一次
:: 首次运行在 2026-10-14 02:00，之后每7天运行
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "cmd /c cd /d \"%PROJECT_DIR%\" && \"%PYTHON_EXE%\" \"%EVOLVE_SCRIPT%\" >> \"%PROJECT_DIR%\reports\weekly_log.txt\" 2>&1" ^
    /sc weekly ^
    /d MON ^
    /st 02:00 ^
    /ru SYSTEM ^
    /f

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo   [成功] 定时任务已创建！
    echo   任务名称: %TASK_NAME%
    echo   运行周期: 每周一 02:00
    echo   日志文件: reports\weekly_log.txt
    echo ============================================================
    echo.
    echo 查看任务: schtasks /query /tn "%TASK_NAME%"
    echo 手动运行: schtasks /run /tn "%TASK_NAME%"
    echo 删除任务: schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo [失败] 任务创建失败，尝试以当前用户权限创建...
    
    schtasks /create ^
        /tn "%TASK_NAME%" ^
        /tr "cmd /c cd /d \"%PROJECT_DIR%\" && \"%PYTHON_EXE%\" \"%EVOLVE_SCRIPT%\" >> \"%PROJECT_DIR%\reports\weekly_log.txt\" 2>&1" ^
        /sc weekly ^
        /d MON ^
        /st 02:00 ^
        /f
    
    if %errorlevel% equ 0 (
        echo [成功] 以当前用户权限创建成功
    ) else (
        echo [失败] 请以管理员身份运行此脚本
    )
)

echo.
pause
