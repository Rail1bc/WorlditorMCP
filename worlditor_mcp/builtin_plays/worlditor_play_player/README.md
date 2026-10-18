# worlditor_play_player（内置玩家包）

回答"玩家是什么"。内核不认识玩家：它只记**两本账**——这次请求以哪具实体行动（凭据指针）、
哪些实体属于哪个主体（实体上的 `core:account`）。本包把"化身"做成普通实体，并提供
造 / 列 / 切 / 退 / 续玩 的工具与跨包服务。

> **本 README 描述当前代码的契约。**
> 目标形态（1 主体 1 化身、离线/上线、出生点、空闲下线）见本目录 `DESIGN.md` §11.3，
> 那里会收窄多化身面——落地前以本 README 为准。

## 三个概念

| 概念 | 是什么 | 从哪读 |
|---|---|---|
| **主体（principal）** | 可登录的账户；稳定的键（换化身、重登都不变） | `api.caller_principal()`；`/meta` 的 `principal` |
| **行动实体** | 这次请求以哪具实体行动；可以为空（还没有化身） | `api.caller()`（`None` = 没有） |
| **化身** | 属于某主体的普通实体（带 `core:account`） | `api.query_entities(include_absent=True, where=lambda e: e.user_id == principal)` |

**没有 `local:player` 这种东西**（D45 已删除）：要判"这是不是人"一律看
`entity.is_account_bound()` / `entity.user_id`。

## 依赖强度：默认零依赖

| 强度 | 写法 | 谁需要 |
|---|---|---|
| **零依赖**（默认） | 直接 `api.caller()` 拿"我现在是谁" | 移动、交互、战斗、背包……绝大多数包 |
| **软依赖** | `list_services()` 探测 + `call_service("worlditor_play_player", …)` | 需要"我的全部化身"的包：队伍面板、切换角色、共号 UI |
| **硬依赖** | `requires.plays: ["worlditor_play_player"]` | 仅"没有玩家包就没有意义"的包 |

⚠ **硬依赖的真实代价**：`requires.plays` 是**全局包级**的——依赖未启用 → 依赖者直接加载失败；
`disable` / `uninstall` 在有依赖者时直接拒绝。而**世界激活是世界级**的（D15），
`call_service` **不做世界过滤**——某世界没启用本包，依赖者照样调得到服务（跨世界串味，见 GAPS G62）。
所以：**别让所有包硬依赖本包**，那会把它变成单点故障。

## 对外服务（当前三个）

| 服务 | 参数 | 返回 |
|---|---|---|
| `avatars_of` | `principal=""`（缺省 = 当前调用方） | `[{entity_id, name, map_id, row, col, in_world}]` |
| `active_avatar` | `principal=""` | 同上单条；没有则 `{}` |
| `switch_to` | `entity_id` | 切换后的摘要；只接受调用方自己的化身，否则报错 |

⚠ **在主体生命周期事件里要显式传 `principal`**：`on_principal_login` / `_logout` / `_deleted`
由 HTTP/CLI 路径触发，没有"当前调用者"上下文，缺省解析出来是空的。另外 `switch_to` 这类服务
拒绝时请抛 `WorldError`——`call_service` 的异常隔离会把其它异常统一换成
"服务执行出错，请稍后再试"，只有 `WorldError` 的文案会原样透出。

## 自己实现一个玩家包时，五个必须处理的点

1. **自举工具声明 `requires_entity=False`**（PLAY_DEV §7）：否则"创建第一具化身"自己就被挡住了。
2. **roster 从内核账本派生**，别再维护第二份名单：两份名单迟早不一致。
   要记的是**玩法状态**（"上次操作的是哪具"），那才放自己的 KV。
3. **落点自己定**（D45：内核没有出生点）：用 `api.list_locations()` 挑，或读自己的内容文件。
   挑不到（空世界）就造一具**不在世界上**的化身（合法状态，D36），等地图就绪再放进去。
4. **`act_as` 之前先校验归属**：内核不校验"这具是不是你的"（它没有名单），
   把客户端传来的 `entity_id` 直接交给 `api.act_as` 等于让任何人操控任何实体。
   反方向的 `claim_avatar` / `release_avatar` 由内核把关（只能认领/退掉自己主体的）。
5. **"登录后接着玩"只能做成惰性接管**（v0.8.0）：`api.act_as()` 写的是**凭据**指针，
   而凭据上下文**只在 MCP 工具 handler 里**存在——`on_principal_login` / `_logout` /
   `on_tick` 这些回调里没有凭据，在那里调会直接抛"需要连接上下文"；而登录签发的新凭据
   `entity_id` 从空开始。所以续玩落在**读侧自举工具**上：谁先被调用谁完成接管。

## 工具名不是契约

`player_whoami` / `player_avatars` / `player_create` / `player_switch` / `player_retire`
是当前实现的工具名，**不构成跨包契约**——玩家端界面按视图注册走，工具名由各包自定。

## 本包自己的数据

- 组件 `local:avatar`：本包眼里"这是一具化身"（纯标记，零读者；目标设计里改名为
  `worlditor_play_player:avatar`，见 `DESIGN.md` §11.3 f）。
- kv `active_avatar`：`{主体 → 上次操作的化身 id}`，续玩用（目标设计里删除）。
- 主体注销时 `on_principal_deleted` 清自己的记录。

## 测试

`tests/test_player.py` 随包：把本目录整份复制进 tmp 的 `plays/` 再加载，**真实走工具入口**
（`build_dynamic_tool` 的 wrapper），覆盖自举、切换、续玩、D14 保护、注销级联、停用保留、
`/views` 不过滤、主体事件不推 SSE。
