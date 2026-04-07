# Oncall 排班平台

一个基于 FastAPI + SQLAlchemy 的 oncall 排班管理系统。

## 功能特性

✅ **用户管理** - 添加、编辑、删除用户信息  
✅ **排班管理** - 创建和管理多个排班表  
✅ **自动排班** - 支持按规则生成 day/night 值班（MVP）  
✅ **日历视图** - 查看指定时间范围的排班  
✅ **当前值班** - 实时查询当前值班人员  
✅ **换班管理** - 支持成员之间申请换班  
✅ **通知提醒** - 每日值班提醒（邮件）  
✅ **规则校验** - 支持周上限、连续夜班、公平性校验  
✅ **特殊排班** - 独立存储、支持删除与批量导入  

## 快速开始

### 1. 安装依赖

```bash
cd oncall_scheduler
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 初始化数据

```bash
python init_data.py
```

### 3. 启动服务

```bash
# 方式 1: 使用启动脚本
./start.sh

# 方式 2: 手动启动
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 访问服务

- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health
- **首页**: http://localhost:8000

### Keycloak 用户同步（可选）

若需要把人员管理托管给 Keycloak，请参阅 `docs/KEYCLOAK_SETUP.md`。文档涵盖了环境变量、管理员 API 以及定时同步的配置方式。

### 4.1 登录

当前前端已切换为真实登录态：登录成功后会调用 `/api/v1/auth/me` 获取当前用户，并默认展示“我的相关告警”。

如果你使用过 `init_data.py` 初始化测试数据，可尝试默认密码：`password123`。

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "zhangsan",
    "password": "password123"
  }'
```

登录成功后，可携带返回的 Bearer Token 调用：

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### 5. 快速验证特殊排班接口（可选）

```bash
DATABASE_URL=sqlite:///./oncall_test.db python smoke_special_shifts.py
```

## API 使用示例

### 获取所有用户
```bash
curl http://localhost:8000/api/v1/users/
```

### 获取我的相关告警
```bash
curl "http://localhost:8000/incidents?related_only=true&status=all" \
  -H "Authorization: Bearer <access_token>"
```

### Nightingale 按 CTI 路由到值班表

1) 先给排班配置 CTI 值（`cti_values`），一个 CTI 只建议映射一个排班：

```bash
curl -X POST http://localhost:8000/api/v1/schedules/1/integrations \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_key": "schedule-1-default",
    "source_name": "SRE Core 默认接入",
    "lark_enabled": true,
    "lark_chat_id": "oc_xxx",
    "cti_values": ["sre-core", "oncall-tc"]
  }'
```

2) Nightingale 回调到开放接口（不需要登录态）：

```bash
curl -X POST http://localhost:8000/open-api/events \
  -H "Content-Type: application/json" \
  -d '{
    "rule_name": "cert expiring",
    "severity": "critical",
    "status": "triggered",
    "labels": {
      "cti": "sre-core"
    },
    "summary": "ssl cert will expire in 7 days"
  }'
```

系统会读取 payload 的 `cti`/`labels.cti`/`tags.cti`，匹配到对应排班后按该排班的值班人 + Lark 群配置发送通知。

### 查询告警详情
```bash
curl http://localhost:8000/incidents/1 \
  -H "Authorization: Bearer <access_token>"
```

### 获取所有排班表
```bash
curl http://localhost:8000/api/v1/schedules/
```

### 获取当前值班人员
```bash
curl http://localhost:8000/api/v1/schedules/1/current
```

### 配置排班规则
```bash
curl -X POST http://localhost:8000/api/v1/schedules/1/rules \
  -H "Content-Type: application/json" \
  -d '{
    "max_shifts_per_week": 5,
    "max_night_shifts_per_week": 2,
    "avoid_consecutive_nights": true,
    "max_consecutive_work_days": 5,
    "fairness_threshold": 2,
    "use_volunteers_only": false,
    "volunteer_member_ids": [],
    "holiday_dates": [],
    "blackout_dates": []
  }'
```

### 生成排班（按规则）
```bash
curl -X POST http://localhost:8000/api/v1/schedules/1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "regenerate": true,
    "include_secondary": false
  }'
```

### 校验排班
```bash
curl -X POST http://localhost:8000/api/v1/schedules/1/validate \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 创建特殊排班（独立数据）
```bash
curl -X POST http://localhost:8000/api/v1/special-shifts/ \
  -H "Content-Type: application/json" \
  -d '{
    "schedule_id": 1,
    "user_id": 1,
    "shift_date": "2026-04-01",
    "shift_type": "full_day",
    "role": "primary",
    "start_time": "2026-04-01T09:00:00",
    "end_time": "2026-04-01T18:00:00",
    "notes": "节假日保障",
    "is_locked": true
  }'
```

### 批量导入特殊排班
```bash
curl -X POST http://localhost:8000/api/v1/special-shifts/schedules/1/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "overwrite": false,
    "items": [
      {
        "user_id": 1,
        "shift_date": "2026-04-01",
        "shift_type": "full_day",
        "role": "primary",
        "notes": "节假日保障"
      }
    ]
  }'
```

### 获取排班日历
```bash
curl "http://localhost:8000/api/v1/schedules/1/calendar?start_date=2026-03-30&end_date=2026-04-05"
```

### 创建新用户
```bash
curl -X POST http://localhost:8000/api/v1/users/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "test",
    "email": "test@example.com",
    "full_name": "测试用户",
    "password": "password123"
  }'
```

## 项目结构

```
oncall_scheduler/
├── app/
│   ├── __init__.py
│   ├── config.py              # 配置管理
│   ├── database.py            # 数据库连接
│   ├── main.py                # 应用入口
│   ├── models.py              # 数据模型
│   ├── schemas.py             # Pydantic 模式
│   ├── routers/
│   │   ├── users.py           # 用户路由
│   │   ├── schedules.py       # 排班路由
│   │   ├── shifts.py          # 班次路由
│   │   └── exchanges.py       # 换班路由
│   ├── services/
│   │   ├── schedule_service.py    # 排班服务
│   │   └── notification_service.py # 通知服务
│   └── utils/
│       └── helpers.py         # 工具函数
├── init_data.py               # 初始化脚本
├── test_api.py                # API 测试脚本
├── start.sh                   # 启动脚本
├── requirements.txt           # 依赖列表
├── .env                       # 环境变量
└── oncall.db                  # SQLite 数据库
```

## 核心功能说明

### 1. 排班规则

支持三种轮换模式：
- **daily** - 每日轮换
- **weekly** - 每周轮换
- **monthly** - 每月轮换

> 当前版本按 `架构.md` 先实现本地 SQLite MVP：
> - 自动排班优先覆盖 `day.primary`、`night.primary`
> - 支持成员级限制：`no_nights`、每周班次上限
> - 支持规则配置与统一校验（生成后建议执行 `/validate`）

## 运行与诊断

### Lark（飞书）通知配置

若需启用飞书群消息通知，请参考 [Lark 完整设置指南](docs/LARK_SETUP.md)。

### Nightingale 告警回调（CTI 路由）

若需把 Nightingale 告警按 `cti` 标签路由到对应值班表，请参考 [Nightingale 接入指南](docs/NIGHTINGALE_SETUP.md)。

### 日志查看

飞书群消息的发送记录会写入 `logs/lark.log`。生产环境建议持久化该目录。

```bash
# 查看实时日志
tail -f logs/lark.log

# 快速查找错误
grep -i error logs/lark.log
grep "code=" logs/lark.log
```

**常见错误**：
- `code=10003, msg=invalid param` → 应用凭证 (app_id/app_secret) 无效，请参考 [Lark 设置指南](docs/LARK_SETUP.md#获取-lark-应用凭证)
- `missing_chat_id` → 排班表未配置飞书群 ID
- `token_failed` → Token 获取失败，检查应用权限和网络连接

**字段含义**：每条日志包含 `chat_id`、`title`、`mention_count`、`unresolved_count`、`stage/error` 等，便于定位是配置问题、token 获取失败还是 HTTP 调用异常。

### 2. 班次类型

- **day** - 白班 (09:00-18:00)
- **night** - 夜班 (18:00-09:00，跨天)
- **primary/secondary** - 每个班次支持主值班/副值班角色（MVP 默认主值班）

### 3. 换班流程

1. 值班人员发起换班申请
2. 被申请人审批（同意/拒绝）
3. 审批通过后自动更新班次

## 测试数据

初始化脚本会创建以下测试数据：

**用户:**
- 张三 (zhangsan)
- 李四 (lisi)
- 王五 (wangwu)
- 赵六 (zhaoliu)

**排班表:**
- 一线值班（按周轮换，从当天开始 90 天）

## 配置说明

编辑 `.env` 文件修改配置：

```bash
# 数据库配置
DATABASE_URL=sqlite:///./oncall.db
# DATABASE_URL=postgresql://user:password@localhost/oncall_db

# 邮件通知（可选）
EMAIL_ENABLED=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-email@example.com
SMTP_PASSWORD=your-password
```

## 开发说明

### 添加新的 API 端点

1. 在 `app/routers/` 下创建或编辑路由文件
2. 在 `app/main.py` 中注册路由
3. 定义 Pydantic 模式在 `app/schemas.py`
4. 实现业务逻辑在 `app/services/`

### 数据库迁移

如使用 PostgreSQL，建议配置 Alembic 进行迁移：

```bash
alembic init alembic
# 配置 alembic.ini
# 修改 alembic/env.py 中的 target_metadata
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

## 常见问题

**Q: 如何重置数据？**  
A: 删除 `oncall.db` 文件后重新运行 `python init_data.py`

**Q: 如何修改排班规则？**  
A: 通过 POST `/api/v1/schedules/{id}/rules` 接口更新

**Q: 邮件通知不工作？**  
A: 检查 `.env` 中的 SMTP 配置，确保 `EMAIL_ENABLED=true`

## License

MIT License
