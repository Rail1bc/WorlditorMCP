# HTTP 端点参考（玩家端口 + 管理端口）

> 权威来源是代码：玩家端口 `worlditor_mcp/world/mcp/http.py`（路由组装在
> `build_http_app`），管理端口 `worlditor_mcp/admin.py`（`build_admin_app`）。
> 本文是给人看的地图——**改端点时请同步这里**。

## 0. 两个端口与档位（D16）

| 端口 | 默认 | 内容 |
|---|---|---|
| 玩家端口 | `6288`（`0.0.0.0`） | MCP + 游玩 WebUI + 快照/SSE + 注册登录 |
| 管理端口 | `6289`（`127.0.0.1`） | 管理 REST + 管理 WebUI（`--admin-port 0` 可关闭） |

- **档位（tier）**：`read`（围观，只读快照/scene）/ `play`（玩家）/ `admin`（拥有者）。
- **认证**：`Authorization: Bearer <token>`；SSE 因浏览器 `EventSource` 不能带
  请求头，额外支持 `?token=<token>`——**该 query 会进服务器/反代访问日志**，
  别把它贴到公网日志里。
- **管理端口不信任端口隔离**：所有 `/admin/*` 一律要求 `tier=admin`（双保险，D16）。
- **公共路径（免认证）**：玩家端口 `/auth/register`、`/auth/login`、
  `/auth/agent-register`、`/auth/read-token`、`/meta`、`/views`，以及内置 WebUI
  静态资源 `/`、`/assets/*`、`/favicon.ico`。
  （免认证 = 不要求凭据；带凭据时仍会解析身份，`/views` 就依赖这一点按世界过滤。）
- **响应约定**：管理端写端点成功 `{"ok": true, "data": …}`，失败 `400
  {"error": "…"}`（`WorldError` 文案原样透出）；读端点直接返回数据对象。

## 1. 玩家端口（6288）

| 方法 | 路径 | 档位 | 说明 |
|---|---|---|---|
| POST/GET/DELETE | `/world/mcp` | play / admin | MCP streamable HTTP（工具调用入口；`read` 档在工具入口被拒） |
| GET | `/state` | read / play / admin | 全量快照：`{maps, locations, entities}`，按 G1 可见性过滤 private 地图 |
| GET | `/scene?entity_id=` | read / play / admin | 单实体场景 `{entity, scene, peers}`（含动作菜单；`entity_id` 缺省 = 调用者自己） |
| GET | `/events` | play / admin | SSE 事件流（`?token=` 支持） |
| GET | `/views` | 免认证 | 视图清单 `{views: [{key,title,icon,play_id}]}`；**带凭据时按调用者所在世界过滤**（D15） |
| GET | `/meta` | 免认证 | `{"mode": "play"}`（前端模式识别） |
| POST | `/auth/register` | 免认证 | 人类注册（`{username, password, invite_code?, admin_key?}`） |
| POST | `/auth/login` | 免认证 | 人类登录 → `{"ok":true,"token":{…}}` |
| POST | `/auth/agent-register` | 免认证 | agent/脚本无密码自助注册（`{"name": "…"}`，按 `AUTH_MODE` / `ALLOW_AGENT_REGISTER` 判定） |
| GET | `/auth/read-token` | 免认证 | 围观凭据（仅 `AUTH_MODE=open`） |
| POST | `/auth/logout` | 本人凭据 | 吊销当前 token |
| POST | `/auth/change-password` | 本人凭据 | 改密（改后旧凭据失效） |
| POST | `/auth/delete-account` | 本人凭据 | 永久注销（级联吊销凭据 + 删除玩家实体，不可恢复） |
| GET | `/plays/{play_id}/web/{path}` | read / play / admin | 玩法包 `web/` 资源（视图 / 管理页组件；仅限本包目录） |

## 2. 管理端口（6289）

### 2.1 身份

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/register` `/auth/login` `/auth/agent-register` | 同玩家端口语义 |
| GET | `/meta` | 模式识别 |

### 2.2 玩法包（全局层，§4.3）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/plays` | 清单：名称/版本/状态（loaded/disabled/加载失败）/builtin 标志 |
| POST | `/admin/plays/install` | 安装社区包（请求体 = zip 字节流，`Content-Type: application/zip`） |
| POST | `/admin/plays/{play_id}/enable` | 启用（自动先启用 `requires.plays` 依赖） |
| POST | `/admin/plays/{play_id}/disable` | 停用（有已加载包依赖它 → 拒绝） |
| POST | `/admin/plays/{play_id}/uninstall` | 卸载社区包（删目录，**不可逆**；内置包拒绝） |
| GET | `/admin/overrides` | 原语覆盖 / 禁用 / 过滤器链状态（谁挂在哪个原语、顺序） |
| GET | `/admin/tools` | 已注册 MCP 工具 |
| GET | `/admin/views` | 已注册视图 |
| GET | `/admin/services` | 跨包服务清单 |

### 2.3 世界与组织树

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/admin/worlds` | 世界列表 / 新建（`{id, name, desc, play_ids}`） |
| PATCH / DELETE | `/admin/worlds/{world_id}` | 改名/描述/激活集合 / 删除 |
| POST | `/admin/worlds/{world_id}/assign-map` | 地图归属（`{map_id, folder_id?, sort?}`） |
| POST | `/admin/worlds/{world_id}/unassign-map` | 解除归属（`{map_id}`） |
| POST | `/admin/worlds/{world_id}/reorder` | 容器内序号绝对化（`{parent_id, items}`，拖拽落位用） |
| POST | `/admin/worlds/{world_id}/folders` | 新建文件夹（`{name, parent_id?, sort?}`） |
| PATCH / DELETE | `/admin/folders/{folder_id}` | 改名 / 改序号 ｜ 删除（非空拒绝，提示先上移内容） |
| POST | `/admin/folders/{folder_id}/move` | 移动文件夹（`{parent_id, sort?}`） |

### 2.4 地图 / 地块 / 连接 / 模板 / 实体

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/maps` | 全部地图（含 world_id / folder_id / sort / 地块数 / 实体数 / visible） |
| POST | `/admin/maps` | 新建（`{id, name, description?, timezone?, spawn_row?, spawn_col?, visible?}`） |
| GET | `/admin/maps/{map_id}` | 详情：`{map, locations, entities}`；`entities[].capabilities` = 合并能力（D19，按世界过滤后的真相） |
| PATCH | `/admin/maps/{map_id}` | 元数据局部更新；⚠ `spawn_row` / `spawn_col` **需成对提供**（只给其一，另一个按 0 落库） |
| DELETE | `/admin/maps/{map_id}` | 删除（图上有身份化实体 → 拒绝，G2） |
| POST | `/admin/maps/{map_id}/copy` | 复制另存（`{new_id, name?, world_id?, folder_id?, with_entities}`；身份化实体永不复制） |
| POST | `/admin/maps/{map_id}/move` | 搬家（`{world_id?, folder_id?, sort?}`；跨世界自动落世界根） |
| GET | `/admin/lint[?map_id=][&world_id=]` | 地图体检（死连接 / 孤立地块 / 出生点落空 / 实体悬空 / 未归属世界 / 空图，错误+提示两级） |
| POST | `/admin/locations` | 建/改地块（`{map_id, row, col, name, description?}`；`description` 缺省 = **清空**；文案必须是结构化 JSON，纯文本 → 400） |
| DELETE | `/admin/locations` | 删地块（请求体 `{map_id, row, col}`；身份化实体在场 → 拒绝） |
| POST | `/admin/locations/move` | 原子移动地块（`{map_id, row, col, to_row, to_col}`：自身坐标 + 全图指向它的连接 + 其上实体） |
| POST | `/admin/connections` | 更新一条出口槽（`{map_id, row, col, direction, enabled, paths}`，**整槽替换**，两个字段都要给全；路径 `label` 同文案格式） |
| GET | `/admin/templates[?scope=location\|entity]` | 模板清单（`source` = play / local） |
| POST | `/admin/templates` | 存模板（`{id, name, data, scope}`） |
| POST | `/admin/templates/apply` | 套用地块模板（`{template_id, map_id, row, col}`：同图目标按偏移平移、跨图原样） |
| DELETE | `/admin/templates/{template_id}` | 删模板 |
| GET | `/admin/kinds[?category=]` | 类型 + 标签名词表（`kinds` / `types`(隐式) / `tags`(显式)，含字段 schema、来源包） |
| POST | `/admin/entities` | 放置实体（`{kind, map_id, row, col, name?, desc?, attrs?, state?, tags?}`） |
| PATCH / DELETE | `/admin/entities/{entity_id}` | 改实体（含 tags / kind；身份化实体的 kind 锁定，D20）/ 删除（身份化实体拒绝） |

### 2.5 账户 / 凭据 / 邀请码

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/accounts?q=&role=&page=&page_size=&sort=` | 账户检索（分页；`sort` 默认 `created_desc`） |
| PATCH / DELETE | `/admin/accounts/{account_id}` | 改角色（改后吊销旧凭据）/ 删除账户 |
| GET | `/admin/accounts/{account_id}/tokens` | 该账户的凭据列表 |
| DELETE | `/admin/tokens/{token}` | 吊销单个凭据 |
| POST | `/admin/invite-codes` | 生成邀请码（`{count}`） |
| DELETE | `/admin/invite-codes/{code}` | 吊销邀请码 |

### 2.6 玩法包管理页（§4.6）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/play-pages` | 管理页导航清单（按 `(play_id, key)` 排序） |
| POST | `/admin/play-pages/{play_id}/{page_key}/{action}` | 代理调用玩法包注册的管理动作（锁内执行、异常隔离；仅 `tier=admin`） |
| GET | `/plays/{play_id}/web/{path}` | 管理页组件资源（带 Bearer 同源加载） |

## 3. 示例

```bash
# 登录拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:6289/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"***"}' | python -c 'import json,sys; print(json.load(sys.stdin)["token"]["token"])')
H="Authorization: Bearer $TOKEN"

# 地图清单 / 体检 / 建地块
curl -s -H "$H" http://127.0.0.1:6289/admin/maps
curl -s -H "$H" 'http://127.0.0.1:6289/admin/lint?world_id=default'
curl -s -X POST -H "$H" -H 'content-type: application/json' \
  -d '{"map_id":"default","row":2,"col":3,"name":"新地块"}' \
  http://127.0.0.1:6289/admin/locations

# 玩家端口：视图清单（带凭据 → 按调用者世界过滤）
curl -s -H "$H" http://127.0.0.1:6288/views

# MCP 握手（玩家端口；完整会话见 docs/PLAY_DEV.md §8）
curl -s -X POST http://127.0.0.1:6288/world/mcp \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

## 4. 已知边界（写在这里免得踩）

- **文案（`description` / 路径 `label`）只有结构化一种格式**：
  `{"periods": [{"start": "06:00", "end": "18:00", "items": [{"text": "白天", "weight": 1}]}]}`；
  `null` = 清空。纯字符串或结构非法 → **400**（消息里带格式示例），不会静默落盘。
- 数值参数（`row` / `col` / `page` / `count` …）传非数字会 **500**（不是 400）：
  管理端 handler 只捕 `WorldError`。见 `GAPS.md` G26。
- `?token=` 会进日志（SSE 的硬需求），公网部署请让反代过滤该 query。
- `/state` 是**全量快照**（按 G1 地图可见性过滤），不做隐身实体过滤；
  隐身过滤目前只作用于感知工具与 `/scene`（见 `GAPS.md` G12 尾巴）。
