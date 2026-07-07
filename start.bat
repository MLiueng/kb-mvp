@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  知识库系统 MVP - Windows 一键启动脚本
REM ============================================================

cd /d "%~dp0"

echo.
echo  [1/6] 检测 Python ...
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where python3 >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python3"
    ) else (
        echo  [错误] 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH
        echo  下载地址: https://www.python.org/downloads/
        pause
        exit /b 1
    )
)
echo  已找到 Python: %PY%

echo.
echo  [2/6] 检测/创建虚拟环境 .venv ...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if %errorlevel% neq 0 (
        echo  [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo  虚拟环境已创建
) else (
    echo  虚拟环境已存在
)
set "PY=.venv\Scripts\python.exe"

echo.
echo  [3/6] 升级 pip ...
%PY% -m pip install --upgrade pip -q

echo.
echo  [4/6] 安装依赖 ...
%PY% -m pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo  [错误] 依赖安装失败，请检查网络或手动执行: pip install -r requirements.txt
    pause
    exit /b 1
)
echo  依赖安装完成

echo.
echo  [5/6] 检测配置文件 .env ...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo  已从 .env.example 创建 .env
    echo  [提示] 请编辑 .env 填入 DASHSCOPE_API_KEY 后重新运行本脚本
    echo         获取地址: https://bailian.console.aliyun.com/
    notepad ".env"
    pause
) else (
    echo  .env 已存在
)

echo.
echo  [6/6] 启动服务 ...
echo.
echo  ==========================================================
echo    知识库系统 MVP 启动中...
echo    访问地址: http://127.0.0.1:8000
echo    API 文档: http://127.0.0.1:8000/docs
echo  ==========================================================
echo.
%PY% -m app.main

if %errorlevel% neq 0 (
    echo.
    echo  [错误] 服务启动失败
    pause
)

endlocal
