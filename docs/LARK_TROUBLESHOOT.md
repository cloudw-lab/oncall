# Lark 通知故障排查 - 快速参考

## 问题：消息无法发送到飞书群

### 第一步：检查日志

```bash
tail -n 20 logs/lark.log
```

### 第二步：根据错误码诊断

| 错误信息 | 原因 | 解决方案 |
|---------|------|--------|
| `code=10003, msg=invalid param` | App ID 或 Secret 无效 | 1. 检查凭证是否完整无误<br>2. 重新从飞书后台复制<br>3. 确认应用已发布 |
| `Missing app_id or app_secret` | 未配置应用凭证 | 调用 `POST /api/v1/lark-app-config` 配置 |
| `missing_chat_id` | 排班表无飞书群 ID | 调用 `POST /api/v1/schedules/{id}/integrations` 配置 |
| `code=13001` | 飞书群不存在或无权限 | 1. 检查群 ID 格式<br>2. 在群设置添加应用机器人 |
| `code=10001, msg=unauthorized` | 应用权限不足 | 1. 进入飞书后台<br>2. 应用权限 → 添加 `im:message`<br>3. 发布变更 |
| `token_len=0` 或 `missing_tenant_access_token` | Token 获取失败 | 检查网络，验证凭证，查看 HTTP 状态码 |

### 第三步：快速验证

```bash
# 1. 查看应用配置
curl http://localhost:8000/api/v1/lark-app-config

# 2. 查看排班集成配置
curl http://localhost:8000/api/v1/schedules/1/integrations

# 3. 手动发送测试告警
curl -X POST http://localhost:8000/open-api/events \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "test-lark-debug",
    "schedule_id": 1,
    "fingerprint": "test-'$(date +%s)'",
    "title": "Test Alert - 消息是否送达？",
    "severity": "critical",
    "status": "triggered"
  }'

# 4. 检查日志中的发送记录
tail -n 5 logs/lark.log
grep "test-lark-debug" logs/lark.log
```

### 第四步：常见检查项

```bash
# 检查应用是否已启用
curl http://localhost:8000/api/v1/lark-app-config | grep "enabled"

# 查找所有错误
grep -i "error\|failed" logs/lark.log | tail -20

# 查看成功发送的消息数
grep "sent" logs/lark.log | wc -l

# 获取最新的失败信息
grep -i "stage.*token\|error" logs/lark.log | tail -1
```

## 关键配置

### 最小必要配置

```json
{
  "enabled": true,
  "app_id": "cli_xxxxxxxxxxxxxxxxxxxxx",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

### 排班级集成配置

```json
{
  "lark_enabled": true,
  "lark_chat_id": "oc_xxxxxxxxxxxxxxxx",
  "ack_escalation_enabled": true,
  "ack_escalation_after_minutes": 15
}
```

## 日志解释

日志格式：`[时间] [日志级别] [事件] [JSON数据]`

**发送成功示例**：
```
2026-03-30 20:47:29,405 [INFO] token_success {"token_len": 100}
2026-03-30 20:47:29,516 [INFO] sending {"chat_id": "oc_xxx", "title": "告警", "mention_count": 1}
2026-03-30 20:47:29,625 [INFO] sent {"chat_id": "oc_xxx", "message_id": "om_xxx"}
```

**发送失败示例**：
```
2026-03-30 20:47:29,405 [INFO] error {"chat_id": "oc_xxx", "stage": "tenant_access_token", "error": "code=10003, msg=invalid param"}
```

## 获取飞书凭证（30秒快速指南）

1. 访问 https://open.feishu.cn/
2. 「创建应用」→ 「企业自建应用」
3. 填写应用名称，创建
4. 在应用详情页：
   - 复制 **App ID**
   - 复制 **App Secret**（仅显示一次）
5. 权限管理 → 添加 `im:message` 权限
6. 发布应用
7. 在飞书群添加该应用机器人

## 更多帮助

- 完整指南：[docs/LARK_SETUP.md](../docs/LARK_SETUP.md)
- 飞书官方文档：https://open.feishu.cn/document/home/
- API 参考：https://open.feishu.cn/document/server-docs/im-v1/message/create

