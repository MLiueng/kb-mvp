#!/usr/bin/env bash
# ============================================================
#  知识库系统 MVP - macOS/Linux 一键启动脚本
# ============================================================
set -e

cd "$(dirname "$0")"

echo ""
echo " [1/6] 检测 Python ..."
if command -v python3 >/dev/null 2>&1; then
    PY_SYS="python3"
elif command -v python >/dev/null 2>&1; then
    PY_SYS="python"
else
    echo " [错误] 未检测到 Python，请先安装 Python 3.10+"
    echo " 下载地址: https://www.python.org/downloads/"
    exit 1
fi
echo " 已找到 Python: $PY_SYS"

echo ""
echo " [2/6] 检测/创建虚拟环境 .venv ..."
if [ ! -f ".venv/bin/python" ]; then
    $PY_SYS -m venv .venv
    echo " 虚拟环境已创建"
else
    echo " 虚拟环境已存在"
fi
PY=".venv/bin/python"

echo ""
echo " [3/6] 升级 pip ..."
$PY -m pip install --upgrade pip -q

echo ""
echo " [4/6] 安装依赖 ..."
$PY -m pip install -r requirements.txt -q
echo " 依赖安装完成"

echo ""
echo " [5/6] 检测配置文件 .env ..."
if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo " 已从 .env.example 创建 .env"
    echo " [提示] 请编辑 .env 填入 DASHSCOPE_API_KEY 后重新运行本脚本"
    echo "        获取地址: https://bailian.console.aliyun.com/"
    echo ""
    ${EDITOR:-vi} ".env"
else
    echo " .env 已存在"
fi

echo ""
echo " [6/6] 启动服务 ..."
echo ""
echo " =========================================================="
echo "   知识库系统 MVP 启动中..."
echo "   访问地址: http://127.0.0.1:8000"
echo "   API 文档: http://127.0.0.1:8000/docs"
echo " =========================================================="
echo ""
exec $PY -m app.main
