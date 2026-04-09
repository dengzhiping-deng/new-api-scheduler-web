# 定时任务 Web 管理台

一个基于 FastAPI 的 New API 巡检与自动恢复控制台，用于替代原有 Windows 计划任务 + 本地脚本方案，支持在 Linux / 容器环境运行。

## 功能概览

- Web 登录与会话保护（`/api/*` 需登录）
- 手动触发任务：`check` / `enable` / `check_and_enable`
- APScheduler 进程内定时执行
- 运行历史与原始日志可视化
- 参数可视化配置（敏感连接信息不在页面回显）
- Docker 镜像构建与 ECS/Fargate 部署骨架

## 迭代记录

- 最近一次修复与页面调整见 [CHANGELOG.md](./CHANGELOG.md)

## 项目结构

```text
webapp/
├─ app/                      # FastAPI 应用
│  ├─ main.py                # 路由、鉴权、生命周期
│  ├─ models.py              # Pydantic 模型
│  ├─ config_store.py        # 配置与认证存储
│  ├─ storage.py             # 运行历史存储
│  ├─ core/automation.py     # 巡检/恢复核心逻辑
│  ├─ services/              # 任务执行与调度服务
│  ├─ templates/             # 页面模板
│  └─ static/                # 前端静态资源
├─ data/                     # 运行数据目录（可由 APP_DATA_DIR 覆盖）
├─ tests/                    # 单元测试
├─ Dockerfile
└─ infra/aws/task-definition.json
```

## 快速开始

### 1) 环境要求

- Python `>=3.11`
- 推荐使用虚拟环境

### 2) 安装依赖

```bash
cd webapp
pip install -e .[dev]
```

### 3) 准备配置

推荐先复制示例配置：

```bash
cp data/config.example.json data/config.json
```

如果是 Windows PowerShell：

```powershell
Copy-Item data/config.example.json data/config.json
```

至少确认以下字段正确：

- `new_api_base_url`
- `new_api_username`
- `new_api_password`

### 4) 启动服务

```bash
uvicorn app.main:app --reload
```

访问：

- `http://127.0.0.1:8000/`
- 未登录会跳转到 `http://127.0.0.1:8000/login`

### 5) 首次登录

当 `data/auth.json` 不存在时，系统会自动生成默认管理员：

- 用户名：`admin`
- 密码：`admin123456`

请在首次部署后立即修改密码（见“认证配置”）。

## 配置说明

### 运行目录

应用默认读写 `webapp/data`，可通过环境变量覆盖：

```bash
APP_DATA_DIR=/app/data uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 数据文件

- `config.json`：业务配置（含 New API 连接参数）
- `auth.json`：管理员账号、密码哈希、Session 密钥
- `runs.json`：结构化运行历史
- `logs/*.log`：每次运行对应的原始日志
- `run.lock`：并发运行锁文件

### 业务配置字段（`config.json`）

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `new_api_base_url` | `str` | `https://niu.chomoo.cc` | New API 地址（会去掉末尾 `/`） |
| `new_api_username` | `str` | `""` | New API 用户名 |
| `new_api_password` | `str` | `""` | New API 密码 |
| `request_timeout` | `int` | `15` | 请求超时（秒，>0） |
| `max_enable_per_run` | `int` | `10` | 单次最多恢复数（>0） |
| `dry_run` | `bool` | `true` | 演练模式，不实际恢复 |
| `deny_channel_ids` | `list[int]` | `[]` | 禁止恢复的渠道 ID |
| `skip_channel_priorities` | `list[int]` | `[-999, -998]` | 巡检与恢复时跳过的渠道优先级 |
| `schedule_enabled` | `bool` | `true` | 是否启用定时任务 |
| `auto_reenable_enabled` | `bool` | `true` | 定时任务是否自动进入恢复阶段 |
| `schedule_interval_minutes` | `int` | `10` | 定时间隔（分钟，>0） |
| `log_page_size` | `int` | `200` | 日志页面默认返回行数 |
| `log_retention_days` | `int` | `3` | 原始日志保留天数（>0） |
| `run_retention_days` | `int` | `3` | 运行历史保留天数（>0） |
| `run_history_limit` | `int` | `200` | 历史记录保留条数 |
| `lock_ttl_minutes` | `int` | `30` | 锁文件过期时间（分钟） |

说明：

- 页面配置接口不会返回 `new_api_base_url/new_api_username/new_api_password`。
- 更新页面配置时，这 3 个敏感字段会按当前值保留，不会被覆盖。
- 巡检和恢复都会先筛选 `status == 3` 的自动禁用渠道，再排除 `skip_channel_priorities` 中配置的优先级。

### 认证配置（`auth.json`）

字段：

- `admin_username`
- `admin_password_hash`（SHA-256）
- `session_secret`

生成新密码哈希示例：

```bash
python -c "import hashlib; print(hashlib.sha256('你的新密码'.encode()).hexdigest())"
```

将输出结果写入 `admin_password_hash` 后重启服务生效。

## 任务与调度行为

### 任务类型

- `check`：仅巡检
- `enable`：仅恢复
- `check_and_enable`：先巡检，再按结果决定是否恢复

### 自动恢复触发逻辑

`check_and_enable` 在以下条件任一满足时会进入恢复阶段：

- `suggest_reenable > 0`
- `weekly_window_grace > 0`
- `rate_limit_grace > 0`

### 并发与冲突处理

- 同一时刻只允许一个任务执行
- 如定时触发时已有任务在跑，会记录一条 `skipped` 运行记录
- `run.lock` 超过 `lock_ttl_minutes` 会被视为过期并自动清理

## API 概览

登录相关：

- `GET /login`
- `POST /auth/login`
- `POST /auth/logout`

受保护接口：

- `GET /api/health`
- `GET /api/config`
- `PUT /api/config`
- `POST /api/config/validate`
- `POST /api/jobs/{job_type}` (`check|enable|check_and_enable`)
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/logs?run_id=<id>&lines=<n>`

## 测试

```bash
cd webapp
pytest -q
```

当前测试覆盖：

- 鉴权与页面访问
- 配置读写与敏感字段保留
- 核心分类逻辑（周窗口、短期限流等）

## Docker

### 构建

```bash
docker build -t new-api-scheduler-web .
```

### 运行

Linux/macOS:

```bash
docker run --rm -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -e APP_DATA_DIR=/app/data \
  new-api-scheduler-web
```

Windows PowerShell:

```powershell
docker run --rm -p 8000:8000 `
  -v "${PWD}/data:/app/data" `
  -e APP_DATA_DIR=/app/data `
  new-api-scheduler-web
```

说明：

- 建议挂载 `/app/data`，避免容器重启后丢失配置与历史数据。

## AWS ECS/Fargate

仓库内提供基础模板：

- `infra/aws/task-definition.json`

建议部署流程：

1. 创建 ECR 仓库并推送镜像。
2. 按模板修改 `image`、`executionRoleArn`、`taskRoleArn`、日志组等字段。
3. 创建 ECS Task Definition 与 Service（建议初期 `desiredCount=1`）。
4. 通过 ALB 将流量转发到容器 `8000` 端口。
5. 将服务入口限制在内网/VPN，避免直接暴露公网。

## 常见问题

### 1) 接口返回 401

先确认已在 `/login` 登录；所有 `/api/*` 均受 Session 保护。

### 2) 配置验证失败

检查 `config.json` 中 New API 地址、用户名、密码是否正确，网络是否可达。

### 3) 页面看不到最新日志

确认对应 `run_id` 的 `log_file` 存在于 `APP_DATA_DIR/logs/`，并检查文件权限。

## 已知限制

- 当前是单进程、文件存储架构，更适合小规模内部使用。
- 容器无持久卷时，重启会丢失运行状态与历史数据。
- 暂不包含细粒度 RBAC、操作审计、分布式调度。

生产化建议优先级：

1. 持久化数据（EFS/RDS/对象存储）
2. 强化鉴权与访问控制
3. 增加审计日志与告警
4. 将调度器与 Web 服务解耦
