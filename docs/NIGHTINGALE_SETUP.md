# Nightingale 回调接入说明（CTI 路由）

本文说明如何把 Nightingale 告警通过 Webhook 接入当前 Oncall 系统，并根据规则标签里的 `cti` 自动路由到对应值班表的 Lark 群。

## 1. 前置条件

- Oncall 服务已启动，可访问 `/open-api/events`
- 已在 Oncall 中创建排班表，并完成排班成员配置
- 已在 Oncall 中配置该排班表的集成信息（至少包含 `cti_values`，可选 `lark_chat_id`）

> 当前已支持由 Oncall 应用自身生成 Nightingale 回调 Basic Auth（无需依赖 Nginx）。

## 2. Oncall 侧配置（关键）

在“排班 -> 接入配置”里，为每个排班设置：

- `lark_enabled`: 是否启用飞书群通知
- `lark_chat_id`: 对应排班的群 chat_id
- `cti_values`: 该排班负责的 CTI 标签值（可多个）

> 新建排班表时，系统会自动生成一条默认 CTI（如 `cti-xxxxxx`），你可以在排班详情页和“接入配置”页直接看到，并按需修改。

示例（API）：

```bash
curl -X POST http://localhost:8000/api/v1/schedules/1/integrations \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "schedule-1-default",
    "source_name": "SRE Core 默认接入",
    "lark_enabled": true,
    "lark_chat_id": "oc_xxx",
    "cti_values": ["sre-core", "cl4a7q08btf87vmocjgg"]
  }'
```

## 3. Nightingale 通知设置

在 Nightingale `告警通知 -> 通知设置 -> 回调地址` 中配置：

- URL: `https://<your-domain>/open-api/events`
- Method: `POST`
- Header: `Content-Type: application/json`
- 超时: 建议 `5s-10s`

## 3.1 由 Oncall 生成 Nightingale Basic Auth（推荐）

1) 管理员获取当前状态：

```bash
curl -X GET http://localhost:8000/api/v1/nightingale-webhook-auth \
  -H "Authorization: Bearer <access_token>"
```

2) 管理员生成/轮换账号密码（会自动启用）：

```bash
curl -X POST http://localhost:8000/api/v1/nightingale-webhook-auth/generate \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "root"}'
```

返回示例：

```json
{
  "enabled": true,
  "username": "root",
  "has_password": true,
  "updated_at": "2026-04-03T12:00:00",
  "password": "<仅本次返回明文>"
}
```

3) 如果需要临时关闭鉴权：

```bash
curl -X POST http://localhost:8000/api/v1/nightingale-webhook-auth/disable \
  -H "Authorization: Bearer <access_token>"
```

## 3.2 在 Nightingale 页面填写

在 Nightingale `告警通知 -> 通知设置 -> 回调地址` 中配置：

- URL: `https://<your-domain>/open-api/events`
- Method: `POST`
- Header: `Content-Type: application/json`
- 用户名: 使用 Oncall 生成的 `username`
- 密码: 使用 Oncall 生成返回的 `password`
- 超时: 建议 `5s-10s`

## 4. CTI 提取规则

Oncall 解析 CTI 的优先级：

1. `payload.cti`
2. `payload.tags`（支持 `cti=xxx`）
3. `payload.labels.cti`

命中规则：

- `cti` 命中某个排班的 `cti_values` -> 路由到该排班
- 未命中任何排班 -> 返回 `400`
- 命中多个排班（冲突）-> 返回 `409`

建议：同一个 `cti` 只配置在一个排班中，避免冲突。

## 5. 回调 JSON 示例

### 5.1 触发事件（labels.cti）

```json
{
  "event_id": "evt-core-001",
  "rule_name": "core api error high",
  "severity": "critical",
  "status": "triggered",
  "labels": {
    "cti": "sre-core",
    "instance": "api-01"
  },
  "summary": "5xx ratio > 20%"
}
```

### 5.2 触发事件（tags 形式）

```json
{
  "event_id": "evt-trade-001",
  "rule_name": "trade latency high",
  "severity": "warning",
  "status": "triggered",
  "tags": ["cti=trade-engine", "cluster=prod"],
  "summary": "p99 > 500ms"
}
```

### 5.3 恢复事件

`status` 可使用 `resolved/recover/recovered/ok`，会被识别为恢复。

## 6. 联调命令

```bash
curl -X POST http://localhost:8000/open-api/events \
  -u '<username>:<password>' \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-debug-001",
    "rule_name": "cert expiring",
    "severity": "critical",
    "status": "triggered",
    "labels": {"cti": "sre-core"},
    "summary": "ssl cert will expire in 7 days"
  }'
```

成功后可在以下位置观察：

- 告警列表：`/incidents`
- 告警详情：`/incidents/{id}`
- Lark 发送日志：`logs/lark.log`

## 7. 常见问题

- `400 未找到 cti=xxx 对应排班表配置`
  - 排查：确认对应排班已配置 `cti_values`，且值完全一致（建议小写）

- `409 cti=xxx 命中了多个排班表`
  - 排查：同一 CTI 被多个排班配置，删除冲突项

- 有 incident 但未发 Lark
  - 排查：`lark_enabled` 是否为 true，`lark_chat_id` 是否正确，`/api/v1/lark-app-config` 是否启用

- 飞书发消息失败
  - 排查：查看 `logs/lark.log` 中 `code/msg`，重点关注 token、机器人是否入群、chat_id 是否有效

## 8. 回归脚本

仓库内可用脚本：`smoke_nightingale_cti.py`

该脚本会：

- 创建两个排班并分别配置不同 CTI
- 发送两条 Nightingale 事件，验证路由到不同排班
- 发送未知 CTI，验证返回 400

