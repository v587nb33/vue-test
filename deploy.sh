#!/bin/bash

echo "开始部署车间停机管理系统..."

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo "错误：Docker未安装，请先安装Docker"
    exit 1
fi

# 检查Docker Compose是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose未安装，尝试安装..."
    # 对于Ubuntu系统
    if [ -f /etc/debian_version ]; then
        apt-get update
        apt-get install -y docker-compose
    fi
fi

# 创建必要的目录
mkdir -p data/mysql

# 停止并移除现有容器
echo "清理现有容器..."
docker-compose down

# 构建并启动服务
echo "构建和启动服务..."
docker-compose up --build -d

# 等待服务启动
echo "等待服务启动..."
sleep 30

# 检查服务状态
echo "检查服务状态..."
docker-compose ps

# 检查后端服务日志
echo "后端服务日志："
docker-compose logs backend --tail=20

# 检查前端服务状态
echo "前端服务状态："
curl -s http://localhost:80 | grep -o "<title>[^<]*</title>" || echo "无法连接到前端服务"

echo "部署完成！"
echo "访问地址：http://服务器公网IP"
echo "WebSocket连接：ws://服务器公网IP/ws"
echo ""
echo "MySQL信息："
echo "- 主机：mysql (容器网络)"
echo "- 端口：3306"
echo "- 数据库：workshop_db"
echo "- 用户：workshop_user"
echo "- 密码：workshop_password"