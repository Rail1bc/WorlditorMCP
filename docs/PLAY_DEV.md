# 玩法包开发指南（PLAY_DEV）

> worlditor 的所有**行为**都由玩法包承载：内核只有数据 + 原语 + 注册表。
> **v0.7.0 起 6 个内置领域包已删除**——行为玩法包不再随仓库分发；行为包的
> 参考实现 = 测试夹具包（`tests/play_fixtures.py` 装入的 `worlditor_play_demo`，
> 组件文件提交在案：`tests/fixtures/plays/worlditor_play_demo/web/`，见 §12）；
> 社区包放 `<数据目录>/plays/worlditor_play_*/`。本文档 = 玩法包唯一权威开发说明
> （与 DESIGN.md 一致；GAPS.md 记录平台缺口历史）。
>
> **SDK 稳定出口**：玩法包只允许 `from worlditor_mcp.world.play.api import
> WorlditorPlayAPI` 与 `from worlditor_mcp.world import ...`（WorldError /
> 数据模型 / DIRECTIONS）——**禁止 import 内核内部模块**（engine / store /
> model 路径可能随重构变化；该约束对内置包与社区包一体适用）。

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
├── play.yaml        # 元数据（必填：name / version；display_name、requires 可省）
├── main.py          # setup(api, context) 入口（必填）
├── helper.py        # 自己的辅助模块（可选，包内用**相对导入**引用）
├── data/            # 自有数据文件（只读访问；写操作走 api.kv_*）
└── web/             # 视图组件 JS（register_view 的 provider.url 指向这里）
```

- play_id = `play.yaml` 的 `name`，必须 `worlditor_play_` 前缀（**加载的硬条件**：
  没有前缀的目录会被直接跳过，手工放进 `plays/` 也不会出现在管理页里）
- **多文件包（v0.7.3 起）**：`main.py` 作为包 `worlditor_play_xxx` 加载、`__path__`
  指向包目录——包内写 `from . import helper` / `from .helper import f` 即可。
  ⚠ **包内一律用相对导入**：`import helper`（绝对、不带点）会 `ModuleNotFoundError`
  ——这是刻意的：绝对导入全进程抢同一个裸模块名，两个包各有 `helper.py` 时后加载的
  会**静默拿到别人的模块**（本地实测：B 包跑出了 A 包的 helper），而且把包目录放进
  `sys.path` 还会遮蔽标准库同名的模块
- 停用/卸载时内核清掉 `sys.modules` 里该包的全部模块（含子模块），所以"改代码 →
  停用 → 启用"能拿到新代码。⚠ 改文件要**改到字节数不同**：`__pycache__` 的有效性
  判据是"mtime + 大小"，同一秒内改出同样大小的文件时 CPython 会继续用旧 `.pyc`
  （解释器行为，不是内核的问题）
- zip 安装（管理端上传）额外要求：顶层目录**只有一个**、目录名 **== `name`**、
  且匹配 `^[A-Za-z0-9_-]+$`（安装与卸载都按目录名定位，不一致会"装得上却卸不掉"）
- `requires.plays`：依赖的玩法包 id 列表——加载拓扑保证先加载；enable 时自动先启用依赖；disable 时仍有依赖者则拒绝
- **内置包 vs 社区包**：内置包随服务分发（只读，可停用不可卸载）；社区包在数据目录（可卸载：**删包目录**，不可逆）。**卸载不会删你的 `play_data` KV**（同名重装数据会回来；要清数据得自己动手，见 GAPS G49）。**内置目录 `worlditor_mcp/builtin_plays/` 现在只剩世界内容包** `worlditor_play_demo_world`——行为玩法包（工具/视图/服务/过滤器/组件声明）不再内置，参考实现见 §12

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

- **setup 可为同步或 async**（v0.2.0 起内核 `await` 返回值）：需要写世界的
  「世界包」用 `async def setup(...)`，例如内置 `worlditor_play_demo_world`
  在 setup 里导入地图/地块/实体（幂等，地图已存在则跳过、不覆盖用户改动）
- **世界激活（D15 / v0.3.0 全路径生效）**：玩法包全局加载一次，**世界声明
  激活集合**（`worlds.play_ids`，空 = 全部启用；管理端「世界 › 玩法包」里
  逐个开关）。某世界未激活你的包时，你在**那个世界**整体不存在：
  | 你注册的东西 | 该世界里的表现 |
  |---|---|
  | MCP 工具 | 调用被拒："该世界未启用该玩法包"（不执行 handler） |
  | 玩家视图 | tab 不出现（`GET /views` 按调用者世界过滤） |
  | 交互动作 | 不可用，动作菜单里也不列 |
  | 事件订阅 | 不触发（on_tick 例外，始终触发） |
  | 原语覆盖/过滤器 | 不生效 → 回落内核默认实现 |
  | 标签/类型声明（动作/字段） | **逐标签过滤**（D21）：你声明的标签不参与并集——不声明动作、不贡献字段 |
  | 实体模板（`register_entity_template`） | **当前未按世界过滤**（`list_templates` 只有 scope 参数）——只有整个包被停用/卸载时才消失；要按世界分模板请自行判断（见 GAPS G52） |
  | ui_hook 注入 | 不注入 |
  > 写包须知：**不要假设自己的工具在任何世界都能调用**（尤其跨世界共享的
  > agent）；也不要依赖"自己的过滤器一定生效"——按世界启停是管理员的权利。
  > 需要"所有世界都必须有"的能力，用**全局层**（`enable`，管理端高级操作）。
  > **标签同理**：你声明的标签只在启用了你的包的世界里贡献能力（D21）。
  未归属世界的地图按**默认世界**的激活集合算（不会逃逸过滤）。
- **数据隔离**：`api.kv_*` 的 namespace = 本包 id（或 `世界id:包id` 双层）——
  不同玩法包互不可见；同包跨世界各自状态
- **disable 保留数据**：只卸载代码注册，kv/data/web 资源保留，enable 即恢复。
  **实体上的组件一律不动**（D41/D44：能力 = 组件的存在）——停用后实体照常带着那些组件，
  `capabilities()` 把它们报成 `orphan_components`（"包没加载"），启用即恢复行为

- **安装/分发**：包目录放到 `<数据目录>/plays/`（或管理端「安装玩法包（zip）」
  上传：zip 内单个顶层目录 `<play_id>/`，含 play.yaml 与 main.py）；内置包
  随版本分发、只可停用不可卸载

## 4. API 参考（WorlditorPlayAPI 全量）

### 注册

> 签名里的 `*` 表示**其后都是关键字参数**（必须写成 `title="…"` 这种形式）；
> 参数名以源码为准（按位置传参会 TypeError）。

| API | 说明 |
|---|---|
| `declare_component(name, *, interactions=(), label=None, fields=None, categories=())` | **声明一个组件**（D41：唯一入口）。组件名 = `source:name`：裸名自动带上你包的 id（`declare_component("merchant")` → `<你的 play_id>:merchant`）；也可以显式写**自己的包名**或共享的 **`local:`**（内容/行为对接用，见下）。带某组件 = 具备该能力（纯能力组件数据是 `{}`） |
| `register_entity_kind(kind, *, interactions=(), label=None, fields=None, categories=(), tags=())` | `declare_component` 的旧名（等价，新代码建议用 `declare_component`）；⚠ `tags=` 参数**已作废**（"类型 = 一组组件的预设"归**实体模板**，传非空值报错） |
| `register_entity_tag(tag, *, label=None, interactions=(), fields=None, categories=())` | `declare_component` 的另一个旧名（等价） |
| `register_entity_type(kind, ...)` | 同上（"类型只是预设"这个读法已过时——预设归实体模板） |
| `add_tag_fields(tag, fields)` / `add_kind_fields(kind, fields)` | 给**一个组件**追加字段（D41：跨包扩展的正当路径）。**同一组件内同名字段重复声明 → 报错**；字段清单**按组件分组**，不跨组件摊平。⚠ `add_category_fields` **已删除** |
| `list_kinds(category=None)` | **组件清单**：`key` / `source` / `name` / `label` / `interactions` / `fields` / `categories`（没有"是否隐式""预设标签"了），`category` 只是选取分组 |
| `capabilities(entity)` | 某实体的能力：`components / active_components / inactive_components / **orphan_components** / **fictional_components** / interactions / fields`——`fields` 是 **`{组件键: [字段]}`**（按组件分组）。四象限（D44）：生效 / 本世界未启用 / **声明它的包不在了**（停用、加载失败、已卸载）/ **虚构组件**（`local:` 且无声明——本来就没有行为，不是坏了）。**不再有阻挡键**（阻挡机制已移除，见 §10） |
| `register_interaction(action, handler, *, label=None)` | 全局交互动作；`async (api, req) -> InteractionResult`。⚠ 同名动作**报错拒绝**（不会静默顶掉别人的） |
| `register_world_event(event, handler, *, interval=0.0, phase="simulate", order=0)` | 事件订阅；on_tick 必须给 interval（秒）；**phase/order 声明跨包执行顺序**（D27，见 §5.3） |
| `register_ui_hook(block_kind, position, provider)` | UiBlock 注入（before/after/replace，**可用**；服务端展开，见 §11） |
| `register_ui_hook(block_kind, position, provider)` | UiBlock 注入（before/after/replace，可用）；自定义页面请使用 `register_view` + provider（§8）。`UiBlock(kind="custom")` 只保留 fallback 数据结构，不提供组件注册 API |
| `apply_ui_hooks(block)` | 对一棵 UiBlock 树应用全部已注册钩子（服务端展开，锁内）；玩家壳生成角色卡后调它，部件包的面板即被追加（§11） |
| `register_tool(name, handler, *, description="", params=None)` | MCP 工具（见 §7） |
| `register_view(key, *, title, icon="", provider=None)` | WebUI 视图（见 §8）；`title` 必填且**只能关键字传** |
| `register_service(name, handler)` | 跨包服务（见 §6） |
| `override_primitive(name, handler)` / `disable_primitive(name)` | 原语覆盖 / 禁用（见 §5） |
| `register_primitive_filter(name, filter, *, label="")` | 原语过滤器（见 §5） |

> **物品不在内核（v2 / D37）**：内核没有 `ItemDef`、没有 `items` 表，也没有物品注册 /
> 落库 API（`register_item_def` / `save_item_def` / `add_item_fields` / `get_item_def` /
> `list_item_defs` / `delete_item_def` / `flush_item_defs` 全删）。**内核只有实体**——
> 物品的定义与持有都下沉玩法包：
>
> | 原来（内核物品） | 现在（你的包） |
> |---|---|
> | 物品**类型**定义 | **组件声明**（`register_entity_tag`：名字 + 字段 schema + 归属） |
> | 物品**实例** | **实体 + 组件**（在地上 = 一个实体带该组件；在背包里 = 本包自己的 kv） |
> | `use_action` | **interaction 名**（`TagSpec.interactions` 完全覆盖，用 `register_interaction` 实现） |
> | `stackable` / `icon` | 组件声明的属性与字段（`fields` 里自定；`icon` 只是本包的 UI 约定） |
> | 管理员手工物品（`user_data`，停用包不消失） | **实体模板**（`register_entity_template` 随包卸载消失 / `save_template` 落 `templates` 表，不受影响；见 §4 地图编辑） |
> | `interact(..., item_id=…)` | `interact(..., args={"item": "apple"})`（`args` 自由 dict，内核不解释其内容） |
> | `on_item_used` 内核事件 | 玩法包**自定义事件**（`api.emit("item_used", {...})`，事件总线支持任意事件名，§9） |

### 只读

| API | 说明 |
|---|---|
| `get_entity(entity_id)` / `list_entities(map_id, row, col, viewer_id, *, include_absent=False)` | 实体（位置筛选，宽松：地图不存在 = 空列表）；**viewer_id 感知过滤（G12）**：隐藏 `core:perception` 里 `invisible` 为真的实体，viewer 自身 `see_invisible` 真视（§10）。`include_absent=True` 连**不在世界上**的实体一起拿（D36，见 `place_entity` 那行） |
| `list_components(entity_id)` / `get_component(entity_id, component)` | 组件整块读（**只读，不进原语分派表**）：组件名列表（稳定排序）/ 组件数据（不存在 = `None`）；见 §10 |
| `query_entities(*, tags, exclude_tags, map_id, world_id, row, col, viewer_id, changed_since_tick, changed_since_revision, where, limit, include_absent=False)` | **实体查询（D26，见 §5.2）**：按标签查一批实体，不再需要"全量拿 + 自己筛"；同样支持 `include_absent` |
| `current_tick()` / `world_revision()` | 变更游标（D28）：tick 窗口号 / 全局变更号（见 §5.4） |
| `get_location(map_id, row, col)` / `get_map(map_id)` | 地块 / 地图（Location 含 connections） |
| `list_locations(map_id=None)` / `list_maps()` | 地块 / 地图**清单**（只读，深拷贝）。**"人从哪来"是玩法的事**（D45：内核没有出生点）——想把人放进世界的包得先看得见地块与地图，否则只能猜坐标 |
| `list_actions(target_id, *, viewer_id=None, tier="")` | 目标可用动作按钮（UI 菜单）。传 `viewer_id`（+`tier`）时先过观察权限：看不见的目标（隐身 / 私有地图）返回**空菜单**——玩法包自建界面也能按感知过滤 |
| `list_worlds()` / `get_world(world_id)` / `entity_world(entity_id)` / `map_world(map_id)` | 世界与归属（D15） |
| `list_folders(world_id)` / `list_maps_by_folder(world_id, folder_id)` | 组织树（按容器内序号排序） |
| `list_admin_pages()` | 管理端管理页清单（§13；导航/调试用） |
| `kv_get(key, default=None, *, world_id=None)` / `kv_set(key, value, *, world_id=None)` | 玩法数据 KV（namespace = 本包）。⚠ `kv_get` 是**同步**、`kv_set` 是 **async**（`await`） |
| `list_world_log(limit=100)` | 世界日志（最新在前） |
| `list_primitive_overrides()` / `list_primitive_filters()` / `list_services()` / `list_views()` | 注册表状态（管理页同源） |

> **同步 / 异步的界线**：**走原语分派表的一律 `async`**（`set_data` / `get_data` /
> `remove_data` / `add_component` / `set_component` / `remove_component` /
> `move` / `move_entity` / `interact` / `place_entity` / `remove_entity` /
> `set_perception` / `clear_position` / `kv_set` / 地图编辑 / `emit` /
> `call_service` / `call_default_primitive`），**纯读取与注册一律同步**。
> 注意 `get_component`（同步）与 `get_data`（async）是一对**不一致**的读接口——
> 后者确实要 `await`；`kv_get` / `kv_set` 同理。

> **只读接口一律返回深拷贝（v0.7.3 / G51）**：`get_entity` / `list_entities` /
> `query_entities` / `get_component` / `get_map` / `get_location` / `get_world` /
> `list_worlds` / `list_folders` / `list_maps_by_folder` / `list_templates` /
> `capabilities` / `kv_get` 改返回值**都不会**影响运行中的世界（此前地图、地块、
> 世界是内核活对象，改个 `loc.name` 就真的改了世界；组件与 KV 是浅拷贝，嵌套的
> dict/list 与内核共享）。要改数据请走写接口。

### 动作（引擎原语，锁内执行）

| API | 说明 |
|---|---|
| `move(entity_id, direction, *, path=None)` | 路径移动（**分派入口**：可被过滤器改写/覆盖，返回 SceneView）。默认实现只做"读 connections → 抽目标 → 移动"，**不做任何阻挡检查**（没有阻挡机制，§10） |
| `move_entity(entity_id, map_id, row, col)` | 直接位移（行为驱动，传送语义） |
| `add_component(entity_id, component, data=None)` / `set_component(entity_id, component, data=None)` | 组件整块写（**走原语分派表**，可被覆盖/禁用）：新建（**已存在 → 报错**）/ 建或整体替换 |
| `remove_component(entity_id, component)` | 整块删组件（走分派表）；不存在 = 幂等 `False`（不落盘、不发事件） |
| `set_data(entity_id, name, value, component=…)` / `get_data(entity_id, name=None, component=…)` | 字段原语（**可被覆盖/禁用**，D11）：组件内合并写一个字段 / 读一个字段（`name=None` = 读整块 dict）；`component` **必填**，写在未建组件上会**隐式建出** |
| `remove_data(entity_id, name, component=…)` | **删字段**（D29；走分派，可被过滤/覆盖/禁用）：字段不存在 = 幂等 `False`（不落盘、不发事件）。⚠ 删掉最后一个字段后**组件仍在**（空组件 = 纯能力标记），要删组件用 `remove_component` |
| `set_perception(entity_id, patch)` | 感知（**写 `core:perception` 的唯一入口**，不受分派表影响）：`patch` 只收 `invisible` / `see_invisible`（布尔），其余键报错；空 dict 幂等无操作。见 §10「感知与隐身」 |
| `claim_avatar(entity_id)` | **把实体登记为当前主体的化身**——写 `core:account` 的**唯一入口**（D46，不受分派表影响）。认领后该实体受 **D14 保护**（`remove_entity` / `delete_map` / `delete_location` / `copy_map` 四处拒绝），账户注销时被级联删除。只能认领给**当前调用者自己的主体**（内核不接受客户端指定的账户 id）；已属于别人 → 报错 |
| `release_avatar(entity_id)` | **退掉自己的化身**（`claim_avatar` 的反向）：只允许解绑当前主体自己的；顺手清空指向它的凭据指针；**不删实体**——调用方随后自己 `remove_entity`（那时它不绑账户了）。两步分开是为了让"解绑"在事件流里留痕 |
| `act_as(entity_id \| None)` | 把**当前凭据**的行动实体指向某具实体（`None` = 解除指向）——D46 窄口。写的是**凭据行**，所以多端各记各的。⚠ **内核不校验归属**：玩法包必须先用自己的 roster 确认"这具是我的"，**绝不能**把客户端传来的 `entity_id` 原样交上来 |
| `clear_position(entity_id)` | 让实体**离开世界**（下线 / 收进容器 / 传送中间态）——**写 `core:position` 的受控入口**（与 `set_perception` 同性质，不受分派表影响）。组件 / 标签 / 账户绑定全保留，只去掉位置；幂等。放回世界用 `move_entity`。见 §10 / D36 |
| `interact(entity_id, target_id, action, args)` | 交互（**可被覆盖/禁用**）。**没有 `item_id` 槽位**（D37）：物品标识放 `args`，如 `args={"item": "apple"}`——内核不解释其内容 |
| `emit(event, data, log=False)` | 自定义事件（SSE 推送；`log=True` 写 world_log） |
| `place_entity(kind=None, map_id=None, row=None, col=None, *, name=None, desc="", components=None, tags=None)` / `remove_entity(entity_id)` | 实体生命周期（D14；**绑定了账户的实体不可 remove**，D42）。**能力 = 组件**（D41）：`kind` / `tags` 是**输入便利**（裸名解析），`place_entity("slime", ..., tags=["spawner"])` = 带上 `bestiary:slime` + `xxx:spawner` 两个组件（数据 `{}`）；两者都可省（没有能力组件的实体也合法）。**位置三参数可选（D36）**：全给 = 放进世界；**全不给 = 造一个不在世界上的实体**（物品放进容器、待投放的 NPC）；只给一部分 → 报错。不在世界上的实体**不出现在** `list_entities` / `query_entities` 的默认结果里（要它们传 `include_absent=True`，该参数 API 上**有**），移动会被拒绝。`components` = 初始组件（dict，键写全名 `source:name`，`core:` 一律拒绝）。**`name` / `desc` 是输入便利**：折进 `core:info` 组件（实体没有顶层名字字段；读回用 `entity.name` / `entity.desc`，§10） |
| `add_component(entity_id, component, data=None)` / `set_component(entity_id, component, data=None)` / `remove_component(entity_id, component)` | 加 / 换 / **摘**能力组件（D41：加能力就是加组件，摘能力要显式删——空组件是纯能力标记，不会自己消失）。`add` 对已存在的键报错；`set` 是整块替换 |
| `call_service(play_id, name, **params)` | 跨包服务调用（§6） |
| `call_default_primitive(name, *args, **kwargs)` | super 通道：显式调内核默认实现（覆盖者前置/后置用） |

> **组件写入也在分派表里**：`add_component` / `set_component` / `remove_component` 与
> 字段类原语一样可被 override / disable / 挂过滤器。**例外 = `core:` 组件**——它的写入
> **绕过分派表**（内核保留命名空间，玩法包既写不进、也拦不住；§10）。只读的
> `list_components` / `get_component` 不进分派表（与 `query_entities` 同口径：查询是数据面）。

### 地图编辑（D14：内容治理归玩法包/用户）

`create_location(map_id, row, col, name, *, description=None)`（新建地块，坐标重复/空名称报错）/ `update_location(map_id, row, col, **kwargs)` / `update_connection(map_id, row, col, direction, **kwargs)` / `create_map(map_id, name, ...)` / `delete_map(map_id)`（图上玩家在场拒绝，G2）/ `save_template(template)` / `delete_template(template_id)`

**内容包导入世界内容用 `import_bundle`（单事务，别逐条写）**：

```python
await api.import_bundle(
    {"id": "main", "name": "主世界"},                          # 地图定义（没有出生点，D45）
    locations=[{"row": 0, "col": 0, "name": "广场",
                "description": {"periods": [...]},          # 文案：TextSchedule 结构
                "connections": {"up": {"enabled": True, "paths": [...]}}}],
    entities=[{"row": 0, "col": 0, "name": "阿福", "desc": "老商贩",
               "components": {"local:merchant": {}}}],
    world_id="default",          # 归属世界（默认世界被删过就传 None = 不归属）
    folder_id=None,              # 归属组织节点（可选）
)
# → {"map_id", "locations", "entities", "entity_ids"}
```

- **一次 SQLite 提交**：要么全落盘、要么一个字节都不写。逐条 `create_map` /
  `create_location` / `place_entity` 在"导入到一半抛错"时会留下**半张世界**，
  而按"地图已存在则跳过"的幂等判断重跑又会**假装成功**（GAPS G55）
- **地图 id 已存在 → 报错**（不覆盖）。"导入过就跳过"由你自己判断：
  `if api.get_map(map_id) is not None: return`
- 校验先于写入，报错消息带**第几行**（"第 3 个地块非法：地块名称不能为空"），
  对着内容文件改就行；地块坐标重复、实体坐标不在任何地块上同样会点名
- 实体的 `name` / `desc` 折进 `core:info`，`row` / `col` 折进 `core:position`
  （**全给或全不给**，不给 = 不在世界上）；`kind` / `tags` 是输入便利（裸名解析）
- **不能带 `core:` 组件、不能绑账户**（D33 / D20）；完成后只发一条
  `on_world_edited`（`{op: "import_bundle", …}`），**不为每个实体补发** `place_entity`
- 不走原语分派——这是数据面导入（与 `create_map` 同级），不是一次动作
- 参考实现：内置世界包 `worlditor_play_demo_world`（41 地块 + 3 实体一次导入）

**模板（D22：地块与实体共用一个"模板"概念）**：
- `register_entity_template(template_id, name, data, label="")` —— 注册本包自带的**实体模板**
  （内存注册表，随包卸载消失）；`data = {name, desc, components}`
  ——`components` = `{"组件键": {字段: 值}}` 组件字典（§10）；顶层 `name` / `desc` 是
  **输入便利**，套用时折进 `core:info`（实体本身没有这两列）。
  **D41：模板就是"类型"的落点**——"类型 A = 一组组件 {A, C}"就写
  `data={"components": {"local:A": {}, "local:C": {}}}`（声明 API 不再收 `tags=`）。
  管理端本地模板落库，两边合并成一个选择列表（`list_templates("entity")`，同 id 本地优先）。
- `list_templates(scope=None)` —— 模板清单（`source` 标明 `play` / `local`）。
- `apply_location_template(template_id, map_id, row, col)` —— 套用地块模板：
  **同图目标按相对偏移平移、跨图目标原样复制**，目标格已有地块则拒绝。

**世界包导入内容时**：新内容走 `import_bundle(..., world_id=…)`（见上）；已经建好的
地图单独改归属用 `assign_map(map_id, world_id, folder_id=None, sort=None)`——把地图
归属到世界与组织节点（`sort` = 该节点内的序号，文件夹与地图**共用一个序号空间**，
见 DESIGN §4.3.2；缺省 = 同节点保留原位 / 换节点排到末尾）。管理端还有组织树拖拽、
地图搬家（含跨世界）、复制另存与地图体检（`GET /admin/lint`）——这些都是**管理维度**，
玩法包一般只需要导入时带上 `world_id`。

**文案（TextSchedule）只有一种格式**（v0.5.2 统一）：地图/地块的 `description`
与出口路径的 `label` 都必须是

```python
{"periods": [{"start": "06:00", "end": "18:00",
              "items": [{"text": "白天", "weight": 3}, {"text": "也是白天", "weight": 1}]}]}
```

`None` = 无文案；**纯字符串会被拒绝**（`WorldError`，消息里带格式示例），
结构非法（坏时间 / 空 `items` / 缺 `text` / 权重非正数）同理——不再静默丢弃条目。
`description` / `label` 的读取侧一律是 `to_dict()` 的产物，往返无损。

### 身份

`caller()`：**当前调用者以哪具实体行动**（MCP 工具 handler / 交互 / 事件回调内有效；身份经请求 `_meta` 注入）。
**没有化身时返回 `None`**——那是合法常态（D45/D46），不是"没认证"。

`caller_principal()`：当前调用者的**主体**（账户）id；围观凭据 → `None`。这是**稳定的键**：
同一主体换化身、重登都不变，适合做 roster 的索引；`caller()` 则会跟着切换变。
`caller_name()`：主体显示名（只用于文案）。

**"没有化身"怎么处理**（每个包都会遇到）：

```python
entity_id = api.caller()
if entity_id is None:
    return {"text": "你还没有角色：先用 player_create 建一具。"}
```

要身体就不要自己写这段——**让内核挡**：`register_tool(..., requires_entity=False)` 是给
**自举工具**（创建第一具化身、选角色）的显式豁免；**默认 `True`**，没有化身时内核直接回
"你还没有角色，先创建一具"。默认值定成 `True` 是刻意的：老包都假设 `api.caller()` 有值，
反过来会让它们**在运行期炸**。

> ⚠ **内核不诞生角色**（D45）：注册 / 登录**只产出凭据**，`token.entity_id` 从空开始。
> 玩家注册完是一个"没有化身的主体"——**把它带进世界是玩法包的活**（见 §14 玩家包契约）。
> 也别再造"player 实体"、别写 `local:player`：那个组件已随 D45 删除，"是不是人"一律看
> `core:account`（D42）。⚠ **`api.act_as()` 只在工具 handler 里有凭据上下文**
> （事件回调里没有）——"登录后接着玩"因此只能做成惰性接管，见 §14.4 第 5 点。

**账户生命周期（内核提供，玩法包感知）**：
- 玩家可永久注销（`POST /auth/delete-account`，级联吊销凭据 + **删除该主体的全部化身**）；
  管理员可删除账户/变更角色（`PATCH /admin/accounts/{id}`，变更即吊销旧凭据强制重登）
- **对玩法包的影响**：注销 = 该主体**全部绑账户实体**被**受控删除**（非玩法包 `remove_entity`
  通道），会触发 `on_entity_removed` / `on_world_edited`——需要按实体清理自身数据的包订阅该事件
  （如背包类包的持有数据、说话类包的广播冷却）；另外还会发一条 `on_principal_deleted`
  （见 §9），供包清自己的 roster

## 5. 原语、查询、顺序与变更（D11 / G14 / D26–D28）

### 5.1 原语覆盖与过滤器链（D11 / G14）

9 个可覆盖原语：`move` / `move_entity` / `set_data` / `get_data` / `remove_data` /
`add_component` / `set_component` / `remove_component` / `interact`
（**组件写入类也在内**；`core:` 组件的写入绕过分派表，玩法包拦不住，§10）。

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

**过滤器收到的命名参数**（`filter(api, **params)`；位置参数已按此规范化）——组件相关原语：

| 原语 | 命名参数 |
|---|---|
| `set_data` | `entity_id` / `name` / `value` / `component` |
| `get_data` / `remove_data` | `entity_id` / `name` / `component` |
| `add_component` / `set_component` | `entity_id` / `component` / `data` |
| `remove_component` | `entity_id` / `component` |

（其余原语参数不变：`move` = `entity_id` / `direction` / `path`，`move_entity` =
`entity_id` / `map_id` / `row` / `col`，`interact` = `entity_id` / `target_id` /
`action` / `args`——**没有 `item_id` 槽位**（D37），物品标识放 `args` 里，
如 `args={"item": "apple"}`。）

- 链尾 = 内核默认实现；**过滤器约定纯函数**（只读、不改世界——世界变更只发生在默认实现；需要改状态的逻辑放 override 或工具 handler）
- **与 override/disable 互斥**：原语已挂过滤器时登记 override 报错，反之亦然
- 同包可注册多个过滤器（各带 label）；生命周期随包卸载自动清理（内核恢复默认）
- 管理页可见（谁、顺序）

> 经典用法：方向别名归一过滤器（上/北/north → up，原内置 movement 包的做法）、
> 束缚/锁血/遮蔽类效果包。

### 5.2 实体查询（D26）

"所有带某组件的实体"不要写成"全量 `list_entities` + 自己筛"：

```python
# 所有中毒的生物（每 tick 扣血那种）——字段归属某个组件（这里用本包自己的组件名）
BESTIARY = "worlditor_play_bestiary:stat"        # source = 本包 play_id（§10）
for e in api.query_entities(tags=["poisoned", "monster"], world_id=world_id):
    hp = await api.get_data(e.id, "hp", component=BESTIARY) or 0
    await api.set_data(e.id, "hp", hp - 1, component=BESTIARY)

# 排除 + 限制条数（结果按 (map_id,row,col,id) 稳定排序，便于 diff）
targets = api.query_entities(tags=["monster"], exclude_tags=["dead"], limit=10)

# 感知过滤：我只该看到我看得见的（隐身 G12）
seen = api.query_entities(map_id=me.map_id, viewer_id=me.id)
```

**组件匹配语义（重要）**：`tags` / `exclude_tags` 筛的是**组件的存在**（D41），
裸名会按 D41 解析：唯一声明者 → 用它；没人声明 → `local:<名>`；**多个声明者 → 报错**
（那就写全名）。**活着的组件**才算数——**声明该组件的包没加载，或该包在实体所在世界
没启用 → 不匹配**（D21：这个世界没有这个能力）。所以"停用中毒包"之后
`tags=["poisoned"]` 查不到东西，和 `available_actions` 说"它没动作"是一致的。例外：

- **没有任何声明的组件**（没人声明过的 `local:xxx`，或声明包已被真卸载）照常匹配
  ——"组件即数据"的用法不受影响。
- 要完全跳过这套语义，用 `where=lambda e: e.has_component("x")`。

**严格校验**：拼错的地图 / 世界、非法标签（空串、非字符串）**直接报错**，不会"悄悄
查到空"——查询条件是人现写的意图，静默返回空会让人以为"世界里没有"。
性能：内存线性扫描（几千实体微秒级）；上万实体再考虑加倒排索引（GAPS G38）。

### 5.3 事件执行顺序（D27）

同一事件的多个订阅者按 **`(phase, order, 注册序)`** 执行：

| 参数 | 取值 | 说明 |
|---|---|---|
| `phase` | `input` → `simulate`（缺省） → `present` | 跨包的大阶段；未知名**报错**（不静默造阶段） |
| `order` | 整数（可负） | 同阶段内的细分序号，小的先跑 |
| — | 注册序 | 同 phase/order 时兜底（= 老行为：不给参数就还是注册序） |

```python
api.register_world_event("on_tick", _decay, interval=1.0, phase="input", order=-10)
api.register_world_event("on_tick", _ai,    interval=1.0)                    # simulate
api.register_world_event("on_tick", _broadcast, interval=2.0, phase="present")
```

覆盖**全部事件**（含 `on_tick`）。跨包顺序从此是**声明出来的**，而不是"谁先加载谁先跑"
这个隐式事实——包一多，那个顺序就会变成不能碰的意外契约。

### 5.4 变更检测与增量遍历（D28）

内核在**落库那一刻**给实体盖两枚戳（写入路径不可能漏盖）：

| 字段 | 含义 |
|---|---|
| `entity.revision` | 全局单调写序号（每次落盘写 +1；重启从库里续号，不回退） |
| `entity.changed_tick` | 最近一次变更所在的 **tick 窗口**（心跳每轮 +1，哪怕没人订阅 on_tick） |

增量遍历（"只处理上一轮之后动过的实体"）：

```python
cursor = api.world_revision()          # 或持久化在 kv 里
for e in api.query_entities(tags=["poisoned"], changed_since_revision=cursor):
    ...
await api.kv_set("cursor", api.world_revision())
```

- `changed_since_revision`：**精确游标**（每次写 +1，既不多报也不漏报）——客户端
  增量刷新 / 大世界按需 tick 用这个。
- `changed_since_tick`：**窗口粒度**（同一窗口内重复报）——`>=` 语义，宁可多报绝不漏报。
- 出口：`/state` 顶部带 `revision`/`tick`，实体自带两字段，SSE 事件 payload 也带。
- **不做**字段级脏标记（"哪些字段变了"）——与"实例可写任意未声明字段"的开放模型冲突，
  真需要时按包约定自己存影子副本。

## 6. 跨包服务（M3：玩法包间同步调用）

玩法包的数据在自己 namespace 里，其他包**不能直接读写**——跨包协作走服务：

```python
# 提供方（如背包包）：
api.register_service("bag_add", _bag_add)   # async (api, **params) -> Any
                                            # api = 提供方自己的 API 实例

# 调用方（任意其他包）：
total = await api.call_service("worlditor_play_yourpack", "bag_add",
                               entity_id=..., item="apple", count=3)
# 参数名由提供方包自定——"物品标识"是包自己的概念，内核不参与（D37）
```

- 服务在**引擎锁内**执行（读改写原子）；异常隔离（服务炸了不拖垮调用方，报"服务执行出错"）
- 服务名同包冲突报错；生命周期随包卸载清理（调用立即报"服务不存在"）
- 管理页 `/admin/services` 可见（谁提供了什么）
- 信任边界：玩法包间互信（社区包都是管理员装的）；跨包权限约定见 §11

> 出处：原内置 items 包曾提供 `bag_add/bag_take/bag_count/bag_get` 四个服务，
> starter 出生礼包、interaction 商贩交易、social 喇叭消耗都经服务调用——这些包
> v0.7.0 起已删除。服务机制本身的用例见 `tests/test_services.py`（用 `pkg_a` /
> `pkg_b` 两个内联假包演示注册、跨包调用、namespace 与异常隔离）。

## 7. MCP 工具

```python
api.register_tool(
    "world_around",
    _world_around,
    description="查看你周围的情况……（agent 的世界观入口，写清楚！）",
    params={"direction": "string", "path": "integer"},  # 可选：声明了即可选
    # requires_entity=True  # 默认：没有化身时内核直接回"你还没有角色"
)
```

- handler 签名 `async (api, ctx, **args) -> str | dict`；返回 `{"text": ...}` 或
  `{"text": ..., "ui": ...}`；dict 会被 JSON 序列化为 MCP 文本内容
- **参数类型**：`string` / `integer` / `number` / `boolean` / `array`
  （array = `list[str]`，G11）；**声明参数即可选**（缺省 None），必填校验由
  handler 自己完成（`raise WorldError("xxx 必填")`）
- **`requires_entity`（D46，默认 `True`）**：这个工具要不要"身体"。默认要求调用者有化身
  （没有则内核回"你还没有角色，先创建一具"）；**自举工具必须显式 `False`**——
  "创建第一具化身 / 选择角色"这类工具在玩家还没有化身时就要能调，否则自举路径被自己挡死。
  豁免后 `api.caller()` 会是 `None`，handler 要自己处理这种情况
- 同名工具冲突报错（D2）；工具随包卸载自动从 MCP server 移除
- 身份：handler 内 `api.caller()` 读取**这次以哪具实体行动**、`api.caller_principal()`
  读取**主体**（稳定键）；**工具是 agent 的唯一动作通道**，
  权限（谁能做什么）由玩法包自行裁定（例如背包类包只回答"我自己身上有什么"）

## 8. 视图（WebUI）

```python
api.register_view(
    "movement",
    title="世界",
    icon="🗺️",
    provider={"type": "component", "url": f"/plays/{api.play_id}/web/view.js"},
)
```

> **视图 tab 会自动跟随玩法包变化**（v0.7.0）：内核在包被加载/启用/停用/安装/卸载，
> 以及某世界的激活集合被改动时广播 `plays_changed`（SSE `/events`），玩家端据此重拉
> `/views` 并更新 tab——**你的包不需要自己实现任何刷新/轮询逻辑**，也不必在组件里
> 监听这件事。视图列表本身按**调用者所在世界**过滤（D15/D21），未启用的包不会出现 tab。

`web/view.js` 是**视图组件协议**文件——`new Function("Vue", "UiBlock", code)`
动态加载，**文件 = IIFE**（形参 `Vue`/`UiBlock` 由加载器注入并执行，返回
Vue 组件选项）：

```js
(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;
  // ...组件实现（Vue 组件选项：props {view}, setup, render）
  return { name: "XxxView", props: { view: Object }, setup() { ... } };
});
```

- **协议约定**：文件必须以 `(function (Vue, UiBlock) {` 开头、`});` 收尾
  （加载器 body = `return (<code>)(Vue, UiBlock);`）；加载失败前端显示
  「视图加载失败」
- 组件 props 收到 `view`（注册元数据）；**数据通道 = MCP 工具**（视图内嵌轻量
  callTool，参考实现 `tests/fixtures/plays/worlditor_play_demo/web/view.js`）
  或只读 REST（/scene 等），不新增数据通道（D7）
- **MCP 会话必须管理**（视图内 callTool 实现）：streamable HTTP 要求先
  `initialize` 拿响应头 `Mcp-Session-Id`，后续 `tools/call` 请求头带上——
  否则返回 400 `Missing session ID`（夹具参考实现：`tests/fixtures/plays/
  worlditor_play_demo/web/view.js` 的 `ensureSession()` + 模块级 `_sessionId` 缓存）
- **请求需带 Bearer**：`/plays/<id>/web/*`、`/scene` 等要求认证——视图内部
  fetch 一律带 `Authorization: Bearer <localStorage 的 worlditor_token>`
  （参考实现同上）
- **provider.url 必须站内本包**：`/plays/<play_id>/web/…`（内核校验，阶段 3）——
  WebUI 对该 url fetch 时附 Bearer，因此拒绝相对/跨站/跨包地址
- `UiBlock` 参数 = 内核 UiBlockRenderer 组件（用 UiBlock 树渲染列表/表单/文本
  免写组件；复杂界面直接写 Vue）
- **视图注入两种通道**（DESIGN §4.4）：
  - `ui_hook`（UiBlock 树，**服务端展开**）：注册 `register_ui_hook(block_kind,
    position, provider)`——交互弹窗等 UiBlock 渲染前注入（已接线，G18 解决）；
    玩法包无需知道 UI 细节
  - **挂载点 slot**（自定义组件视图，**设计稿**）：`register_view_slot(view_key,
    slot_name, provider)` + 视图组件 `<slot name>`——快捷栏/手持按钮等需要
    注入到自定义 Vue 组件时再实现（G4）
- 兜底：无任何视图时 WebUI 显示内核"无视图"提示（D7）
- **样式约定（v0.1.17）**：WebUI 是**暗色主题**，视图组件**不得硬编码浅色**
  （白底/浅灰底与主题冲突 → "整片发白、白底白字"）；统一用内核样式基石：
  - 结构/文本：`wt-head`（两端对齐标题行）、`wt-row`、`wt-title`、`wt-strong`、
    `wt-dim`、`wt-note`、`wt-err`、`wt-clip`（单行省略）
  - 容器：`wt-card`、`wt-grid`（配 `wt-cols-3` / `wt-cols-4`）、`wt-cell`
    （格子；`.empty` 空态、`.here` 当前位置、`.walkable` 可点）、
    `wt-list` + `wt-li`、`wt-detail` + `wt-json`（折叠原始 JSON）
  - 按钮：`wt-btn`（可加 `.primary` / `.ghost`）——**不要用裸 `<button>`**
    （浏览器系统按钮样式是浅色的）
  - 颜色只走 CSS 变量：`--bg` / `--bg-2` / `--bg-3` / `--text` / `--text-dim` /
    `--accent` / `--danger`（如 `background: "var(--bg-2)"`）
  - 参考实现：`tests/fixtures/plays/worlditor_play_demo/web/view.js`；防回归测试
    `tests/test_web_view_styles.py`（扫描 `tests/fixtures/plays/*/web/*.js`，
    硬编码浅色或裸按钮直接失败）
- `/meta` 返回 `{mode: "play"|"admin"}`：同一前端按端口切换界面（玩家视图宿主
  vs 管理面板）——视图只在玩家模式加载（D16 界面分离）

## 9. 事件

预置事件（WORLD_EVENTS，**共 10 个**，订阅签名）：

| 事件 | 签名 |
|---|---|
| `on_tick` | `(api, dt)`——必须给 interval（秒）；tick 粒度 1s（G3 观察项） |
| `on_entity_move` | `(api, entity, from_pos, to_pos)` |
| `on_entity_enter` | `(api, entity, map_id, row, col)` |
| `on_interact` | `(api, request, result)` |
| `on_entity_removed` | `(api, entity)` |
| `on_entity_changed` | `(api, entity, changed)` |
| `on_world_edited` | `(api, what)`——`{op: "place_entity"|"remove_entity"|..., entity_id}` |
| `on_principal_login` | `(api, principal)`——主体登录成功（凭据已发） |
| `on_principal_logout` | `(api, principal)`——一份**凭据**被吊销（改密/重登的批量吊销不算） |
| `on_principal_deleted` | `(api, principal)`——账户永久注销（内核已删该主体的全部化身） |

`principal` 是 `Principal`（`account_id` / `username`）——**主体 = 可登录的账户，不是实体**：
它不绑位置、不属于任何世界。所以三条主体事件**不做世界激活过滤**（订阅者全都能收到），
也**不推 SSE**（"谁登录了"广播给所有订阅者 = 把名册发给每个玩家）。典型用法：

```python
async def _on_login(api, principal):
    # 记"这个主体上次操作的是哪具"（本包自己的 KV），或让化身**入场**（move_entity）
    # ⚠ 但**不能**在这里 act_as——事件回调里没有凭据上下文（§14.4 第 5 点）
    ...
api.register_world_event("on_principal_login", _on_login)
```

> **内核事件现为 10 个**（上表全部）：v2 / D37 删掉了原 `on_item_used`——**物品语义由
> 玩法包自定义事件承担**（例如"用了一个东西"发 `api.emit("item_used", {...})`），
> 内核不解释事件名与内容（下段的自定义事件通道）；D47 加了三条主体事件。

自定义事件（G8/D1）：`api.emit("say", {...}, log=True)`——任意事件名，
SSE 推送；`log=True` 才写 world_log（高频事件勿写，5000 条上限）。
**说话/广播通道 = 自定义事件**（内核无 say）。

## 10. 组件设施（D9/D10）

**实体的数据按组件分组**：`entity.components == {"组件名": {字段: 值}}`（读单个组件用
`entity.component("组件名")`，缺失 = 空 dict；**当只读看待，别改内部引用**）。
原来的 `attrs`（玩法数据）与 `state`（动态状态）**两个扁平容器都已删除**——
**不再有 attrs / state 之分**，只有组件；实体可以带**任意**组件（沿用原 D9
"可写任意未声明字段"的开放模型）——**`core:` 除外**（内核保留，写不进）。

**实体形态**（v2 / D41 / DESIGN §12.4）：`to_dict()` / JSON / SSE 投影都是**5 键**——

```python
{"id": "…",                       # uuid4 hex
 "components": {"core:info": {...}, "local:stat": {...}},
 "last_active_ts": 0.0,           # 在线状态（只在内存，重启从 0 起）
 "revision": 12,                  # 全局单调写序号（D28）
 "changed_tick": 7}               # 最近一次变更所在的 tick 窗口（D28）
```

**没有顶层 `name` / `desc` / `user_id`，也没有 `kind` / `tags` / `map_id` / `row` / `col`**
（能力 = 带没带那个组件，D41；位置在 `core:position` 里，D36）。名字 / 描述在
**`core:info`** 里，账户绑定在 **`core:account`** 里（都是内核保留组件）。
读名字的**兜底写法**：

```python
info = entity.components.get("core:info") or {}
name = info.get("name") or entity.id[:8]    # 缺失 → id 前 8 位（§12.4 既定语义）
desc = info.get("desc") or ""               # 缺失 → 空串

# 更省事：内核把同一份兜底逻辑做成了只读 property（推荐）
name, desc, uid = entity.name, entity.desc, entity.user_id
# 位置同理：entity.map_id / entity.row / entity.col 是**只读 property**
#（缺失 → None，不是 "" / 0）；它们**不在 to_dict() 投影里**，序列化后取不到
```

- `entity.name` / `entity.desc` / `entity.user_id` / `entity.map_id` / `entity.row` /
  `entity.col` 都是**只读 property（派生视图）**，缺失依次兜底为 `id` 前 8 位 /
  `""` / `None` / `None`——**别再给它们赋值**（没有 setter），
  玩法包也**写不进** `core:info` / `core:account`（`core:` 保留命名空间，写入直接报错）
- **能力（`kind` / `tags`）已随 D41 折叠为组件**：实体的 `kind` / `tags` 属性
  **不存在**（`AttributeError`），两张表列也删了（表 v11 / 4 列）；
  `core:player` 从未引入（D42：身份概念整个删除，判据是"带没带 `core:account`"），
  `local:player` 也已随 D45 删除——**没有任何"这是玩家"的内核标记**

### 组件名 = `source:name` 信封

```python
entity.components == {
    "core:info":       {"name": "商贩·阿福", "desc": "…"},   # 内核保留：名字 / 描述
    "core:account":    {"user_id": "…"},                    # 内核保留：账户绑定
    "core:perception": {},                      # 内核保留：感知
    "local:stat": {"gold": 120, "energy": 1},   # 编辑器 / 人手写
    "worlditor_play_xxx:yyy": {...},            # 包用自己 play_id 作 source
}
```

| source | 说明 |
|---|---|
| `core` | **内核保留命名空间**（仅内核可写）——玩法包写入**直接报错**（`WorldError`）；它的写入还**绕过分派表**（玩法包拦不住） |
| `local` | 编辑器 / 人手写的本地命名空间——管理端编辑虚构组件的落点（保证"信封必填"无例外）。**玩法包当前也写得进**（D43 暂不收紧） |
| `<自己的 play_id>` | 自己的组件——**推荐用它作 source**，天然不撞名 |
| `<别人的 play_id>` | **写不进**（D43：包名写在键里就是真规则，不是命名约定）。要影响别人的数据走 `call_service`（让对方自己写）或事件；**声明期**的跨包扩展走 `add_tag_fields`（"扩展可以，但要留痕"） |

- 组件名**必须含一个冒号**（`source:name`），字符集 = 字母 / 数字 / `_` / `.` / `-`；
  非法名**报错**，不静默兜底
- **内核组件共 4 个**：`core:info`（`name` / `desc`）、`core:account`（`user_id`）、
  `core:position`（`map_id` / `row` / `col`，可选，见 §「不在世界上」）、`core:perception`
  （`invisible` / `see_invisible`，见下）。**能力 = 组件的存在**（D41：没有"基底类型"
  这回事，`kind` / `tags` 已折叠为组件、两张表列已删——表 v11 / 4 列）
- **`core:` 读得到、写不了**：`get_component` / `list_components` 读 `core:` 不受限；
  写只有内核能做——**但正当能力走窄口**：目前有四个入口
  **`api.set_perception(...)`** / **`api.clear_position(...)`** /
  **`api.claim_avatar(...)`** / **`api.release_avatar(...)`**（见 §4 与 §14）；`core:info` /
  `core:account` 其余情形由内核侧写入
  （`place_entity(name=…, desc=…)`、身份服务、管理端 `PATCH /admin/entities/{id}`），
  玩法包不直接改——**名字是内核文案**（lint / 删除保护 / 日志），D40

### 组件级 API（整块）

```python
api.list_components(entity_id) -> list[str]               # 组件名列表（只读）
api.get_component(entity_id, component) -> dict | None    # 整块读（只读；不存在 = None）

await api.add_component(entity_id, component, data=None)  # 新建（已存在 → 报错）
await api.set_component(entity_id, component, data=None)  # 建或**整体替换**
await api.remove_component(entity_id, component) -> bool  # 幂等（不存在 → False）
```

### 字段级 API（组件内的一个键）

`component` **必填**——没有扁平命名空间了；写在**未建组件**上会**隐式建出**组件：

```python
await api.set_data(entity_id, "gold", 120, component="local:stat")  # 合并写一个字段
api.get_data(entity_id, "gold", component="local:stat")             # 读一个字段
api.get_data(entity_id, component="local:stat")                     # name 省略 = 整块 dict
await api.remove_data(entity_id, "gold", component="local:stat")    # 删字段（幂等 False）
```

- **逐字段合并写的替代**：现在是"**读整块 → 改 → `set_component` 整体写回**"——
  handler 在引擎锁内执行，天然原子（§11 性能与并发）
- **已删除**：`set_attrs` / `get_attrs` / `set_state` / `get_state` / `remove_state`
  全都没了——请改用上面的组件 / 字段 API
- **走分派表**：`set_data` / `get_data` / `remove_data` / `add_component` /
  `set_component` / `remove_component` 都可被其他包 override / disable / 挂过滤器
  （§5.1）；`core:` 组件例外（写入绕过分派表）
- **字段 schema 仍可声明**（D9/D41）：组件声明的 `fields` 项 =
  `{name, label, type, default?}`（type: str/int/float/bool/json）；别人用
  `add_tag_fields(组件键, [...])` 追加。**字段清单按组件分组**（不跨组件摊平），
  **同一组件内同名字段重复声明 → 报错**；分类字段（`add_category_fields`）已删除，
  `categories` 只剩"选取分组"这一件事。**声明只影响 UI 渲染**，实例照旧可写任意未声明字段
- **新增实体**：`await api.place_entity(kind, map_id, row, col, name=…, desc=…,
  components={...}, tags=[...])`——原 `attrs=` / `state=` 参数**已删除**；`kind` / `tags`
  是**能力输入便利**（落成组件键，D41），`components` 是显式组件字典；实体模板
  的 `data` 里同样是 `components`（§4）；`name` / `desc` 会被**折进 `core:info`**
  （实体没有顶层名字字段——见本节顶部「实体形态」）
- **"不在世界上"是合法状态**（v2 / D36）：`place_entity` 的坐标**可以整组不给**——
  造出来的实体没有 `core:position`，不出现在默认的 `list_entities` / `query_entities`
  结果里，也不能 `move`。**放回世界**用 `await api.move_entity(entity_id, map_id, row, col)`
  （它接受不在场的实体），**让它离开世界**用 `await api.clear_position(entity_id)`
  （组件、标签、账户绑定全保留，只去掉位置；幂等）。
  什么时候用它：物品收进容器、玩家下线、传送中的中间态——**别用 (0,0) 当"没有位置"**，
  那会把"不在场"变成一个真实存在的坐标。
  > 这两个入口与 `set_perception` 同一性质：`core:` 直写对玩法包关闭（D33），但"下线 /
  > 传送"本来就是玩法包的正当能力，所以内核给**窄口受控入口**（§12.2：规则不放宽，
  > 能力不丢失）。若没有 `clear_position`，"位置可缺失"就成了单向门——造得出、送不回去。
- **物品不在内核**（v2 / D37）：原"物品定义同构（`ItemDef` + 字段）"作废——
  **类型 = 组件声明**（`declare_component` 的 `fields`，字段 schema 完全同构），
  **实例 = 实体 + 组件**（在地上 = 一个实体带该组件，在背包里 = 本包自己的 kv）；
  `stackable` / `icon` 这类属性就是组件声明里的字段与你的 UI 约定。替换关系表见 §4

### 阻挡机制已整体移除

- `register_entity_kind` / `register_entity_tag` / `register_entity_type` 的
  `block_move` 参数**已删除**；`capabilities(entity)` 与 `list_kinds()` 的输出里
  也**没有阻挡键**了
- **所有实体都不阻挡**：`move()` 的默认实现只做"读 connections → 抽目标 → 移动"，
  **没有任何阻挡检查**；`move_entity` 是传送语义
- 门的开关 / 机关 / 墙 / NPC 挡路 → **归玩法包**：用
  `api.override_primitive("move", handler)` 或过滤器链自行判定（原"开门解除阻挡"的
  那条通道已随 state 容器一起删除）
- 将来若需要，会另立一个"描述阻挡能力"的内核组件（尚未定，见 GAPS G44）

### 感知与隐身（G1 / G12）

- 内核感知读的是 **`core:perception`** 组件里的 `invisible` / `see_invisible` 字段
  （原来读 attrs 里的键名）：`query_entities(viewer_id=…)` / `list_entities(viewer_id=…)`
  据此过滤——隐藏 `invisible` 为真的实体，viewer 自身 `see_invisible` 真视
- 写它的入口是 **`api.set_perception(entity_id, {"invisible": True})`**：
  玩法包不能直写 `core:`（D33），但让实体隐身本来就是玩法包的正当能力，所以内核给了
  这个**窄口受控入口**——只收 `invisible` / `see_invisible` 两个布尔字段
  （白名单之外的键直接报错；空 dict 幂等无操作）。
  这正是"规则不放宽（`core:` 仍只有内核能直写）、能力不丢失"的平衡点，
  与 `clear_position`（位置）同一种做法：**受控窄口入口**，而不是把命名空间打开。

  ```python
  await api.set_perception(npc.id, {"invisible": True})   # 藏起来
  await api.set_perception(player.id, {"see_invisible": True})  # 真视
  await api.set_perception(npc.id, {"invisible": False})  # 现形
  ```

  > 想让**自己的组件**也成为可见性依据（包级隐身分层）时，请自行过滤——
  > 内核感知的判定点是**单一**的（只看 `core:perception`，G12），
  > 多一层来源会让"query 说看得见、菜单说看不见"这类不一致重新出现。

### 落库与兼容

- 实体表 **4 列**（v11 起）：`id` / `components_json` / `revision` / `changed_tick`。
  组件全部落在 `components_json`（v8 起：原 `attrs_json` + `state_json` 合一）；
  `name` / `desc` / `user_id`（v9 删）、`map_id` / `row` / `col`（v10 删，搬进
  `core:position`）、`kind` / `tags_json`（v11 删，能力 = 组件）**都已不在表里**；
  地图表 `maps` 的 `spawn_row` / `spawn_col` 也在 **v12 删除**（D45：内核不存在出生点）
- 表结构版本 **v12**（`store.SCHEMA_VERSION`）：旧版本库**拒绝启动**
  （`IncompatibleDataError`，消息里指明删 `world.db`），**没有迁移**，也不再
  "缺列就 ALTER 补上"。另有**「不该存在的列」检查**：库里还带着上面那些删掉的列
  （含 `maps.spawn_row` / `spawn_col`）同样**拒绝启动**——多出来的旧列 = 数据还在
  老位置，载入会成功而**名字 / 描述 / 账户绑定 / 位置 / 能力被静默丢掉**
- `last_active_ts` **不落库**（在线状态只在内存，重启从 0 起）

## 11. 约定与规范

### 玩家部件（Player Part，DESIGN §4.5）

背包、技能树、装备栏等概念"属于玩家"（拥有关系）但**不依赖**玩家对象——
新部件是**追加**，不得要求重设计玩家。做一个玩家部件：

- **数据**：`play_data` KV，key 含 entity_id（如 `bag:<eid>`）；默认**玩家级**
  （跨世界跟人走，kv 不传 world_id）；世界级隔离为可选（传 world_id）
- **服务**：部件能力出口（bag_add/take/…），供其他包软探测/调用
- **UI 注入（追加到玩家界面）**：注册 `ui_hook("character", "after", provider)`——
  产出 `character` 块的包（夹具参考：`world_whoami`）把块交给
  `api.apply_ui_hooks` 服务端展开；部件包 hook 追加自己的面板（背包面板 = list
  子块，provider 内调服务读取数据）。**软依赖天然**：部件包未装 → hook 不存在
  → 玩家视图无该面板，无需任何探测代码
- **软依赖（玩家壳零部件引用）**：部件信息通道归部件包——文本 = 部件包自己
  的工具（如背包工具）；面板 = `ui_hook` 注入。**玩家壳不 import、不探测、
  不调用部件包**（夹具示范：`worlditor_play_demo` 的 `world_whoami` 只产出
  `character` 块 + `apply_ui_hooks`，不引用任何部件包 play_id）；
  `requires.plays` 只用于原子能力硬依赖（如礼包包发货必须背包包的服务）
- **不写硬依赖**：`requires.plays` 仅用于"没有它部件无法工作"（如礼包发货必须
  背包包的服务）；纯展示/可选功能一律软依赖
- 参考实现：`tests/play_fixtures.py` 的夹具包 `worlditor_play_demo`——出生礼包 =
  `on_world_edited` 给新玩家发初始金币（`"gold" not in entity.component("local:stat")`
  即"只发一次"的标记）；部件面板注入 = `world_whoami` 的 `character` 块 +
  `apply_ui_hooks`（见 §12）

### 命名契约（G6，社区共同遵守）

| 领域 | 建议组件/字段/事件名（附原提供方） |
|---|---|
| 金币 | 组件 `local:stat` 的字段 `gold`——原内置 interaction/player 包 |
| 精力 | 组件 `local:stat` 的字段 `energy`——原内置 interaction 包（eat 效果） |
| 说话 | 事件 `say`（cell）/ `broadcast`（world）——原内置 social 包 |
| 礼包标记 | 组件 `local:stat` 的字段 `starter_granted`——原内置 player 包 |
| 广播冷却 | kv `broadcast_cd:<entity_id>`——原内置 social 包 |

**现在有归属机制了**：组件名自带 source（§10）——包自己的组件用
`<自己的 play_id>:<名字>`，`core:` 是内核保留，**写别人的 `<play_id>:` 直接报错**（D43）。
`local:` 的定位是"编辑器 / 人手写"，但**当前玩法包也写得进**（D43 只拦"别人的前缀"，
收紧 `local:` 留到以后单独一步）——**新代码建议写自己的 play_id**，归属一眼可见。
**撞名由命名空间解决**，所以本表的意义从"防撞名"降级为"让人找得到"：写通用数据
（金币、精力这类跨包会互相认的字段）时，按本表用**同一个组件名 + 字段名**，
别的包才认得出你的数据；只给自己用的数据随便放自己的组件，不必登记。

> **v0.7.0 起 6 个内置领域包已删除**：上表"原提供方"只是**出处记录**——那些包
> 不再分发，也不再提供这些字段/事件；**名字本身是社区包的建议名，谁都可以采用**
> （已无包"拥有"它们）。若你的包要与别的包共享字段/事件，仍建议登记到本表
> （PR 更新），让"谁提供、谁消费"有据可查。
>
> **朝向不在约定内**（v0.1.18）：地块连接槽的方向（up/right/down/left）是
> 内核数据模型，但"实体朝向/视角"属于具体玩法的自由发挥——原内置 movement 包
> 不做朝向（该包已删除），若你的包需要（第一人称/相对移动），自行约定字段名并
> 登记到本表。

跨包读写**约定字段**（组件名 + 字段名）前先查提供方包的服务/文档；通用字段建议进本表（PR 更新）。

### 编辑权限（G7）

编辑地图/实体前**先查其 ACL**：家地图的写权限由家玩法包判定（读其服务/
记录），内核不做"家"概念强制（D14：内容治理责任归玩法包）。示例：商贩交易 =
金币等**组件字段**的读写 + 背包数据操作，无内核强制（夹具包的 `trade` /
`buy_apple` 即此写法）。

### 性能与并发（G5）

- **handler 在引擎锁内执行**（AsyncRLock 任务级可重入）：handler 内再调
  API 原语（move / set_data / emit / kv_set…）为同一任务重入，安全——
  多段「读-判-写」天然原子，无需自备锁
- **红线**：handler 内 `asyncio.create_task()` 创建的子任务**不得调用引擎
  API**（子任务不是当前任务、拿不到锁——await 子任务即死锁）；自管后台
  任务只做纯计算/IO，并必须在 `teardown(api)` 中取消
- handler 保持短小（毫秒级）；长耗时任务（LLM 调用、网络、重计算）按上条
  自管 asyncio task
  - ⚠ **红线是"handler 不得 `await` 那个子任务"**（handler 持锁等它 = 它永远拿不到锁
    = 死锁），而**不是**"子任务永远不能碰引擎 API"：handler 返回、锁释放之后，
    分离式任务自己去抢锁是安全的
  - **结果怎么落回世界**：两条路都行——① 子任务把结果放进自己的队列/变量，
    由**后续的 handler**（如 `on_tick`）在锁内落地；② 子任务自己
    `await api.set_data(...)`（它会在锁空闲时拿到锁）。**唯一不能做的是让 handler 等它**
- 过滤器必须纯函数（只读）；世界变更只发生在默认实现
- 事件 handler 异常被隔离（记日志不拖垮内核）；交互 handler 异常转可展示错误

### 通用

- 中文注释/文案（本项目语言）；日志用 `logging.getLogger("worlditor")` 风格
- 工具 description 写清楚**给 agent 看**（世界观入口，G9 观察项）
- 管理端可见性：注册的东西（工具/视图/服务/过滤器/覆盖）都会显示在管理页，
  命名要人能看懂（label 字段）

## 12. 参考实现（测试夹具包）

**v0.7.0 起 6 个内置领域包已删除**：仓库不再分发行为玩法包（工具/视图/服务/
过滤器/组件声明）；内置目录 `worlditor_mcp/builtin_plays/` 只剩世界内容包。
行为玩法包的参考实现搬到了测试夹具：

- `tests/play_fixtures.py`——夹具源码：`install_demo_play(plays_root)` 把演示包
  `worlditor_play_demo` 写进临时目录（`play.yaml` / `main.py` / `data/shop.json` /
  `web/*.js`），测试与 E2E 都用它；`install_probe_play(plays_root)` 是更小的探针包
  `worlditor_play_probe`（工具 `world_ping` + 视图 `ping`，用于世界激活过滤的对比验证）。
- `tests/fixtures/plays/worlditor_play_demo/web/view.js`——**视图组件参考实现**
  （IIFE 协议 / `ensureSession()` 会话管理 / `wt-*` 样式约定 / 版本串上报），
  也是防回归测试 `tests/test_web_view_styles.py` 的对象。
- `tests/fixtures/plays/worlditor_play_demo/web/admin-shop.js`——**管理页组件参考
  实现**（数据通道 = `fetch /admin/play-pages/{play_id}/{page_key}/{action}`）。
- `tests/fixtures/plays/worlditor_play_player/`——**玩家包参考实现**（完整包：`play.yaml` /
  `main.py` / `data/spawn.json` / `web/view.js`）。"玩家是什么"的示范都在这里，见 §14。

夹具包 `worlditor_play_demo` 覆盖的机制（照它抄就够起步）：

| 机制 | 夹具包里的样子 |
|---|---|
| MCP 工具 | `world_whoami`（`api.caller()` 读身份） |
| 视图组件 | `register_view("demo", …)` → `web/view.js` |
| 管理页 | `register_admin_page("shop", …)`：货单管理，action = `list` / `set_price` |
| 物品标识 / 组件声明 | apple / megaphone = **包自己的物品标识**（现在是标签名 + 自己的 kv）：类型由本包声明为组件（`register_entity_tag` 的字段 schema），持有数放本包 kv `bag`——内核没有 `ItemDef` / `items` 表（D37） |
| 组件声明 + 交互 | merchant（talk/trade/buy_apple/buy_megaphone/bye）、sign（read）、door（open；**不再挡路**——阻挡机制已移除，开门只写一次组件数据）；`eat` 走**本包自定义事件** `item_used`（原内核 `on_item_used`，已随 D37 移除） |
| ui_hook 产出 | `world_whoami` 产出 `character` 块，经 `api.apply_ui_hooks` 服务端展开（部件注入点，见 §11） |
| 世界事件 | `on_tick`（告示牌写 `local:sign.last_updated`）/ `on_entity_enter`（进迷雾区发自定义事件）/ 自定义事件 `item_used`（吃苹果 → `local:stat.energy` +1）/ `on_world_edited`（新玩家首次发 `local:stat.gold`） |
| 玩法数据自管 | 实体组件（`local:stat` 的 `gold` / `energy`、`local:sign` 的 `last_updated`、`local:door` 的 `open`）+ kv（`bag` 背包、`bulletin_reads`、`shop_prices` 覆盖层） |
| 世界激活语义 | 与 `worlditor_play_probe` 对照验证（D21：未启用该包的世界里工具被拒、视图不出现） |

> 夹具包**不注册跨包服务**（`world_whoami` 与背包都走本包 kv）——跨包服务的
> 注册/调用用法见 §6，完整用例在 `tests/test_services.py`（`pkg_a` / `pkg_b`
> 两个内联假包）。

内置只剩一个世界内容包：

| 包 | 能力 | 关键机制 |
|---|---|---|
| `worlditor_play_demo_world` | **世界内容包**：导入示例主世界（41 地块：广场/步行街/AstrBot大道/开源小区/迷雾森林 + 商贩·阿福/告示牌/木门） | `async setup` 读取本包 `world.json`（地图/地块/连接/实体），**一次 `api.import_bundle` 单事务导入**（§4「地图编辑」——要么全落盘、要么什么都不写）；**地图已存在则跳过**（不覆盖用户改动）；只导入内容，**不注册组件声明/交互/工具/视图**——行为由你自己的包（或夹具参考包）提供；换世界主题 = 停用本包换成你自己的世界包 |

> 想看真实代码？内容导入型包看 `worlditor_mcp/builtin_plays/worlditor_play_demo_world/`；
> 行为玩法包看 `tests/play_fixtures.py`（Python）+ `tests/fixtures/plays/worlditor_play_demo/web/*.js`（组件）；
> **玩家包看 `tests/fixtures/plays/worlditor_play_player/`**（§14）。

## 13. 玩法包管理页（管理端注册协议，DESIGN §4.6）

玩法包可注册**管理页**（可多个），让管理员经管理端治理本包内容（自有数据：货单、
商店配置、背包等），无需改内核。

### 注册

```python
api.register_admin_page(
    key="shop",               # 本包内唯一 key
    title="货单管理",          # 管理端导航显示名
    icon="🧺",
    component_url=f"/plays/{api.play_id}/web/admin-shop.js",  # 必须本包资源
    actions={
        "list": _admin_list,        # async def handler(api, **params) -> JSON 可序列化
        "set_price": _admin_set_price,
    },
)
```

### 约定

- **管理页是独立页面**（管理端路由 `#/admin/pages/{play_id}/{page_key}`，
  非弹窗）：复杂配置玩法包可在页面内自建二级面板/分栏；组件可读取
  `page` prop（{play_id, key, title, actions}）
- **入口由内核放到管理端侧栏**（v0.2.1）：所有管理页在侧栏自成一级分组
  「玩法包管理页」（可收起展开）；玩法包详情页只展示工具/服务/视图/原语，
  不列管理页；管理页内不需要"返回玩法包"按钮。启停/安装/卸载后侧栏实时刷新
  （玩法包不需要做任何事，`register_admin_page` 即出现在侧栏）；
  多包都有管理页时条目会补显示所属包名。
- **数据语义归玩法包**：action handler 收到**本包自己的 API 实例**（play_id
  已绑定），在引擎锁内执行；数据校验、不变量、持久化全由玩法包负责
  （示例：货单管理 create/update 后写本包 kv；**内核没有物品定义可落库**——D37 后
  持久化由包自管，落 `templates` 表请用 `save_template`）。
- **错误透出**：`WorldError` 的消息会原样返回（400 + `{"error": msg}`）；
  其他异常被隔离为通用错误文案（管理端可见）。
- **组件**：与视图组件同一动态加载协议（`(function(Vue, UiBlock) {…})`，
  IIFE 形参由加载器注入执行，见 §8；render 函数，运行时无模板编译器；
  数据通道 = `fetch` 管理端代理端点
  `/admin/play-pages/{play_id}/{page_key}/{action}`（同源 + Bearer，
  仅 tier=admin））。
- **样式**：管理端同为暗色主题——用 `.btn` / `.btn-primary` / `.btn-ghost` /
  `.btn-danger`、`.card`、`.table` 或 CSS 变量（`var(--bg-2)`…），不要硬编码浅色
  （管理页组件 `admin-*.js` 不在视图防回归测试范围内，但同属一条约定）。
- **管理面不扩展内核**：不要用管理页绕过玩法包语义去裸写其他包的 play_data。
- 参考实现：`tests/fixtures/plays/worlditor_play_demo/web/admin-shop.js`（货单管理，
  `list` / `set_price` 两个 action；对应的 Python 在 `tests/play_fixtures.py`）。

## 14. 玩家包契约（D45–D47）

**内核不认识"玩家"**：它只知道两件事——**这次请求以哪具实体行动**（凭据指针）和
**哪些实体属于哪个主体**（实体上的 `core:account`）。"玩家是什么"（一具化身 / 多具 /
没有 / 夺舍 / 共号）整个归玩法包。这一节是包与包之间的**名字级契约**（G59 提前落地的部分）。

### 14.1 三个概念，别再混

| 概念 | 是什么 | 从哪读 |
|---|---|---|
| **主体（principal）** | 可登录的账户；**稳定的键**（换化身、重登都不变） | `api.caller_principal()`；`/meta` 的 `principal` |
| **行动实体** | 这次请求以哪具实体行动；**可以为空**（还没有化身） | `api.caller()`（`None` = 没有） |
| **化身** | 属于某主体的普通实体（带 `core:account`） | `api.query_entities(include_absent=True, where=lambda e: e.user_id == principal)` |

**没有 `local:player` 这种东西**（D45 已删除）：要判"这是不是人"一律看
`entity.is_account_bound()` / `entity.user_id`。

### 14.2 依赖强度：默认零依赖，只有需要 roster 才连玩家包

| 强度 | 写法 | 谁需要 |
|---|---|---|
| **零依赖**（默认） | 直接 `api.caller()` 拿"我现在是谁" | 移动、交互、战斗、背包……绝大多数包 |
| **软依赖** | `list_services()` 探测 + `call_service("<玩家包 id>", "avatars_of" / "active_avatar" / "switch_to", …)` | 需要"我的**全部**化身"的包：队伍面板、切换角色、共号 UI |
| **硬依赖** | `requires.plays: ["<玩家包 id>"]` | 仅"没有玩家包就没有意义"的包 |

⚠ **硬依赖的真实代价**（已核实，别踩）：`requires.plays` 是**全局包级**的——依赖未启用 →
**依赖者直接加载失败**；`disable` / `uninstall` 在有依赖者时**直接拒绝**（停玩家包要先停所有
依赖者）。而**世界激活是世界级**的（D15），`call_service` **不做世界过滤**——某世界没启用玩家包，
依赖者照样调得到它的服务（跨世界串味，见 GAPS G62）。所以：**别让所有包硬依赖玩家包**，
那会把它变成单点故障。

### 14.3 参考实现对外只暴露三个服务

`worlditor_play_player`（`tests/fixtures/plays/`）的口径，社区包按此对接即可：

| 服务 | 参数 | 返回 |
|---|---|---|
| `avatars_of` | `principal=""`（缺省 = 当前调用方） | `[{entity_id, name, map_id, row, col, in_world}]` |
| `active_avatar` | `principal=""` | 同上单条；没有则 `{}` |
| `switch_to` | `entity_id` | 切换后的摘要；**只接受调用方自己的化身**，否则报错 |

⚠ **在主体生命周期事件里要显式传 `principal`**：`on_principal_login` / `_logout` / `_deleted`
是 HTTP/CLI 路径触发的，**没有"当前调用者"上下文**（`api.caller_principal()` 是 `None`），
缺省解析出来是空的。另外 `switch_to` 这类服务拒绝时请抛 `WorldError`——
`call_service` 的异常隔离会把其它异常统一换成"服务执行出错，请稍后再试"，
只有 `WorldError` 的文案会原样透出（M3）。

它的工具名（`player_whoami` / `player_avatars` / `player_create` / `player_switch` /
`player_retire`）**不是契约**——玩家端界面按视图注册走，工具名由各包自定。

### 14.4 自己实现一个玩家包时，四个必须处理的点

1. **自举工具声明 `requires_entity=False`**（§7）：否则"创建第一具化身"自己就被挡住了。
2. **roster 从内核账本派生**，别再维护第二份名单：两份名单迟早不一致。
   要记的是**玩法状态**（"上次操作的是哪具"），那才放自己的 KV。
3. **落点自己定**（D45：内核没有出生点）：用 `api.list_locations()` 挑，或读自己的内容文件。
   挑不到（空世界）就造一具**不在世界上**的化身（合法状态，D36），等地图就绪再放进去。
4. **`act_as` 之前先校验归属**：内核不校验"这具是不是你的"（它没有名单），
   把客户端传来的 `entity_id` 直接交给 `api.act_as` 等于让任何人操控任何实体。
   反方向的 `claim_avatar` / `release_avatar` 由内核把关（只能认领/退掉**自己主体**的）。
5. **"登录后接着玩"只能做成惰性接管**（v0.8.0）：`api.act_as()` 写的是**凭据**指针，
   而凭据上下文**只在 MCP 工具 handler 里**存在（`world/mcp/__init__.py` 的工具包装器
   设置那几个 contextvar）——`on_principal_login` / `_logout` / `on_tick` 这些回调里
   **没有凭据**，在那里调 `act_as` 会直接抛"需要连接上下文"。而登录签发的**新凭据**
   `entity_id` 从空开始（§4 D-a 的固有代价）。两者一叠，能力边界是这样：

   | 想做的事 | 能做的地方 |
   |---|---|
   | 记录"这个主体上次操作的是哪具"（本包 KV） | 任何地方（主体事件里也行） |
   | 让化身**入场 / 移动**（`place_entity` / `move_entity`） | 任何地方（显式给 entity_id，不需要凭据） |
   | **把凭据指向某具**（`act_as`） | **只有工具 handler** |

   所以续玩要落在**读侧自举工具**上——谁先被调用谁完成接管。参考实现
   `worlditor_play_player` 的 `_resume()` 是个可直接抄的顺序：
   `caller()` 已指向**自己的**化身就不动（尊重本设备上次的显式选择）→ 查本包 KV 记的
   那具 → 只有**一具**就直接接上 → **多具且无记忆就不猜**（挑哪具是玩法判断，
   交给 `player_switch`）。它的视图在 `onMounted` 调一次 `player_whoami`，接管即完成。

   ⚠ **代价（如实记）**：**别的包的工具不认"上次那具"**——玩家重登后先去点别人的工具，
   会撞上工具门的"你还没有角色"。这是 D46 的必然结果（内核没有名单，就不可能替包选），
   缓解办法只有"客户端先调一次玩家包的读侧工具"（内置 WebUI 的视图挂载已经这么做了）。
