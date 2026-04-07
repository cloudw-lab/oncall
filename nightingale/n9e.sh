#!/usr/bin/env zsh
# 本地 Nightingale 快捷管理脚本
# 使用方法：./n9e.sh [up|down|logs|status|restart]

DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

case "${1:-status}" in
  up)
    echo "🚀 启动 Nightingale..."
    $DOCKER compose -f "$COMPOSE_FILE" up -d
    echo ""
    echo "🌐 Web UI: http://localhost:17000"
    echo "📈 Prometheus: http://localhost:19090"
    echo "👤 默认账号: root / root.2020"
    ;;
  down)
    echo "🛑 停止 Nightingale..."
    $DOCKER compose -f "$COMPOSE_FILE" down
    ;;
  restart)
    echo "🔄 重启 Nightingale..."
    $DOCKER compose -f "$COMPOSE_FILE" restart
    ;;
  logs)
    $DOCKER logs -f n9e
    ;;
  status)
    echo "=== 容器状态 ==="
    $DOCKER compose -f "$COMPOSE_FILE" ps
    echo ""
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:17000/api/n9e/status 2>/dev/null)
    if [ "$STATUS" = "200" ]; then
      echo "✅ Nightingale Web UI 正常: http://localhost:17000"
      echo "👤 默认账号: root / root.2020"
    else
      echo "⚠️  Web UI 未就绪 (HTTP $STATUS)"
    fi
    PROM_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:19090/-/ready 2>/dev/null)
    if [ "$PROM_STATUS" = "200" ]; then
      echo "✅ Prometheus 正常: http://localhost:19090"
    else
      echo "⚠️  Prometheus 未就绪 (HTTP $PROM_STATUS)"
    fi
    ;;
  *)
    echo "用法: $0 [up|down|logs|status|restart]"
    ;;
esac

