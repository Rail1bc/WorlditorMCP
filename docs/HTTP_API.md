# HTTP 端点参考（玩家端口 + 管理端口）

> 权威来源是代码：玩家端口 `worlditor_mcp/world/mcp/http.py`（路由组装在
> `build_http_app`），管理端口 `worlditor_mcp/admin.py`（`build_admin_app`）。
> 本文是给人看的地图——**改端点时请同步这里**。

## 0. 两个端口与档位（D16）

| 端口 | 默认 | 内容 |
|---|---|---|
| 玩家端口 | `6288`（`0.0.0.0`） | MCP + 游玩 WebUI + 快照/SSE + 注册登录 |
| 管理端口 | `6289`（`127.0.0.1`） | 管理 REST + 管理 WebUI（`--admin-port 0` 可关闭） |

- **档位（tier）**：`play`（玩家）/ `admin`（拥有者）。（v0.9 删除了 `read` 围观档：
  一个"只能看、不能做"的身份没有真实场景——未登录时 `/meta`、`/views` 本来就免认证，
  要看世界内容就得先有身份。）
- **认证**：`Authorization: Bearer <token>`；SSE 因浏览器 `EventSource` 不能带
  请求头，额外支持 `?token=<token>`——**该 query 会进服务器/反代访问日志**，
  别把它贴到公网日志里。
- **管理端口不信任端口隔离**：所有 `/admin/*` 一律要求 `tier=admin`（双保险，D16）。
- **公共路径（免认证）**：玩家端口 `/auth/register`、`/auth/login`、
  `/auth/agent-register`、`/meta`、`/views`，以及内置 WebUI
  静态资源 `/`、`/assets/*`、`/favicon.ico`。
  （免认证 = 不要求凭据；带凭据时仍会解析身份，`/views` 就依赖这一点按世界过滤。）
- **响应约定**：管理端写端点成功 `{"ok": true, "data": …}`，失败 `400
  {"error": "…"}`（`WorldError` 文案原样透出）；读端点直接返回数据对象。

## 1. 玩家端口（6288）

| 方法 | 路径 | 档位 | 说明 |
|---|---|---|---|
| POST/GET/DELETE | `/world/mcp` | play / admin | MCP streamable HTTP（工具调用入口） |
| GET | `/state` | play / admin | 全量快照：`{revision, tick, maps, locations, entities}`，按 G1 可见性过滤 private 地图；`revision`/`tick` = 变更游标（D28，实体各自也带）。**`entities[]` = 组件形态**（表结构 v13）：`{id, components, last_active_ts, revision, changed_tick}`——**没有顶层 `name` / `desc` / `user_id`，也没有 `kind` / `tags` / `map_id` / `row` / `col`**（能力 = 带没带那个组件，D41；位置在 `core:position` 里，D36，**不在投影里**）。名字/描述在 `components["core:info"]`、账户绑定在 `components["core:account"]`；读名字用 `components["core:info"]["name"]`，**缺失兜底 `id` 前 8 位**（DESIGN §12.4）。⚠ `/state` **不做隐身过滤**（G12 尾巴：只挡私有地图，不挡 `invisible` 实体），也**不过滤 `core:account`**（能读到别人的账户 id，见 GAPS G63）。地图对象**没有** `spawn_row` / `spawn_col`（D45） |
| GET | `/scene?entity_id=` | play / admin | 单实体场景 `{entity, scene, peers}`（含动作菜单；`entity_id` 缺省 = 调用者自己）。`entity` / `peers` 的实体形态同 `/state`（组件里放名字，无顶层 `name` / `desc` / `user_id`）。**D45/D46：没有化身是 200 空态**——`{entity: null, scene: null, peers: [], reason: "no_avatar", text: "你还没有角色…"}`；实体不在世界上（下线 / 收在容器里）同样是 200，`reason: "not_in_world"` 而 `entity` 照常返回 |
| GET | `/where` | play / admin | **页眉基础信息**（K-3）：`{entity_id, world: {id,name}\|null, map: {id,name}\|null, reason}`。页眉只要"世界名 + 地图名"，而唯一现成的来源 `/state` 是全量快照——为一个页眉把整个世界拉下来不划算。`reason`：`""`（正常）/ `no_avatar`（还没有化身，D45）/ `not_in_world`（下线或收在容器里，D36）——**都是合法状态，不是错误** |
| GET | `/events` | play / admin | SSE 事件流（`?token=` 支持）。⚠ 主体生命周期事件（登录/登出/注销）**不推 SSE**（D47：那等于把主体名册发给每个订阅者） |
| GET | `/views` | 免认证 | 视图清单 `{views: [{key,title,icon,layout,play_id,provider}]}`；**带凭据且有行动实体时按调用者所在世界过滤**（D15）；**没有化身时不过滤**（D46 / R9：否则"创建角色"的入口会跟着消失，人被困死在门口）。`layout`：`default` / `fullscreen`（K-6：`fullscreen` 视图自带整屏，壳层不画页眉、不进顶栏 tab 条） |
| GET | `/chrome` | **play / admin** | **壳层挂载点**（K-1）：玩家端页眉抽屉的列表 `{blocks: [...]}`。条目由玩法包用 `register_ui_hook("core:shell.menu", "after", provider)` 注入，**内核不放内容**——没有包时 `blocks` 是空数组，抽屉照常打开、底部「退出登录」仍在。**要认证**：它会执行玩法包代码（provider），返回内容可能是有权限的（与免认证的 `/views` 不同）。条目协议：`title` + `icon` + `data["view"]`（目标视图 key；**不是** `action`） |
| GET | `/meta` | 免认证 | `{"mode":"play","authenticated":bool}`（前端模式识别 + **连接身份状态**）。带有效凭据时补 `tier` / `entity_id` / `username` / `principal`（`principal` = 主体账户 id，**稳定的键**；`entity_id` 可能为空 = 还没有化身，D46）；无凭据或凭据解析不出 → `authenticated:false`（仍 200，登录页要用它判断端口模式）。前端启动时若本地存有 token 而这里是 `false`，就清掉凭据回登录页——否则删库/吊销后界面停在打不开任何东西的空壳上 |
| POST | `/auth/register` | 免认证 | 人类注册（`{username, password, invite_code?, admin_key?}`）→ 账户 + 凭据（**不建实体**，D45：返回的 `token.entity_id` 是空串，"我以哪具化身行动"由玩法包定） |
| POST | `/auth/login` | 免认证 | 人类登录 → `{"ok":true,"token":{…}}` |
| POST | `/auth/agent-register` | 免认证 | agent/脚本无密码自助注册（`{"name": "…"}`，按 `AUTH_MODE` / `ALLOW_AGENT_REGISTER` 判定） |
| POST | `/auth/logout` | 本人凭据 | 吊销当前 token |
| POST | `/auth/change-password` | 本人凭据 | 改密（改后旧凭据失效） |
| POST | `/auth/delete-account` | 本人凭据 | 永久注销（级联吊销凭据 + **删除该主体的全部化身** + 发 `on_principal_deleted`，不可恢复） |
| GET | `/plays/{play_id}/web/{path}` | read / play / admin | 玩法包 `web/` 资源（视图 / 管理页组件；仅限本包目录） |

## 2. 管理端口（6289）

### 2.1 身份

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/register` `/auth/login` `/auth/agent-register` | 同玩家端口语义 |
| GET | `/meta` | 模式识别 + 连接身份状态（同玩家端口语义，`mode` = `admin`） |

### 2.2 玩法包（全局层，§4.3）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/plays` | 清单：名称/版本/状态（loaded/disabled/加载失败）/builtin 标志 |
| POST | `/admin/plays/install` | 安装社区包（请求体 = zip 字节流，`Content-Type: application/zip`） |
| POST | `/admin/plays/{play_id}/enable` | 启用（自动先启用 `requires.plays` 依赖） |
| POST | `/admin/plays/{play_id}/disable` | 停用（有已加载包依赖它 → 拒绝） |
| POST | `/admin/plays/{play_id}/uninstall` | 卸载社区包（删目录，**不可逆**；内置包拒绝——当前内置的只有世界内容包 `worlditor_play_demo_world`，只能停用） |
| GET | `/admin/overrides` | 原语覆盖 / 禁用 / 过滤器链状态（谁挂在哪个原语、顺序） |
| GET | `/admin/tools` | 已注册 MCP 工具 |
| GET | `/admin/views` | 已注册视图 |
| GET | `/admin/services` | 跨包服务清单 |

### 2.3 世界与组织树

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/admin/worlds` | 世界列表 / 新建（`{id, name, desc, play_ids}`）。`play_ids` 三态（D55）：**`null` = 全部启用（默认）**、`[]` = 一个都不启用、数组 = 只启用这些 |
| PATCH / DELETE | `/admin/worlds/{world_id}` | 改名/描述/激活集合 / 删除。`play_ids`：**键不出现 = 不变**；`null` / `[]` / 数组分别表示"全部 / 一个都不启用 / 这些"（不能用"传 null 表示不改"——那正是 D55 修掉的歧义） |
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
| POST | `/admin/maps` | 新建（`{id, name, description?, timezone?, visible?, world_id?, folder_id?}`）。**没有 `spawn_row` / `spawn_col`**（D45：内核不存在出生点，落点是玩法包的事） |
| GET | `/admin/maps/{map_id}` | 详情：`{map, locations, entities}`；`entities[].capabilities` = 合并能力（D19，按世界过滤后的真相）。**实体形态同 `/state`**（名字在 `components["core:info"]`，无顶层 `name` / `desc` / `user_id`）。⚠ 这是**地图视角**：按 `core:position` 裁，**不在世界上的实体不在结果里**（要它们用 `GET /admin/entities`） |
| PATCH | `/admin/maps/{map_id}` | 元数据局部更新（`{name?, description?, timezone?, visible?}`；body 未提供的字段不变，`description=null` 清空）。**没有出生点字段**（D45） |
| DELETE | `/admin/maps/{map_id}` | 删除（图上还有**绑定了账户**的实体 → 拒绝，G2 / D42） |
| POST | `/admin/maps/{map_id}/copy` | 复制另存（`{new_id, name?, world_id?, folder_id?, with_entities}`；**绑定了账户的实体永不复制**，D42） |
| POST | `/admin/maps/{map_id}/move` | 搬家（`{world_id?, folder_id?, sort?}`；跨世界自动落世界根） |
| GET | `/admin/lint[?map_id=][&world_id=]` | 地图体检（死连接 / 孤立地块 / 实体悬空 / 未归属世界 / 空图，错误+提示两级）。⚠ **`spawn_missing` 已随 D45 删除**——内核没有出生点，也就没有"落空" |
| POST | `/admin/locations` | 建/改地块（`{map_id, row, col, name, description?}`；`description` 缺省 = **清空**；文案必须是结构化 JSON，纯文本 → 400） |
| DELETE | `/admin/locations` | 删地块（请求体 `{map_id, row, col}`；**绑定了账户的实体**在场 → 拒绝，D42） |
| POST | `/admin/locations/move` | 原子移动地块（`{map_id, row, col, to_row, to_col}`：自身坐标 + 全图指向它的连接 + 其上实体） |
| POST | `/admin/connections` | 更新一条出口槽（`{map_id, row, col, direction, enabled, paths}`，**整槽替换**，两个字段都要给全；路径 `label` 同文案格式） |
| GET | `/admin/templates[?scope=location\|entity]` | 模板清单（`source` = play / local） |
| POST | `/admin/templates` | 存模板（`{id, name, data, scope}`） |
| POST | `/admin/templates/apply` | 套用地块模板（`{template_id, map_id, row, col}`：同图目标按偏移平移、跨图原样） |
| DELETE | `/admin/templates/{template_id}` | 删模板 |
| GET | `/admin/kinds[?category=]` | **组件清单**（D41：只有一套声明）——`kinds[]` 每条 = `key` / `source` / `name` / `label` / `interactions` / `fields` / `categories`。旧的两区（`types` / `tags`，按 `implicit` 分）已随"类型 = 一组组件的预设归实体模板"删除 |
| GET | `/admin/orphan-components` | **组件诊断**（D44）：按来源分组的四象限——`components[]` 每条 = `source` / `state`（active / inactive / orphan / fictional）/ `package`（loaded / disabled / load_failed / invalid / uninstalled / none）/ `purgeable` / `keys` / `count` / `sample`。判定**先看目录在不在**（`/admin/plays` 只遍历磁盘上还在的包目录），再看 `status`——"在停用集合里"不等于"包还在" |
| POST | `/admin/orphan-components/purge` | **清理已卸载包的遗留组件**（D44）：`{source, keys?, dry_run?}`。**服务端强制只接受"包真的不在了"**（停用 / 加载失败 → 400）；`local:` 永不可清；`dry_run` 默认 **true**（先看影响面再删）；粒度按 source 或 `keys` 子集，**不支持按实体挑**；⚠ 不可逆（数据没了 + 该实体的这项能力也没了）；事件复用 `on_world_edited`（`{op: "purge_components", …}`） |
| GET | `/admin/entities[?absent=0\|1][&world_id=]` | **全部实体**（跨地图）——`entities[].capabilities` 同地图详情。**这是唯一能看见"不在世界上的实体"的入口**（D36：位置是可选的 `core:position`，玩家下线 / 物品在容器里 / 尚未投放的 NPC 都属此类；地图详情按坐标裁，一个都看不见）。`absent=1` 只列不在世界上的、`absent=0` 只列在世界的；响应另带 `total` / `absent` 计数 |
| POST | `/admin/entities` | 新建实体（`{kind?, name?, desc?, components?, tags?, map_id?, row?, col?}`）。**位置三参数要么全给、要么全不给**：给了 = 放进世界（写 `core:position`）；**一个都不给 = 造一个不在世界上的实体**；只给一部分 → 400（"半截位置"会被兜底成 `""` / `0`，把"忘了给"变成静默出现在 (0,0) 的实体）。`name` / `desc` 是**输入便利**：折进 `core:info` 组件，实体上没有这两列。**`name` 受显示名约束**（K-11：1–24 字符、去首尾空白、拒绝控制字符与双向文本，见 `PLAY_DEV.md`「显示名」）。`components` = 组件键 → 数据，键须为 `source:name` 信封；`kind` / `tags` 是**能力输入便利**（D41：落成组件键，裸名按 D41 解析）。响应 `{id, components}` |
| PATCH / DELETE | `/admin/entities/{entity_id}` | 改实体（`name` / `desc` / `components`（整体替换））/ 删除（**绑定了账户的实体**拒绝，D14 / D42）。**D41：没有 `kind` / `tags` 可改**——能力就是组件，加/摘能力 = 加/删组件键（单点增删请用组件原语，整块替换时记得把 `core:*` 一起带上，否则实体会离开世界）。`name` / `desc` 折进 `core:info` 组件——**只动这两个键**，不碰同组件其它数据。`desc` 传空串 = 删该键；**`name` 不能传空串**（K-11 起报错，不再"删键"）——要让名字回落到 `id` 前 8 位，用 `components` 整体替换时去掉 `core:info`。**`name` 受显示名约束**（K-11：1–24 字符、无控制字符/双向文本）。响应 `{id, components}` |

### 2.5 账户 / 凭据 / 邀请码

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/accounts?q=&role=&page=&page_size=&sort=` | 账户检索（分页；`sort` 默认 `created_desc`）。每行带 `entities`（**该主体的全部化身**，0/1/N；D46）与 `token_count` |
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
- **错误体统一 JSON**：所有 `HTTPException`（401 / 403 / 404 …）与业务失败
  （400）都返回 `{"error": "…"}`——v0.7.0 前 Starlette 默认把前者渲染成**纯文本**，
  客户端统一按 JSON 解析会崩（已修，见 `GAPS.md` G26）。
- **`WorldError` → 409 JSON**（v0.8.0）：内核业务错误（"地块不存在"、"实体不在任何地块"、
  "你还没有角色"）此前会穿成 **500** 空壳。D36 让"不在世界上"合法、D45 之后它更是默认
  状态，所以必须能明确回答。409 的含义是"请求本身合法，当前世界状态让它做不了"。
- 数值参数（`row` / `col` / `page` / `count` …）传非数字 → **400**
  `{"error": "…必须是整数：…"}`（v0.7.0 前是 500；G26 已修）。
- `?token=` 会进日志（SSE 的硬需求），公网部署请让反代过滤该 query。
- `/state` 是**全量快照**（按 G1 地图可见性过滤），不做隐身实体过滤；
  隐身过滤目前只作用于感知工具与 `/scene`（见 `GAPS.md` G12 尾巴）。
  ⚠ 它**也不过滤 `core:account`**——每个在场实体都把 `user_id` 带给所有能读 `/state` 的人
  （见 `GAPS.md` G63）。
- **增量刷新（D28）**：`/state` 顶部与每个实体都带 `revision`（全局单调写序号）
  与 `changed_tick`（tick 窗口）；SSE 事件 payload 也带全局 `revision`/`tick`。
  客户端缓存失效判定：`revision` 没变 = 世界没写盘；单实体用 `entity.revision`
  比对（相等 = 这条没被改过）。玩法包侧精确增量用
  `api.query_entities(changed_since_revision=cursor)`。
- **SSE 载荷形状**：**自定义事件的数据在 `data` 键下**，预置事件把各自字段摊在顶层。
  例：`{"event": "plays_changed", "ts": …, "entity": null, "revision": N, "tick": M,
  "data": {"reason": "install", "plays": ["worlditor_play_x"]}}`。
  `plays_changed` 由内核在玩法包 load_all / enable / disable / install / uninstall
  之后发出，**改世界激活集合**（`PATCH /admin/worlds/{id}` 带 `play_ids`）时也发
  （reason = `world_plays`）——**前端据此刷新 `/views`**，装/卸玩法包或改世界激活后
  玩家端不必整页刷新。注意：SSE 只发 `data:` 行、**没有 `id:` 行**，断线重连
  （`retry: 3000`）无法补发丢失的事件，客户端应把 `/state` 快照当作兜底。
  （v0.9 删除了 `read` 围观档，`/events` 现在只有 play / admin 两档。）
- **实体查询（D26）不走 HTTP**：`query_entities` 是玩法包/内核 API（`api.query_entities`），
  面向 agent 的查询能力由玩法包自己注册 MCP 工具暴露。
