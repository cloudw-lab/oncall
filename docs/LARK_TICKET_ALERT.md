# Nightingale 告警 Ticket 式 Lark 通知

## 概述

本功能实现了从 Nightingale (n9e) 接收的告警信息，经过提取和格式化，以 Ticket 式的飞书卡片展示。卡片包含了关键的告警信息，类似于 IT 服务管理系统的报障单格式。

## 功能特性

### 提取的关键信息

从 n9e 的 POST 数据中提取以下信息：

1. **ID** - 告警事件 ID
2. **名称** - 规则名称 (rule_name)
3. **CTI** - 关键信息标签，用于路由到对应的排班
4. **级别** - 告警严重程度 (critical, warning, info, debug)
5. **集群** - Prometheus 集群标识 (cluster)
6. **状态** - 告警状态 (triggered, resolved)
7. **触发时间** - 告警触发时间戳
8. **目标** - 监控目标标识 (target_ident)
9. **Prometheus QL** - 完整的查询语句
10. **摘要** - 告警摘要信息

### 卡片样式

卡片根据严重程度采用不同的颜色：
- **Critical** → 红色
- **Warning** → 橙色
- **Info** → 蓝色
- **Debug** → 灰色

## 工作流程

```
Nightingale Alert (POST)
    ↓
Extract Key Information
    ↓
Query Schedule by CTI
    ↓
Create/Update Incident
    ↓
Send Lark Ticket Card ← 新功能
```

## 配置步骤

### 1. 配置 Lark 应用凭证

```bash
curl -X POST http://localhost:8000/api/v1/lark-app-config \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "app_id": "your_app_id",
    "app_secret": "your_app_secret"
  }'
```

### 2. 创建告警接入源

```bash
curl -X POST http://localhost:8000/integrations \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "n9e-alert-source",
    "name": "Nightingale Alert Source",
    "description": "Alert source from Nightingale",
    "schedule_id": 1,
    "channel": "email",
    "config": {
      "lark_enabled": true,
      "lark_chat_id": "oc_xxxxxxxxxxxx",
      "lark_ticket_enabled": true,
      "cti_values": ["your-cti-value"]
    },
    "is_active": true
  }'
```

### 3. 配置 Nightingale Webhook

在 Nightingale 管理后台，配置 Webhook 地址：

```
URL: http://<your-server>/open-api/events
Authentication: Basic Auth
Username: <webhook_username>
Password: <webhook_password>
```

获取 Webhook 凭证：

```bash
curl -X POST http://localhost:8000/api/v1/nightingale-webhook-auth/generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "n9e_webhook"
  }'
```

## API 端点

### 发送 Nightingale 告警

```
POST /open-api/events
Authorization: Basic Auth (username:password)
Content-Type: application/json
```

#### 请求体示例

```json
{
  "id": "alert_12345",
  "rule_name": "Redis Memory Usage High",
  "cti": "redis-prod",
  "severity": "critical",
  "cluster": "prometheus-local",
  "prom_ql": "redis_memory_usage_bytes / 1024 / 1024 > 512",
  "target_ident": "redis-node-01.internal",
  "title": "[CRITICAL] Redis Memory Usage Exceeded",
  "summary": "Redis memory usage has exceeded threshold",
  "trigger_time": "2024-04-03T10:30:45+08:00",
  "status": "triggered"
}
```

#### 支持的字段映射

| 字段 | 支持的键 | 说明 |
|------|---------|------|
| 告警 ID | `id`, `alert_id`, `event_id` | 唯一标识 |
| 规则名 | `rule_name`, `ruleName` | 告警规则名称 |
| CTI | `cti`, `CTI` | 关键信息标签 |
| 严重程度 | `severity`, `level`, `priority` | critical/warning/info/debug |
| 状态 | `status`, `event_status` | triggered/resolved |
| 集群 | `cluster` | Prometheus 集群 |
| 查询语句 | `prom_ql`, `ql` | Prometheus QL |
| 目标 | `target_ident`, `target` | 监控对象 |
| 标题 | `title`, `rule_name`, `ruleName` | 告警标题 |
| 摘要 | `summary`, `annotations.summary` | 详细描述 |
| 时间戳 | `trigger_time`, `first_trigger_time`, `timestamp`, `ts` | Unix timestamp (毫秒/秒) |

#### 返回示例

```json
{
  "deduped": false,
  "incident": {
    "id": 123,
    "source_id": 456,
    "schedule_id": 1,
    "fingerprint": "redis-memory-high",
    "title": "[CRITICAL] Redis Memory Usage Exceeded",
    "severity": "critical",
    "status": "open",
    "summary": "Redis memory usage has exceeded threshold",
    "first_event_at": "2024-04-03T10:30:45",
    "latest_event_at": "2024-04-03T10:30:45"
  },
  "event": {
    "id": 789,
    "incident_id": 123,
    "severity": "critical",
    "event_status": "triggered"
  },
  "notifications": []
}
```

## 集成配置详解

### 核心配置

```json
{
  "config": {
    "lark_enabled": true,                    // 启用 Lark 通知
    "lark_chat_id": "oc_xxxxxxxxxxxx",       // Lark 群组 ID
    "lark_ticket_enabled": true,             // 启用 Ticket 式卡片（新功能）
    "cti_values": ["redis-prod", "mysql-prod"], // CTI 匹配值列表
    "ack_escalation_enabled": true,          // 启用未确认升级
    "ack_escalation_after_minutes": 15,      // 未确认多少分钟后升级
    "escalation_enabled": true,              // 启用自动升级
    "escalation_after_minutes": 60,          // 多少分钟后升级到电话
    "important_direct_phone": true           // Critical 告警直接电话
  }
}
```

## 工作示例

### 场景：Redis 内存告警

1. **Nightingale 检测到 Redis 内存使用率过高**

2. **POST 请求发送到系统**：
```json
{
  "id": "n9e-alert-20240403-001",
  "rule_name": "Redis Memory Usage High",
  "cti": "redis-prod",
  "severity": "critical",
  "cluster": "prometheus-local",
  "prom_ql": "redis_memory_usage_bytes / 1024 / 1024 > 512",
  "target_ident": "redis-prod.internal:6379",
  "title": "[CRITICAL] Redis Memory Usage Exceeded",
  "summary": "Redis memory: 578MB (threshold: 512MB)",
  "trigger_time": "2024-04-03T10:30:45+08:00"
}
```

3. **系统处理流程**：
   - 提取 CTI = "redis-prod"
   - 查询对应排班表
   - 创建 Incident
   - 发送 Lark Ticket 卡片

4. **Lark 群组收到的卡片**（类似截图中的格式）：
   ```
   ┌─────────────────────────────────────────┐
   │ 🔴 [CRITICAL] Redis Memory Usage...     │
   ├─────────────────────────────────────────┤
   │ ID:           n9e-alert-20240403-001   │
   │ 名称:         Redis Memory Usage High   │
   │ CTI:          redis-prod               │
   │ 级别:         CRITICAL                 │
   │ 集群:         prometheus-local         │
   │ 状态:         triggered                │
   │ 触发时间:     2024-04-03 10:30:45      │
   │ 目标:         redis-prod.internal:6379 │
   │ Prom QL:      redis_memory_usage_bytes │
   │               / 1024 / 1024 > 512      │
   │ 摘要:         Redis memory: 578MB      │
   │               (threshold: 512MB)       │
   └─────────────────────────────────────────┘
   ```

## 故障排查

### 卡片未收到

1. **检查 Lark 配置**：
   ```bash
   curl http://localhost:8000/api/v1/lark-app-config \
     -H "Authorization: Bearer <token>"
   ```

2. **检查日志**：
   ```bash
   tail -f logs/lark.log
   ```

3. **验证聊天 ID**：
   - 确保机器人已加入指定群组
   - 使用正确的群组 ID (以 oc_ 开头)

### 告警未创建

1. **检查 CTI 配置**：
   - Nightingale 发送的 `cti` 字段必须匹配 `cti_values` 中的一个值

2. **检查权限**：
   - Nightingale webhook 凭证是否有效
   - 检查是否启用了 webhook 认证

## 代码位置

- **通知服务**：`app/services/notification_service.py` (方法: `send_nightingale_alert_ticket`)
- **告警服务**：`app/services/alert_service.py` (方法: `ingest_nightingale_event`)
- **API 路由**：`app/routers/alerts.py` (端点: `/open-api/events`)

## 日志记录

所有 Lark 操作都会记录到 `logs/lark.log`，包括：
- Token 获取
- 卡片发送
- 错误信息

## 限制和注意事项

1. **Lark 应用限额**：确保应用不超过 API 速率限制
2. **群组成员**：机器人必须是目标群组的成员
3. **卡片大小**：极长的 Prometheus QL 可能被截断（Lark 卡片限制）
4. **时间戳格式**：支持 Unix 时间戳 (秒/毫秒) 或 ISO 8601 格式

## 扩展功能建议

1. 添加卡片中的操作按钮（认领、关闭、升级）
2. 支持自定义卡片模板
3. 添加告警趋势图表
4. 集成告警关联分析

