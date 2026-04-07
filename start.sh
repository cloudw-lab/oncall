#!/bin/bash

# Oncall 排班平台启动脚本

echo "🚀 启动 Oncall 排班平台..."

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3.13 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📦 安装依赖..."
pip install -r requirements.txt -q

# 初始化数据库
echo "🗄️  初始化数据库..."
python init_data.py

# 启动服务
echo "🌐 启动服务..."
echo "访问 http://localhost:8000/docs 查看 API 文档"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
