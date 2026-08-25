# WorlditorMCP

一行命令部署的**世界服务**：MCP 为第一公民协议，任意 agent 框架（AstrBot /
Claude / Cursor / 自建 agent…）都可接入；自带 WebUI——人类玩家登录游玩、
拥有者经独立管理端口可视化管理（双端口，D16）。

内核纯数据：世界/组织树/地块/连接/实体/物品定义/玩法数据，行为由**玩法包**
承载（社区包放 `<数据目录>/plays/`；内置领域包开发中，见 `DESIGN.md` §6）。

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
| 玩家端口：WebUI（登录/游玩）+ MCP + 快照/SSE | http://localhost:6288 |
| MCP streamable HTTP | http://localhost:6288/world/mcp |
| **管理端口：管理 REST + 管理 WebUI（拥有者）** | http://127.0.0.1:6289（仅本机） |
| MCP stdio（本地一行） | `worlditor mcp-stdio --db data/world.db --token <agent-token>` |

任意 MCP client 以 `Authorization: Bearer <token>` 连接后即可游玩；
agent 注册：`POST /auth/agent-register {"name": "..."}`（凭邀请码或开放）。

> 管理端口默认只监听 127.0.0.1；Docker 部署时如需远程管理，设置
> `WORLDITOR_ADMIN_HOST=0.0.0.0` 并**不要**把 6289 映射到宿主机公网。

## 配置（环境变量 `WORLDITOR_*`，全部有默认值）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORLDITOR_DATA_DIR` | `./data` | 数据目录（world.db / plays/） |
| `WORLDITOR_HOST` / `WORLDITOR_PORT` | `0.0.0.0` / `6288` | 玩家端口监听地址 |
| `WORLDITOR_ADMIN_HOST` / `WORLDITOR_ADMIN_PORT` | `127.0.0.1` / `6289` | 管理端口（0 = 关闭） |
| `WORLDITOR_AUTH_MODE` | `open` | `open` / `invite` / `closed` |
| `WORLDITOR_ADMIN_KEY` | 空 | 管理员注册密钥（空 = 首个注册者为 admin） |
| `WORLDITOR_ALLOW_AGENT_REGISTER` | `1` | 是否允许 agent 自助注册 |
| `WORLDITOR_ALLOWED_ORIGINS` | 空 | CORS 允许来源（逗号分隔） |
| `WORLDITOR_STATIC_DIR` | 自动探测 | WebUI 构建产物目录 |

CLI 参数（`worlditor serve --port 6288 --admin-port 6289 --admin-key xxx`）
优先于环境变量。

## 玩法包

行为、规则、工具与界面全部由玩法包提供（内核纯数据 + 原语 + 注册表）。
一个最小的玩法包（`<数据目录>/plays/worlditor_play_hello/`）：

```
play.yaml          # name/display_name/version/requires
main.py            # setup(api, context)：注册 kind/交互/事件/工具/视图
```

玩法包可：注册实体 kind（含字段声明）、交互、事件订阅、MCP 工具
（参数支持 array，G11）、WebUI 视图、覆盖/禁用行为原语（override/
disable/过滤器链，D11/G14）、spawn/编辑实体与地图（D14）、读写实体字段
与按世界隔离的 KV。详见 `DESIGN.md`（设计/协议/路线）与 `GAPS.md`（缺口清单）。

## 开发

```bash
uv sync          # 或 pip install -e .[dev]
pytest           # 全量测试
ruff check . && ruff format --check .
cd webui && npm install && npm run build   # 前端构建（dist 提交跟踪）
```
