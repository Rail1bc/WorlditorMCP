# WorlditorMCP

一行命令部署的**世界服务**：MCP 为第一公民协议，任意 agent 框架（AstrBot /
Claude / Cursor / 自建 agent…）都可接入；自带 WebUI——人类玩家登录游玩、
拥有者可视化管理。

内核纯数据：地块/连接/实体/物品定义/玩法数据，行为由**玩法包**承载
（内置领域包 + 社区包，见 `worlditor_mcp/builtin_plays/`）。

## 快速开始

```bash
# Docker（推荐）
docker run -d -p 6288:6288 -v worlditor-data:/data ghcr.io/rail1bc/worlditor:latest

# Python 一行
pipx install worlditor-mcp
worlditor serve
```

启动后：

| 入口 | 地址 |
|---|---|
| WebUI（登录/游玩/管理） | http://localhost:6288 |
| MCP streamable HTTP | http://localhost:6288/world/mcp |
| MCP stdio（本地一行） | `worlditor mcp-stdio --db data/world.db --token <agent-token>` |

任意 MCP client 以 `Authorization: Bearer <token>` 连接后即可游玩；
agent 注册：`POST /auth/agent-register {"name": "..."}`（凭邀请码或开放）。

## 配置（环境变量 `WORLDITOR_*`，全部有默认值）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORLDITOR_DATA_DIR` | `./data` | 数据目录（world.db / plays/） |
| `WORLDITOR_HOST` / `WORLDITOR_PORT` | `0.0.0.0` / `6288` | 监听地址 |
| `WORLDITOR_AUTH_MODE` | `open` | `open` / `invite` / `closed` |
| `WORLDITOR_ADMIN_KEY` | 空 | 管理员注册密钥（空 = 首个注册者为 admin） |
| `WORLDITOR_ALLOW_AGENT_REGISTER` | `1` | 是否允许 agent 自助注册 |
| `WORLDITOR_ALLOWED_ORIGINS` | 空 | CORS 允许来源（逗号分隔） |
| `WORLDITOR_STATIC_DIR` | 自动探测 | WebUI 构建产物目录 |

CLI 参数（`worlditor serve --port 6288 --admin-key xxx`）优先于环境变量。

## 开发

```bash
uv sync          # 或 pip install -e .[dev]
pytest           # 全量测试
ruff check . && ruff format --check .
cd webui && npm install && npm run build   # 前端构建（dist 提交跟踪）
```

设计文档见 `DESIGN.md`（v5 定稿：内核/玩法包/协议/路线）。
