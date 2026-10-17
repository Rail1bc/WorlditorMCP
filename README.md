# WorlditorMCP

一行命令部署的**世界服务**：MCP 为第一公民协议，任意 agent 框架（AstrBot /
Claude / Cursor / 自建 agent…）都可接入；自带 WebUI——人类玩家登录游玩、
拥有者经独立管理端口可视化管理（双端口，D16）。

内核纯数据：世界/组织树/地块/连接/实体（= 组件字典）/玩法数据，行为与**世界内容**
都由**玩法包**承载（社区包放 `<数据目录>/plays/`；内置只剩 1 个世界内容包，
行为玩法包的参考实现见 `tests/fixtures/plays/`——`docs/PLAY_DEV.md` §12）。

## 快速开始（本地）

```bash
pip install -e .          # 或 uv sync；Docker 见下节
worlditor serve
```

启动后：

| 入口 | 地址 |
|---|---|
| 玩家端口：WebUI（登录/游玩）+ MCP + 快照/SSE | http://localhost:6288 |
| MCP streamable HTTP | http://localhost:6288/world/mcp |
| **管理端口：管理 REST + 管理 WebUI（拥有者）** | http://127.0.0.1:6289（仅本机） |

任意 MCP client 以 `Authorization: Bearer <token>` 连接后即可游玩
（本地 agent 与远程 agent 同走 streamable HTTP，无需额外进程）；
agent 注册：`POST /auth/agent-register {"name": "..."}`（凭邀请码或开放）。

## 云服务器部署（Docker，推荐）

镜像经 GitHub Actions 自动发布到 `ghcr.io/rail1bc/worlditor`（打版本标签即发布）。

```bash
# 1. 服务器装 Docker（Ubuntu/Debian）
curl -fsSL https://get.docker.com | sh

# 2. 拉取仓库的 compose.yml（修改 ADMIN_KEY / AUTH_MODE）后启动
docker compose up -d
```

- **玩家端口** `6288`：公网开放（WebUI + MCP + 注册）
- **管理端口** `6289`：compose 里只映射到宿主机 `127.0.0.1`——永不出公网，
  用 SSH 隧道访问：

```bash
ssh -L 6289:127.0.0.1:6289 user@你的服务器
# 本地浏览器打开 http://127.0.0.1:6289
```

- **数据持久化**：数据卷（world.db / 账户 / 玩法包），重建容器不丢数据。
  卷名由 compose 管理（实际是 `<项目目录名>_worlditor-data`），**不要自己拼卷名**——
  按服务备份，容器用哪个卷就是哪个：

  ```bash
  # 备份（在 compose.yml 所在目录执行；包写到当前目录）
  docker compose exec worlditor tar czf - -C /data . > worlditor-backup.tgz

  # 恢复（先停服务，恢复完再启动）
  docker compose stop worlditor
  docker compose run --rm --no-deps --entrypoint sh worlditor \
    -c 'tar xzf - -C /data' < worlditor-backup.tgz
  docker compose start worlditor
  ```

  > `docker run -v <卷名>:/data` 一旦卷名写错，Docker 会**新建一个空卷**并打出空包，
  > 而备份看起来"成功"了——按服务走就没有写错卷名的可能。

**更新**（一条命令，数据不丢）：

```bash
docker compose pull && docker compose up -d
```

> 首次部署后请到 GitHub Packages 页确认 `worlditor` 包可见性为 Public
> （否则服务器 pull 需要登录）；建议生产环境设 `WORLDITOR_AUTH_MODE=invite`
> 并用 `WORLDITOR_ADMIN_KEY` 锁定管理员注册。

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
| `WORLDITOR_MCP_ALLOWED_HOSTS` | 空 | MCP Host 白名单（逗号分隔；空 = 任意 Host，局域网 IP / 域名直接可用） |
| `WORLDITOR_MCP_ALLOWED_ORIGINS` | 空 | MCP Origin 白名单（空 = 按 hosts 派生） |
| `WORLDITOR_STATIC_DIR` | 自动探测 | WebUI 构建产物目录 |

CLI 参数（`worlditor serve …`）优先于同名环境变量：

| 参数 | 说明 |
|---|---|
| `--host` / `--port` | 玩家端口监听地址 / 端口 |
| `--admin-host` / `--admin-port` | 管理端口监听地址 / 端口（`--admin-port 0` = 关闭管理端口） |
| `--data-dir` | 数据目录 |
| `--admin-key` | 管理员注册密钥 |
| `--auth-mode {open,invite,closed}` | 身份模式 |
| `--allowed-origins` | CORS 允许来源（逗号分隔） |
| `--mcp-allowed-hosts` / `--mcp-allowed-origins` | MCP Host / Origin 白名单（逗号分隔） |
| `--static-dir` | WebUI 构建产物目录 |
| `--verbose` | 详细日志（DEBUG） |

## 玩法包

行为、规则、工具、界面**以及世界内容**全部由玩法包提供（内核纯数据 + 原语 +
注册表）——v0.2.0 起内核不内置任何地图/地块/实体，空库只有一个空的「默认世界」。
一个最小的玩法包（`<数据目录>/plays/worlditor_play_hello/`）：

```
play.yaml          # name/display_name/version/requires（name 必须 worlditor_play_ 前缀）
main.py            # setup(api, context)：注册组件声明/交互/事件/工具/视图
helper.py          # 自己的辅助模块（可选，包内用相对导入 from . import helper）
```

> **多文件包**：`main.py` 按**包语义**加载（v0.7.3 起），包内用相对导入即可；
> `import helper` 这种绝对导入会失败（避免两个包抢同一个裸模块名）。
> zip 安装（管理端）要求：顶层目录名 **== `play.yaml` 的 name**、带
> `worlditor_play_` 前缀。

玩法包可：声明组件（含字段 schema）、注册交互、事件订阅、MCP 工具
（参数支持 array，G11）、WebUI 视图、覆盖/禁用行为原语（override/
disable/过滤器链，D11/G14）、跨包服务（M3）、放置/编辑实体与地图（D14）、
读写实体组件与按世界隔离的 KV；**世界包**还可写 `async def setup(...)` 用
`api.import_bundle(...)` **单事务**导入地图、地块、连接与实体（要么全落盘、
要么什么都不写；参考内置 `worlditor_play_demo_world`：地图已存在则跳过，
不覆盖用户改动）。

**玩家模型（v0.8.0 / D45–D47）**：内核**不诞生角色、不存在出生点、不标记"谁是玩家"**
——注册/登录只产出凭据（`token.entity_id` 为空是常态）。内核只记两本账
（"这次以哪具实体行动" + "这具实体属于哪个主体"），**"玩家是什么"归玩法包**：
一具化身 = 一个带 `core:account` 的普通实体，创建 / 切换 / 退掉都走内核窄口
（`api.claim_avatar` / `api.act_as` / `api.release_avatar`）。参考玩家包见
`tests/fixtures/plays/worlditor_play_player/`，契约见 `docs/PLAY_DEV.md` §14。

安装方式：把包目录放进 `<数据目录>/plays/`，或在管理端
「玩法包 → 安装玩法包（zip）」上传（zip 内单个顶层目录 `<play_id>/`，
含 play.yaml 与 main.py）。

- 内置包只有**世界内容包** `worlditor_play_demo_world`（示例主世界：41 地块 +
  商贩·阿福/告示牌/木门；只导入内容，不注册行为）；行为玩法包（工具/视图/
  服务/组件声明）不再随仓库分发，参考实现见 `tests/fixtures/plays/`
  （`docs/PLAY_DEV.md` §12 / §14）
- 身份只有一种 `player`：人类玩家与 agent 不作区分（脚本/agent 可用登录页
  「agent / 脚本接入」无密码注册）；⚠ **v0.9.0 起表结构 v13——升级请删
  `world.db` 重建**（D13：无迁移，旧库会被明确拒绝并指名该删哪个文件）
- `docs/PLAY_DEV.md`：玩法包开发指南（API 全量 + 约定 + 示例）
- `docs/HTTP_API.md`：HTTP 端点参考（玩家端口 + 管理端口：路径 / 档位 / 请求体 / 示例）
- `docs/NGINX_DEPLOY.md`：域名 + HTTPS 反向代理部署（含双端口暴露边界）
- `docs/PLAYER_PAGE_PLAN.md`：玩家包与界面扩展（剩余工作 / K-5·K-10·P7 / 进场流程）；
  `docs/PLAYER_MODEL_PLAN.md`、`docs/ENTITY_FOLD_PLAN.md` 是已完成的施工档案
- `docs/CORE_AUDIT.md`：内核边界审查（零玩法包视角）+ 决策记录（其 §4 待办多数已收编进 `GAPS.md` G26/G49–G52）
- `DESIGN.md`：设计/协议/路线（唯一权威）
- `GAPS.md`：平台缺口清单（历史与观察项）

## 开发

```bash
uv sync --extra dev       # 或 pip install -e ".[dev]"（dev extra 才带 pytest/ruff）
pytest                   # 全量测试
ruff check . && ruff format --check .
cd webui && npm install && npm run build   # 前端构建（dist 提交跟踪）
```
