# 您的 Lark 发送问题诊断报告

## 🔴 检测到的错误

```
2026-03-30 20:47:29,405 [INFO] error 
{
  "chat_id": "oc_lark_chat_prod",
  "stage": "tenant_access_token",
  "error": "code=10003, msg=invalid param"
}
```

---

## 问题分析

### 错误含义
- **code=10003** ：飞书 API 返回"无效参数"
- **stage=tenant_access_token** ：在获取应用 Token 时失败
- **原因** ：`app_id` 或 `app_secret` 无效、过期或格式错误

---

## 🔧 解决步骤

### 第 1 步：验证当前配置

```bash
curl http://localhost:8000/api/v1/lark-app-config
```

输出应该类似：
```json
{
  "id": 1,
  "enabled": true,
  "app_id": "cli_mock_app_id",
  "app_secret": "cli_mock_app_secret"
}
```

如果 `app_id` 是 `cli_mock_app_id`，那就是问题所在 ⚠️

### 第 2 步：获取真实的飞书应用凭证

1. **登录飞书开放平台**
   - 访问：https://open.feishu.cn/
   - 用飞书账号或企业邮箱登录

2. **创建/进入应用**
   - 点击「创建应用」或选择已有应用
   - 选择「企业自建应用」

3. **获取凭证**
   - 在应用详情页找到 **App ID** 和 **App Secret**
   - 完整复制（不要手动修改）

4. **配置权限**
   - 权限管理 → 添加 `im:message` 权限（发送消息）
   - 点击「发布」

5. **添加应用到飞书群**
   - 打开目标飞书群
   - 群设置 → 添加机器人
   - 选择您的应用

### 第 3 步：更新系统配置

使用您从飞书获取的真实凭证：

```bash
curl -X POST http://localhost:8000/api/v1/lark-app-config \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "app_id": "cli_xxxxxxxxxxxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }'
```

替换 `app_id` 和 `app_secret` 为真实值。

### 第 4 步：获取飞书群 Chat ID

```bash
# 在飞书群中
# 1. 打开群设置
# 2. 复制群 ID（或从飞书开放平台群管理 API 获取）
# 通常格式为：oc_cc8d68d763ef570e6d87e98f5cd7a168

# 为排班表配置此群 ID
curl -X POST http://localhost:8000/api/v1/schedules/1/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "lark_enabled": true,
    "lark_chat_id": "oc_cc8d68d763ef570e6d87e98f5cd7a168"
  }'
```

### 第 5 步：测试

发送测试告警查看日志：

```bash
curl -X POST http://localhost:8000/open-api/events \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "test-lark",
    "schedule_id": 1,
    "fingerprint": "test-fp-'$(date +%s)'",
    "title": "测试告警 - 消息是否送达飞书？",
    "severity": "critical",
    "status": "triggered"
  }'

# 查看日志
tail -n 10 logs/lark.log
```

**成功的日志应该包含**：
```
... [INFO] token_success ...
... [INFO] sending ... 
... [INFO] sent ...
```

**失败的日志会显示**：
```
... [INFO] error ... "code=10003" ...
```

---

## ✅ 验证清单

在进行以上步骤后，检查：

- [ ] `curl http://localhost:8000/api/v1/lark-app-config` 返回真实的 app_id（不是 mock）
- [ ] `curl http://localhost:8000/api/v1/schedules/1/integrations` 中 `lark_chat_id` 不为空
- [ ] 飞书应用在飞书后台已发布
- [ ] 飞书应用已被添加到目标群
- [ ] `logs/lark.log` 中出现 `"token_success"` 事件（不是 `token_failed`）
- [ ] `logs/lark.log` 中出现 `"sent"` 事件（消息发送成功）

---

## 快速排查命令

```bash
# 1. 查看所有 token 相关错误
grep "token_" logs/lark.log

# 2. 查看最新的发送尝试
tail -n 3 logs/lark.log

# 3. 统计成功 vs 失败
echo "成功：$(grep '"sent"' logs/lark.log | wc -l)"
echo "失败：$(grep '"error"' logs/lark.log | wc -l)"

# 4. 查看特定群的所有尝试
grep 'oc_lark_chat_prod' logs/lark.log
```

---

## 还是不行？

查看完整指南：[LARK_SETUP.md](LARK_SETUP.md)

常见错误与解决：[LARK_TROUBLESHOOT.md](LARK_TROUBLESHOOT.md)

或检查飞书官方文档：https://open.feishu.cn/document/home/

---

**最后更新**：2026-03-30  
**检测到的错误时间**：2026-03-30 20:47:29

