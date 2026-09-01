# 玩法包开发指南（PLAY_DEV）

> worlditor 的所有**行为**都由玩法包承载：内核只有数据 + 原语 + 注册表。
> 内置 5 个领域包（`worlditor_mcp/builtin_plays/`）即参考实现；社区包
> 放 `<数据目录>/plays/worlditor_play_*/`。本文档 = 玩法包唯一权威开发说明
> （与 DESIGN.md 一致；GAPS.md 记录平台缺口历史）。
>
> **SDK 稳定出口**：玩法包只允许 `from worlditor_mcp.world.play.api import
> WorlditorPlayAPI` 与 `from worlditor_mcp.world import ...`（WorldError /
> 数据模型 / DIRECTIONS）——**禁止 import 内核内部模块**（engine / store /
> model 路径可能随重构变化，已据此统一全部内置包）。

---

## 1. 最小示例

`worlditor_play_hello/` 目录（两个文件）：

`play.yaml`：

```yaml
name: worlditor_play_hello
display_name: 问候
version: 0.1.0
author: 你
desc: 一个打招呼的玩法包
requires:
  worlditor: ">=0.1.0"
  plays: []          # 依赖的其他玩法包（拓扑加载，先加载被依赖者）
```

`main.py`：

```python
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world import WorldError


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口：注册能力（工具/事件/服务/视图/原语覆盖...）。"""
    api.register_tool(
        "hello",
        _hello,
        description="向世界打个招呼。",
    )


async def _hello(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    me = api.caller()          # 当前调用者实体 id（MCP 工具 handler 内有效）
    if me is None:
        raise WorldError("无法确定调用者身份")
    entity = api.get_entity(me)
    return {"text": f"你好，我是 {entity.name}！"}


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子（可选）：取消自管 task、清理自管资源。"""
```

管理端（6289）启用后，玩家/agent 即可通过 MCP 调用 `hello` 工具。

## 2. 包结构

```
worlditor_play_xxx/
├── play.yaml        # 元数据（必填：name/display_name/version/requires）
├── main.py          # setup(api, context) 入口（必填）
├── data/            # 自有数据文件（只读访问；写操作走 api.kv_*）
└── web/             # 视图组件 JS（register_view 的 provider.url 指向这里）
```

- play_id = `name`，必须 `worlditor_play_` 前缀；命名 `^[A-Za-z0-9_-]+$`
- `requires.plays`：依赖的玩法包 id 列表——加载拓扑保证先加载；enable 时自动先启用依赖；disable 时仍有依赖者则拒绝
- **内置包 vs 社区包**：内置包随服务分发（只读，可停用不可卸载）；社区包在数据目录（可卸载，卸载删目录含数据，不可逆）

## 3. 生命周期

```
load_all / enable(play_id)  →  import main → setup(api, context)
  │                             （异常 → 加载失败，原因管理页可见，半注册回滚）
  ▼
运行中：工具/事件/过滤器/服务按需被调用
  │
disable(play_id) / 服务关闭 → teardown(api) → 注册表按 play_id 清理
                                  （过滤器/覆盖自动清除 → 内核恢复默认实现）
```

- **世界激活（D15）**：玩法包全局加载一次；事件/交互/感知按实体所在世界的
  `worlds.play_ids` 激活集合过滤分发（on_tick 例外，不过滤）
- **数据隔离**：`api.kv_*` 的 namespace = 本包 id（或 `世界id:包id` 双层）——
  不同玩法包互不可见；同包跨世界各自状态
- **disable 保留数据**：只卸载代码注册，kv/data/web 资源保留，enable 即恢复

## 4. API 参考（WorlditorPlayAPI 全量）

### 注册

| API | 说明 |
|---|---|
| `register_item_def(item, fields=[])` | 物品类型定义（内核注册表；同 id 覆盖更新） |
| `add_item_fields(item_id, fields)` | 向已有物品类型追加字段（D9） |
| `register_entity_kind(kind, block_move, interactions, tick, label, fields, categories)` | 实体类型元数据；`interactions` = 该 kind 默认可用的动作名 |
| `add_kind_fields(kind, fields)` / `add_category_fields(category, fields)` | 向 kind / 分类追加字段（D9/D10） |
| `list_kinds(category=None)` | kind 列表（含字段 schema），分类过滤 |
| `register_interaction(action, handler, label)` | 全局交互动作；`async (api, req) -> InteractionResult` |
| `register_world_event(event, handler, interval=0)` | 事件订阅；on_tick 必须给 interval（秒） |
| `register_ui_component(name, web_entry)` / `register_ui_hook(block_kind, position, provider)` | 自定义界面组件 / UiBlock 注入（before/after/replace） |
| `register_tool(name, handler, description, params)` | MCP 工具（见 §7） |
| `register_view(key, title, icon, provider)` | WebUI 视图（见 §8） |
| `register_service(name, handler)` | 跨包服务（见 §6） |
| `override_primitive(name, handler)` / `disable_primitive(name)` | 原语覆盖 / 禁用（见 §5） |
| `register_primitive_filter(name, filter, label)` | 原语过滤器（见 §5） |

### 只读

| API | 说明 |
|---|---|
| `get_entity(id)` / `list_entities(map_id, row, col, viewer_id)` | 实体；**viewer_id 感知过滤（G12）**：隐藏 `attrs.invisible` 实体，viewer 自身 `see_invisible` 真视 |
| `get_location(map_id, row, col)` / `get_map(map_id)` | 地块 / 地图（Location 含 connections） |
| `list_actions(target_id)` | 目标可用动作按钮（UI 菜单） |
| `list_worlds()` / `get_world(id)` / `entity_world(id)` / `map_world(id)` | 世界与归属（D15） |
| `list_folders(world_id)` / `list_maps_by_folder(world_id, folder_id)` | 组织树 |
| `kv_get(key, default, world_id)` / `kv_set(key, value, world_id)` | 玩法数据 KV（namespace = 本包） |
| `list_world_log(limit=100)` | 世界日志（最新在前） |
| `list_primitive_overrides()` / `list_primitive_filters()` / `list_services()` / `list_views()` | 注册表状态（管理页同源） |

### 动作（引擎原语，锁内执行）

| API | 说明 |
|---|---|
| `move(entity_id, direction, path=None)` | 路径移动（**分派入口**：可被过滤器改写/覆盖，返回 SceneView） |
| `move_entity(entity_id, map_id, row, col)` | 直接位移（行为驱动，不做阻挡检查） |
| `set_attrs(entity_id, patch)` / `get_attrs(entity_id)` | 实体 attrs（玩法数据）合并读写（不经原语分派） |
| `set_data(entity_id, name, value)` / `get_data(entity_id, name)` | 字段原语（**可被覆盖/禁用**，D11）；读写容器 = attrs，与 `set_attrs` 同容器 |
| `interact(entity_id, target_id, action, args, item_id)` | 交互（**可被覆盖/禁用**） |
| `emit(event, data, log=False)` | 自定义事件（SSE 推送；`log=True` 写 world_log） |
| `place_entity(kind, map_id, row, col, ...)` / `remove_entity(id)` | 实体生命周期（D14；身份化实体不可 remove） |
| `set_state(entity_id, patch)` / `get_state(entity_id)` | 实体 state（门开/关、动态状态） |
| `call_service(play_id, name, **params)` | 跨包服务调用（§6） |
| `call_default_primitive(name, *args, **kwargs)` | super 通道：显式调内核默认实现（覆盖者前置/后置用） |

### 地图编辑（D14：内容治理归玩法包/用户）

`update_location(map_id, row, col, **kwargs)` / `update_connection(map_id, row, col, direction, **kwargs)` / `create_map(map_id, name, ...)` / `delete_map(map_id)`（图上玩家在场拒绝，G2）/ `save_template(template)` / `delete_template(template_id)`

### 身份

`caller()`：当前调用者实体 id（MCP 工具 handler 内有效；身份经请求 `_meta` 注入）。无身份返回 `None`。

**账户生命周期（内核提供，玩法包感知）**：
- 玩家可永久注销（`POST /auth/delete-account`，级联吊销凭据 + 删除玩家实体）；管理员可删除账户/变更角色（`PATCH /admin/accounts/{id}`，变更即吊销旧凭据强制重登）
- **对玩法包的影响**：注销 = 身份化实体被**受控删除**（非玩法包 remove_entity 通道），会触发 `on_entity_removed` / `on_world_edited`——需要按实体清理自身数据的包订阅该事件（如 items 包背包、social 包冷却）

## 5. 原语覆盖与过滤器链（D11 / G14）

5 个可覆盖原语：`move` / `move_entity` / `set_data` / `get_data` / `interact`。

**override**（整体替换）：`override_primitive(name, handler)`——handler
`async (api, *args, **kwargs)` 锁内回调；可调 `api.call_default_primitive`
走默认实现（前置/后置条件）。**disable**（禁用）：调用报"该能力已被禁用"。

**过滤器链**（G14，推荐）：`register_primitive_filter(name, filter, label)`——
多个过滤器按注册序执行，三态：

| 行为 | 写法 |
|---|---|
| 否决 | `raise WorldError("原因")` → 本次调用失败 |
| 参数改写 | 返回参数字典 → 继续链（后续过滤器与默认实现收到改写后的参数） |
| 短路 | `return ShortCircuit(value)` → 直接作为结果，跳过后续与默认实现 |

- 链尾 = 内核默认实现；**过滤器约定纯函数**（只读、不改世界——世界变更只发生在默认实现；需要改状态的逻辑放 override 或工具 handler）
- **与 override/disable 互斥**：原语已挂过滤器时登记 override 报错，反之亦然
- 同包可注册多个过滤器（各带 label）；生命周期随包卸载自动清理（内核恢复默认）
- 管理页可见（谁、顺序）

> 经典用法：movement 包的"相对方向换算"过滤器（forward/back/left/right →
> 绝对方向）、束缚/锁血/遮蔽类效果包。

## 6. 跨包服务（M3：玩法包间同步调用）

玩法包的数据在自己 namespace 里，其他包**不能直接读写**——跨包协作走服务：

```python
# 提供方（如 items 包）：
api.register_service("bag_add", _bag_add)   # async (api, **params) -> Any
                                            # api = 提供方自己的 API 实例

# 调用方（如 player 包）：
total = await api.call_service("worlditor_play_items", "bag_add",
                               entity_id=..., item_id="apple", count=3)
```

- 服务在**引擎锁内**执行（读改写原子）；异常隔离（服务炸了不拖垮调用方，报"服务执行出错"）
- 服务名同包冲突报错；生命周期随包卸载清理（调用立即报"服务不存在"）
- 管理页 `/admin/services` 可见（谁提供了什么）
- 信任边界：玩法包间互信（社区包都是管理员装的）；跨包权限约定见 §11

> 内置参考：items 包提供 `bag_add/bag_take/bag_count/bag_get` 四个服务；
> player 包出生礼包、interaction 包商贩交易、social 包喇叭消耗都经服务调用。

## 7. MCP 工具

```python
api.register_tool(
    "world_look",
    _world_look,
    description="查看 3×3 视野……（agent 的世界观入口，写清楚！）",
    params={"direction": "string", "path": "integer"},  # 可选：声明了即可选
)
```

- handler 签名 `async (api, ctx, **args) -> str | dict`；返回 `{"text": ...}` 或
  `{"text": ..., "ui": ...}`；dict 会被 JSON 序列化为 MCP 文本内容
- **参数类型**：`string` / `integer` / `number` / `boolean` / `array`
  （array = `list[str]`，G11）；**声明参数即可选**（缺省 None），必填校验由
  handler 自己完成（`raise WorldError("xxx 必填")`）
- 同名工具冲突报错（D2）；工具随包卸载自动从 MCP server 移除
- 身份：handler 内 `api.caller()` 读取调用者；**工具是 agent 的唯一动作通道**，
  权限（谁能做什么）由玩法包自行裁定（参考 items 包"只看自己背包"）

## 8. 视图（WebUI）

```python
api.register_view(
    "movement",
    title="世界",
    icon="🗺️",
    provider={"type": "component", "url": f"/plays/{api.play_id}/web/view.js"},
)
```

`web/view.js` 是**视图组件协议**文件——`new Function("Vue", "UiBlock", code)`
动态加载，文件体即函数体：

```js
(function (Vue, UiBlock) {
  const { ref, onMounted, h } = Vue;
  // ...组件实现（Vue 组件选项：props {view}, setup, render）
  return { name: "XxxView", props: { view: Object }, setup() { ... } };
})
```

- 组件 props 收到 `view`（注册元数据）；**数据通道 = MCP 工具**（视图内嵌轻量
  callTool，见内置包 `web/*.js` 参考）或只读 REST（/scene 等），不新增数据通道（D7）
- **请求需带 Bearer**：`/plays/<id>/web/*`、`/scene` 等要求认证——视图内部
  fetch 一律带 `Authorization: Bearer <localStorage 的 worlditor_token>`（内置包示例）
- `UiBlock` 参数 = 内核 UiBlockRenderer 组件（用 UiBlock 树渲染列表/表单/文本
  免写组件；复杂界面直接写 Vue）
- 兜底：无任何视图时 WebUI 显示内核"无视图"提示（D7）
- `/meta` 返回 `{mode: "play"|"admin"}`：同一前端按端口切换界面（玩家视图宿主
  vs 管理面板）——视图只在玩家模式加载（D16 界面分离）

## 9. 事件

预置事件（WORLD_EVENTS，订阅签名）：

| 事件 | 签名 |
|---|---|
| `on_tick` | `(api, dt)`——必须给 interval（秒）；tick 粒度 1s（G3 观察项） |
| `on_entity_move` | `(api, entity, from_pos, to_pos)` |
| `on_entity_enter` | `(api, entity, map_id, row, col)` |
| `on_interact` | `(api, request, result)` |
| `on_item_used` | `(api, entity, item_id, args, result)`（D8：无 count，持有数自管） |
| `on_entity_removed` | `(api, entity)` |
| `on_entity_changed` | `(api, entity, changed)` |
| `on_world_edited` | `(api, what)`——`{op: "place_entity"|"remove_entity"|..., entity_id}` |

自定义事件（G8/D1）：`api.emit("say", {...}, log=True)`——任意事件名，
SSE 推送；`log=True` 才写 world_log（高频事件勿写，5000 条上限）。
**说话/广播通道 = 自定义事件**（内核无 say）。

## 10. 字段设施（D9/D10）

- 实体数据 = attrs（玩法数据，内核不解释）+ state（动态状态）；kind 注册可声明
  字段 schema `{name, label, type, default?}`（type: str/int/float/bool/json）
- **两套字段读写**：`set_attrs`（合并写、不经分派，日常推荐）与 `set_data`
  （走原语分派，可被其他包 override/过滤器拦截）**都写 attrs**，对同一实体
  二选一即可；`state` 独立（`set_state`/`get_state`，门开/关、`block_move`
  动态覆盖等，不经分派），两者互不干扰
- 分类字段：`add_category_fields` 使该分类全部 kind 获得字段；有效字段 =
  kind 声明 ∪ 分类声明（运行时合并）；实例可写任意未声明字段（buff 等临时效果）
- 物品定义同构（ItemDef + 字段）

## 11. 约定与规范

### 命名契约（G6，社区共同遵守）

| 领域 | 建议字段/事件名 |
|---|---|
| 朝向 | attrs `facing`（up/right/down/left，默认 up）——movement 包 |
| 金币 | attrs `gold`——interaction/player 包 |
| 精力 | attrs `energy`——interaction 包（eat 效果） |
| 说话 | 事件 `say`（cell）/ `broadcast`（world）——social 包 |
| 礼包标记 | attrs `starter_granted`——player 包 |
| 广播冷却 | kv `broadcast_cd:<entity_id>`——social 包 |

跨包读写**约定字段**前先查提供方包的服务/文档；通用字段建议进本表（PR 更新）。

### 编辑权限（G7）

编辑地图/实体前**先查其 ACL**：家地图的写权限由家玩法包判定（读其服务/
记录），内核不做"家"概念强制（D14：内容治理责任归玩法包）。示例：
interaction 包商贩交易 = 金币 attrs + items 服务，无内核强制。

### 性能与并发（G5）

- **handler 在引擎锁内执行**：保持短小（毫秒级）；长耗时任务（LLM 调用、
  网络、重计算）**自管 asyncio task**，在 `teardown(api)` 中取消
- 过滤器必须纯函数（只读）；世界变更只发生在默认实现
- 事件 handler 异常被隔离（记日志不拖垮内核）；交互 handler 异常转可展示错误

### 通用

- 中文注释/文案（本项目语言）；日志用 `logging.getLogger("worlditor")` 风格
- 工具 description 写清楚**给 agent 看**（世界观入口，G9 观察项）
- 管理端可见性：注册的东西（工具/视图/服务/过滤器/覆盖）都会显示在管理页，
  命名要人能看懂（label 字段）

## 12. 内置领域包一览（参考实现）

| 包 | 能力 | 关键机制 |
|---|---|---|
| `worlditor_play_movement` | 朝向移动 + 3×3 视野 + world_look/move/turn/who | move 过滤器（相对方向换算）+ register_view |
| `worlditor_play_items` | 背包（20 格/堆叠 99）+ world_bag/use + 苹果/面包 | **服务** bag_add/take/count/get；持有下沉（D8） |
| `worlditor_play_player` | 出生礼包 + 角色视图 + world_profile | 事件 on_world_edited + 跨包服务 |
| `worlditor_play_interaction` | 种子实体 kind/交互 + world_interact | 商贩交易跨包；door block_move |
| `worlditor_play_social` | cell 说话 + world 广播（喇叭+冷却）+ 日志视图 | 自定义事件 + kv 冷却自管 |

> 想看真实代码？`worlditor_mcp/builtin_plays/` 每个包就是一个完整示例。
