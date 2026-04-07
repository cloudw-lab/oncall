# Keycloak 集成指南

本指南说明如何让 Keycloak 作为人员管理的主数据源，并将用户（及所属组）同步到 Oncall 平台。

## 1. 准备 Keycloak

1. 创建一个 `admin-cli` 或专用的 **Confidential** Client，并允许使用密码凭证获取 token。若使用专用 Client，请在 `.env` 中同步更新 `KEYCLOAK_CLIENT_ID/KEYCLOAK_CLIENT_SECRET`。
2. 确保具有 `view-users` 与 `manage-users` 权限的账号（可使用默认管理账号），该账号会由后台定期登录拉取用户列表。
3. 可选：创建 `oncall-admins` 组，成员会在同步后自动授予 `admin` 角色，其他人默认 `operator`。

## 2. 配置环境变量

在 `.env` 或部署平台里设置以下变量：

```
KEYCLOAK_ENABLED=true
KEYCLOAK_SERVER_URL=https://keycloak.example.com/
KEYCLOAK_REALM=oncall
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=changeme
KEYCLOAK_CLIENT_ID=admin-cli
KEYCLOAK_CLIENT_SECRET=
KEYCLOAK_VERIFY_SSL=true
KEYCLOAK_SYNC_INTERVAL_MINUTES=60
KEYCLOAK_DISABLE_MISSING=true
```

- `SYNC_INTERVAL_MINUTES > 0` 时会自动轮询；若只想使用手动触发，可保持为 `0`。
- `DISABLE_MISSING=true` 表示当用户在 Keycloak 中被删除时，本地账号会被自动设为 `is_active=false`。

## 3. 手动触发同步

管理员登录后可调用：

```
POST /api/v1/integrations/keycloak/sync
```

响应示例：

```json
{
  "processed": 42,
  "created": 5,
  "updated": 37,
  "deactivated": 1
}
```

也可以通过 `GET /api/v1/integrations/keycloak/status` 查看当前配置。

## 4. 字段映射说明

| Keycloak 字段 | Oncall 字段 | 说明 |
| --- | --- | --- |
| `username` | `users.username` | 作为主键；为空时使用 Keycloak `id` |
| `email` | `users.email` | 缺失时会生成 `<username>@<realm>.local` |
| `firstName + lastName` | `users.full_name` | 均为空时回退到 `username` |
| `attributes.team[0]` | `users.team` | 没有属性则保持原值/默认 `SRE` |
| `attributes.phoneNumber[0]` | `users.phone` | 会经过加密存储 |
| Keycloak 组 | `users.keycloak_groups` | 同步为字符串数组；包含 `admin` / `oncall-admins` 时授予管理员角色 |

同步过程中若找不到对应用户，会创建一个带随机密码的账号；密码仅占位，后续仍应通过 Keycloak 登录或单点。

## 5. 常见问题

- **配置错误 / 无法登录**：检查 `KEYCLOAK_SERVER_URL` 是否以 `/` 结尾（可留给程序自动补全），以及账号是否具有 REST Admin 权限。
- **证书问题**：在测试环境可将 `KEYCLOAK_VERIFY_SSL=false`。生产环境必须提供受信任的证书。
- **批量停用**：如果不希望 Keycloak 删除用户时自动停用本地账号，将 `KEYCLOAK_DISABLE_MISSING=false`。

完成上述配置后，Keycloak 将成为人员信息的统一来源，新增/停用用户均可通过同步自动反映在 Oncall 排班平台。
