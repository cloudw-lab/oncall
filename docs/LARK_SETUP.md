# Lark（飞书）通知配置指南

## 问题诊断

如果 `logs/lark.log` 显示如下错误：
```
"stage": "tenant_access_token", "error": "code=10003, msg=invalid param"
```

**根本原因**：Lark 应用 `app_id` 或 `app_secret` 无效或格式不正确。

---

## 获取 Lark 应用凭证

### 1. 进入飞书开放平台
访问 https://open.feishu.cn/

### 2. 创建企业自建应用
- 点击「创建应用」→「企业自建应用」
- 填写应用基本信息（应用名称、描述等）
- 完成后进入应用详情

### 3. 获取凭证
在应用详情页面找到：
- **App ID**
- **App Secret**

⚠️ **重要**：`App Secret` 仅显示一次，请妥善保管。

### 4. 配置应用权限
应用需要以下权限才能发送群消息：
- `im:message` - 发送消息权限
- `im:message:readonly` - 读取消息
- `contact:user.email:readonly` - 读取用户邮箱

### 5. 获取飞书群 Chat ID
群聊 Chat ID 获取方法：
- 打开飞书群
- 群设置 → 复制群 ID
- 或通过开放平台的群管理接口获取

格式通常为：`oc_xxxxxx` 或完整的 UUID

---

## 配置到系统

### 方式 1: 通过 API 配置（推荐）

```bash
curl -X POST http://localhost:8000/api/v1/lark-app-config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "app_id": "cli_xxxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxx"
  }'
```

### 方式 2: 通过前端配置
访问 http://localhost:8000 → 系统设置 → 飞书配置

---

## 为排班表启用飞书通知

```bash
curl -X POST http://localhost:8000/api/v1/schedules/{schedule_id}/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "lark_enabled": true,
    "lark_chat_id": "oc_xxxxxx",
    "ack_escalation_enabled": true,
    "ack_escalation_after_minutes": 15
  }'
```

---

## 常见错误与解决

### ❌ code=10003, msg=invalid param
**原因**：`app_id` 或 `app_secret` 错误

**检查**：
```bash
# 查看已配置的凭证长度
curl http://localhost:8000/api/v1/lark-app-config
```

**解决**：
1. 确认从飞书开放平台复制的凭证完整无误
2. 重新设置凭证
3. 查看 `logs/lark.log` 中的 `app_id_len` 和 `app_secret_len` 是否异常

### ❌ Missing app_id or app_secret
**原因**：未配置应用凭证

**解决**：
```bash
curl -X POST http://localhost:8000/api/v1/lark-app-config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "app_id": "your_app_id",
    "app_secret": "your_app_secret"
  }'
```

### ❌ missing_chat_id
**原因**：排班表未配置飞书群 ID

**解决**：
```bash
curl -X POST http://localhost:8000/api/v1/schedules/{schedule_id}/integrations \
  -H "Content-Type: application/json" \
  -d '{"lark_chat_id": "oc_xxxxxx", "lark_enabled": true}'
```

### ❌ Lark API error: code=13001
**原因**：飞书群 ID 不存在或应用无权限访问

**解决**：
1. 确认群 ID 正确
2. 确保应用有该群的访问权限
3. 在飞书群设置中添加应用机器人

### ❌ Lark API error: code=10001, msg=unauthorized
**原因**：应用权限不足

**解决**：
1. 进入飞书开放平台
2. 应用详情 → 权限管理
3. 添加 `im:message` 权限
4. 保存并发布

---

## 日志分析

查看实时日志：
```bash
tail -f logs/lark.log
```

关键字段解读：

| 字段 | 含义 | 示例 |
|------|------|------|
| `token_request` | 正在请求飞书 token | `app_id_len: 20` |
| `token_success` | Token 获取成功 | `token_len: 100` |
| `token_failed` | Token 获取失败 | `error: "code=10003..."` |
| `sending` | 正在发送群消息 | `chat_id: "oc_xxx"` |
| `sent` | 消息发送成功 | `message_id: "om_xxx"` |
| `fallback_sent` | 消息发送失败后降级成功 | `original_error: "..."` |
| `error` | 发送失败 | `stage: "send_payload"` |

### 快速查找失败：
```bash
grep -i error logs/lark.log
grep -i "code=" logs/lark.log
grep token_failed logs/lark.log
```

---

## 端到端测试

### 1. 确保应用已配置
```bash
curl http://localhost:8000/api/v1/lark-app-config
```

输出示例：
```json
{
  "id": 1,
  "enabled": true,
  "app_id": "cli_xxxxx"
}
```

### 2. 创建测试排班
```bash
curl -X POST http://localhost:8000/api/v1/schedules/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Schedule",
    "start_date": "2026-03-30",
    "end_date": "2026-03-31",
    "member_ids": [1]
  }'
```

### 3. 启用飞书通知
```bash
SCHEDULE_ID=1
curl -X POST http://localhost:8000/api/v1/schedules/$SCHEDULE_ID/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "lark_enabled": true,
    "lark_chat_id": "oc_xxxxxx"
  }'
```

### 4. 发送测试告警
```bash
SCHEDULE_ID=1
curl -X POST http://localhost:8000/open-api/events \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "test-source",
    "schedule_id": '$SCHEDULE_ID',
    "fingerprint": "test-fp-'$(date +%s)'",
    "title": "Test Alert",
    "summary": "This is a test alert",
    "severity": "critical",
    "status": "triggered",
    "occurred_at": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'
```

### 5. 检查日志
```bash
tail -n 5 logs/lark.log
```

预期输出：
```
... [INFO] sending {"chat_id": "oc_xxxxx", "title": "Test Alert", ...}
... [INFO] sent {"chat_id": "oc_xxxxx", "message_id": "om_xxxxx", ...}
```

---

## 飞书机器人 @ 提及

系统会自动根据用户邮箱 @ 飞书群内的用户。需要：

1. 用户在飞书和系统中邮箱一致
2. 飞书用户已加入该群
3. 应用有 `contact:user.email:readonly` 权限

日志中 `unresolved_count` 表示无法 @ 的用户数。

---

## 故障排查检查清单

- [ ] `logs/lark.log` 存在且最近有新日志
- [ ] 飞书应用凭证已配置且不为空
- [ ] 飞书群 Chat ID 格式正确（通常以 `oc_` 开头）
- [ ] 应用在飞书后台已发布
- [ ] 应用拥有 `im:message` 权限
- [ ] 应用已被添加到目标飞书群
- [ ] 飞书网络连接正常（test: `curl https://open.feishu.cn/`)
- [ ] 系统时间与飞书服务器同步

---

## 更多资源

- 飞书开放平台: https://open.feishu.cn/
- 飞书 API 文档: https://open.feishu.cn/document/home/
- 群应用权限: https://open.feishu.cn/document/home/permission-scopes-reference/
- 消息发送 API: https://open.feishu.cn/document/server-docs/im-v1/message/create

