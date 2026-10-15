# Changelog

## v0.7.2（2026-10-16）

**修复 v0.7.1 的实体编辑面板白屏（D44 能力键改名未同步前端）。**

### 修复

- **点开任一实体就白屏**（v0.7.1 事故）：`EntityManager.vue` 的详情面板直读
  `capabilities.unknown_components`，而 D44 已把该键拆成 `orphan_components`
  （声明它的包不在了）+ `fictional_components`（`local:` 且查无声明）——后端不再返回旧键，
  模板里的 `.length` 抛 `TypeError: can't access property "length", ... is undefined`，
  Vue 渲染中断，**整个实体编辑 UI 不渲染**。列表单元格那处因为写了 `?.` 只是静默不显示，
  所以问题只在详情面板暴露。
- **能力读取收口到 `capsOf()`**：四象限缺键一律归一化成空数组，模板拿到的永远是能安全
  `.length` / `.join` 的形状——后端增删能力键不会再让界面整块崩掉。
- **详情面板补「声明已不在」一栏**：`orphan`（玩法包停用 / 卸载，启用即恢复）与
  `fictional`（虚构组件，本来就没有行为）分开显示；列表徽标也用 `⛔` / `⚠` 区分两者。
- **新增守卫 `test_entity_panel_capability_keys_match_backend`**：前端代码不得再读旧键
  （解释性注释不计入）、能力读取必须经归一化函数、四象限键名与后端 `capabilities()` 同源
  ——前后端各改一半这类漂移，CI 直接点名。

## v0.7.1（2026-10-16）

**实体模型 v2（D32–D40）全部落地；内核复合写入收束为单事务；实体编辑器按组件来源重构。**

### 新增（内核事务与索引）

- **实体位置内存索引（G42 / D39）**：新增 `store.entities_at`（`(map_id, row, col) → 实体 id 集合`）
  ——**只存内存、不落库**（纯派生数据，启动时按 `core:position` 重建），数据库结构不变。
  维护点覆盖启动载入 / `save_entities` / 复制地图 / 移动地块 / 删除实体 / 删除地图 / 注册 bundle；
  `list_entities(map_id, row, col)` 走索引。新增 `check_entity_position_index()` 自检
  （不变式：**在世界上**的实体恰好出现一次——按 `has_position()` 过滤，离线实体本就不该在索引里）。
- **复合地图编辑单事务**：`store.save_map_bundle`（地图 + 地块 + 实体 + 世界归属）、
  `store.move_location_bundle`（地块坐标 + 全图连接引用 + 其上实体位置）、`store.delete_map`
  （实体 / 地块 / 地图 / 归属）各自**一次提交**——原来逐条 `save_*` 在 WAL 下每行一次 fsync，
  失败还会留下半成品。`Revision` / `changed_tick` 一律**事务成功后**才写回内存对象。
- **创建地图可同时归属**：`create_map(world_id=…, folder_id=…)`（管理端同一参数）——
  世界或文件夹不存在时**拒绝且不留孤儿地图**。
- **身份注册单事务 bundle**：`store.save_registration_bundle` 把**实体 + 账户 + 凭据 +
  邀请码消费**放进一次提交（注册物化实体改为延迟落库）——失败时账户 / 实体 / token /
  邀请码都不进内存，不再出现"用户建了、码没消"这类半成品。无地图部署的注册与
  登录补建实体行为不变。

### 修复（可见性与管理端）

- **私有地图可见性收紧**：`/scene` 走统一的 `can_observe_entity()`（地图可见性 + 隐身一起判）；
  **SSE 按查看者过滤**（`subscribe(viewer_id, tier)`，private 地图的事件不再广播给无关凭据）；
  `list_actions(..., viewer_id=, tier=)` 对不可观察实体返回空菜单，`/scene` 的动作菜单带查看者身份；
  `interact(..., viewer_id=, tier=)` 增加授权上下文。
- **`POST /admin/connections` 支持部分字段更新**：只给 `enabled` 或只给 `paths` 都能用
  （此前缺失的一侧作为 `None` 传下去会被当成"要清空"）。

### 改进（实体编辑器按组件重构）

- **组件编辑器按来源分组**：`core:`（内核协议，**锁定不可删**）/ `local:`（本地内容）/
  各玩法包分栏显示，块头给出来源与组件数；`core:` 组件的删除按钮不再暴露
  （内核协议组件的存在语义由内核管理）。
- **实体详情增加组件摘要**：标题直接给名字 + 短 id + 组件总数，下面是全部组件键的
  chip 列表（`core:` 用强调色、虚构组件用危险色），能力面板与字段分组照旧按后端裁决显示。
- **空组件实体的空状态文案**：明确"空组件字典是合法状态"，引导改用 `local:` 组件。

### 实体模型 v2（第 2 期 D41 / D42 / D43）：能力 = 组件的存在，删 `kind` / `tags` 两列（表 v11）（BREAKING，DESIGN §12.6 / D41–D43）

### 破坏性变更（D41 能力面折叠）

- **实体没有"基底类型"了**：`Entity.kind` / `Entity.tags` **两个字段删除**，
  `entities` 表 **4 列**（`id` / `components_json` / `revision` / `changed_tick`，表结构 **v11**），
  `to_dict()` 只剩 **5 键**（`id` / `components` / `last_active_ts` / `revision` / `changed_tick`）。
  `kind` / `tags_json` 进**禁列名单**（旧库启动即拒绝）——**升级方式同前：删掉数据目录下的
  `world.db` 并重新启动**。`last_active_ts` 改为**只在内存**（在线状态，重启从 0 起）。
- **能力 = 带没带那个组件**：判断用 `entity.has_component("pkg:duel")`——**别**用
  `component(key) == {}`（纯能力组件的数据本来就是 `{}`，"空组件"与"没有这个组件"必须分得开）。
  要摘能力必须显式 `remove_component`（`remove_data` 删掉最后一个字段不会顺手删组件）。
- **声明只有一套**：`api.declare_component(name, interactions, label, fields, categories)`
  （`register_entity_kind` / `register_entity_tag` / `register_entity_type` 保留为**等价旧名**）。
  组件名 = `source:name`，裸名声明自动带上你包的 id；**两个包各声明 `merchant` 是两个组件共存**
  （"后注册覆盖"整条作废）。`register_entity_kind(tags=…)` **作废并报错**——
  "类型 = 一组组件的预设"归**实体模板**（`register_entity_template` 的
  `data = {name, desc, components}`）。
- **`local:` = 内容与跨包协作的公共命名空间**：世界内容包用 `local:` 写实体组件
  （内置演示世界已改为 `local:merchant` / `local:sign` / `local:door`），给这些内容加行为的
  玩法包**声明 `local:<同键>`** 即可对接——不再依赖包加载顺序。`<别人的 play_id>:` 依旧拒写（D43）。
- **字段清单按组件分组，不跨组件摊平**：`capabilities(entity)["fields"]` 现在是
  `{组件键: [字段]}`；`effective_fields(key)` 只看该组件；**同一组件内同名字段声明两次 → 报错**；
  `add_category_fields` **删除**（`categories` 只作"选取分组"，`list_kinds(category=…)` 保留）。
- **`capabilities()` 的键改了**：`components` / `active_components` / `inactive_components` /
  `unknown_components`（= **虚构组件**：没有任何声明，允许存在、不贡献能力）/ `interactions` / `fields`。
  `list_kinds()` 每条 = `key` / `source` / `name` / `label` / `interactions` / `fields` / `categories`
  （`implicit` / `preset_tags` / `play_id` 删除）。
- **实体编辑**：`update_entity` 不再有 `kind` / `tags`（能力就是组件，加/摘用
  `add_component` / `remove_component`）；`api.set_tags` 删除。`place_entity` 的 `kind` / `tags`
  降级为**输入便利**（落成组件键，裸名按 D41 解析：唯一声明者 → 用它；无人声明 → `local:`；
  多个声明者 → 报错），两者都可省（**没有能力组件的实体也合法**；`kind=""` 报错，不静默当"没有"）。
- **管理端**：`GET /admin/kinds` 只剩一张组件清单（`{"kinds": [...]}`，旧的 `types` / `tags` 两区删除）；
  实体创建 / 编辑端点返回 `{"id", "components"}`，PATCH 只接受 `name` / `desc` / `components`。
- **`parse_tags` 改名 `parse_names`**（名字列表的容错解析）；`TagSpec.implicit`、`EntityKindSpec`
  别名删除。

### 新增（D44：卸载 / 清理语义）

- **四象限诊断**：`capabilities(entity)` 现在是 `components` / `active_components` /
  `inactive_components` / **`orphan_components`** / **`fictional_components`** / `interactions` / `fields`
  （原来的 `unknown_components` 拆成后两个）。`orphan` = **声明它的包不在了**（停用 / 加载失败 /
  已卸载）；`fictional` = `local:` 且查无声明（本来就没有行为，不是坏了）。
- **`GET /admin/orphan-components`**：按来源分组的影响面（`state` / `package` / `purgeable` /
  `keys` / `count` / `sample`）。判定**先看目录在不在**，再看 `status`。
- **`POST /admin/orphan-components/purge`**：管理员手动清理**已卸载包**的遗留组件
  （`{source, keys?, dry_run?}`）。服务端强制只接受"包真的不在了"（停用 / 加载失败 → 400）；
  `local:` 永不可清；**默认 dry-run**；粒度按 source 或 keys，不支持按实体挑；
  ⚠ **不可逆**（数据没了 + 该实体的这项能力也没了）。事件复用 `on_world_edited`
  （`{op: "purge_components", …}`）。
- **`_tag_owner` 删除**：归属从**键里的 source + 规格的 `play_id`** 读，不再另存一份。
- **管理端"玩法包"页**：停用的包在列表里并显示"遗留组件 N"（启用即恢复、**不可清理**）；
  已卸载的包不在列表里 → 单开"组件遗留"栏，只有那一栏能清。

### 破坏性变更（第 1 / 1b / 1c / 1d / 3 期）

- **`Entity.attrs` / `Entity.state` 两个容器删除** → 统一为 `Entity.components`（组件字典）。
  组件名 = **`source:name` 信封**：`core`（内核保留）／`local`（编辑器手写）／`<play_id>`（包自己）；
  必须含一个冒号，字符集 = 字母/数字/`_`/`.`/`-`。
- **玩法包 API**：`set_attrs` / `get_attrs` / `set_state` / `get_state` / `remove_state` **已删除**；
  新增组件原语 `add_component` / `set_component` / `remove_component` / `get_component` / `list_components`；
  字段原语 `set_data` / `get_data` / `remove_data` 现在 **`component` 必填**。
- **`core:` 是内核保留命名空间**：玩法包写入直接报错（D33）；`core:` 组件的写入**绕过分派表**
  （玩法包既写不进、也拦不住）。
  **但正当能力不丢**：新增 **`api.set_perception(entity_id, {"invisible"| "see_invisible": bool})`**
  ——玩法包写 `core:perception` 的唯一窄口受控入口（与 D20"身份只能经身份服务改"同一范式：
  规则不放宽，能力不丢失）。管理端经 `update_entity` 可直接写 `components`（含 `core:`）。
- **阻挡机制整体移除**（D34）：`register_entity_kind(block_move=…)` 参数、`TagSpec.block_move`、
  `_is_blocking` / `_blocker_at`、`move()` 的阻挡检查、`STATE_BLOCK_MOVE` / `core:state` 全部删除
  —— **所有实体都不阻挡**。门的开关 / 机关 / 墙 / NPC 挡路归玩法包
  （`override_primitive("move")` 或过滤器链，D11 早已支持）。
- **`place_entity` / `update_entity` 的 `attrs=` / `state=` → `components=`**；
  实体模板负载 = `{kind, tags[], name, desc, components}`。
- **落库（第 1 期）**：`entities` 表 **13 列**（第 1c 期起 **10 列**、第 1d 期起 **7 列**——见表结构
  v9 / v10 条目），组件落
  `components_json`（原 `attrs_json` + `state_json` 合一）；
  删掉 `idx_entities_pos`——实测**没有任何 SQL 使用它**（实体相关 SQL 只有 `SELECT *` 与
  `DELETE WHERE id`），是 v4 遗留死重。
- **表结构版本 v8（第 1 期；1c 期起为 v9、1d 期起为 v10——闸再加一道「不该存在的列」，
  见下）+ 新增版本闸（两道检查）**：`_check_schema` 读
  `world_meta.schema_version` **和**一张「后加列清单」（`world_maps.sort` /
  `entities.tags_json` · `revision` · `changed_tick` · `components_json` /
  `templates.scope`），任一不符即**拒绝启动**，错误消息列出缺的列并指名
  `world.db` 与处理方式（不迁移，D13）。
  **原 `ALTER TABLE` 补列逻辑（`_ensure_columns`）整个删除**——补出来的
  `components_json` 是空默认值，会把旧实体的数据**静默清空**，比拒绝启动危险得多。
  两道缺一不可：只查版本记录的话，**没有版本记录的极老库 / 手造库**会在载入期撞出裸
  `IndexError`（一屏栈、没有"删哪个文件"的指引）。
  → **升级方式：删除数据目录下的 `world.db` 后重新启动**（会一并清空地图 / 地块 / 实体 / 账户，
  重建后需重新注册管理员）。
- **实体名字 / 描述 / 账户绑定进组件（v2 第 1c 期，DESIGN §12.4）**：`Entity.name` / `desc` /
  `user_id` 变成**只读 property**（派生视图）——分别读 `components["core:info"]` 的
  `name` / `desc` 与 `components["core:account"]` 的 `user_id`；缺失语义：`name` 兜底
  **`id` 前 8 位**、`desc` = `""`、`user_id` = `None`。写入走 `core:` 组件
  （**内核保留命名空间，玩法包不能直写**，D33）；管理端 `update_entity(name=…)` / `desc=`
  **只动 `core:info` 里的那一个键**，不碰同组件其它数据（传空 `desc` = 删该键，
  `name` 随即回落到 `id` 兜底）。
- **`to_dict()` 线上投影不再有顶层 `name` / `desc` / `user_id`**：消费者读
  `components["core:info"]["name"]`（**兜底到 `id` 前 8 位是既定语义**，DESIGN §12.4）。
  `Entity.from_dict` / `place_entity(name=, desc=, user_id=)` / 实体模板负载保留顶层三键作
  **输入便利**，会被折进对应组件——所以管理端 `POST` / `PATCH /admin/entities` 的
  `name` / `desc` 参数**照旧可用**（内部只有组件一种形态，不会两处存同一事实）。
  注意 `components=` 仍是**整体替换**，与 `name` / `desc` **不要在同一次 PATCH 里混用**。
- **落库（第 1c 期）**：`entities` 表 **13 列 → 10 列**——`name` / `desc` / `user_id` 三列删除
  （数据搬进 `components_json` 里的 `core:info` / `core:account`）；**表结构版本 v8 → v9**。
- **版本闸新增「不该存在的列」检查（v9）**：库里若还带着 `entities.name` / `desc` / `user_id`
  → **拒绝启动**，错误消息逐个列出这些列。理由：只查"需要的列在不在"查不出多出来的旧列，
  而那种库会**载入成功但名字 / 描述 / 账户绑定被静默丢掉**。
  → **升级方式同上：删除数据目录下的 `world.db` 后重新启动**（会一并清空地图 / 地块 / 实体 /
  账户，重建后需重新注册管理员）。
- **实体位置进组件（v2 第 1d 期，DESIGN §12.4 / D36）**：`Entity.map_id` / `row` / `col` 变成
  **只读 property**（派生视图）——读 `components["core:position"]`。**缺失是合法状态**：
  "**实体不在世界上**"（玩家下线 / 物品在容器里 / 传送中），三个 property 都返回 **`None`**
  （**不是** `""` / `0`——空值兜底会把"缺失"变成静默错误：实体静默出现在 (0,0)、静默参与
  按位置筛选）。新增 `has_position()` / `pos_key()`（无位置 → `None`）/ `require_position()`
  （"必须在场"的路径显式调用，如 `move()` / `_build_scene()`）/ `set_position()` /
  `clear_position()`。
  - **读点行为变化**：`list_entities` / `query_entities` 新增 `include_absent=False` 关键字参数
    ——**默认跳过不在世界上的实体**（`True` 时才带上）；按位置筛选时它们天然不匹配；
    `query_entities` 的排序键改用**哨兵值**（否则 `None` 会与 `str` 比大小而报错）；
    `lint_map` 的悬挂实体检查先跳过无位置实体（无位置 ≠ 地图有问题）。
  - **`move()` 对不在世界上的实体报错**「实体不在任何地块」——移动的前提是有位置。
  - **事件负载**：`on_entity_move` 的 `from` / `to` 可以是 `null`（实体从世界外移回来 /
    移出世界）。
  - **落库（第 1d 期）**：`entities` 表 **10 列 → 7 列**——`map_id` / `row` / `col` 三列删除
    （数据搬进 `components_json` 里的 `core:position`）；**表结构版本 v9 → v10**。
  - **版本闸扩到六列（v10）**：库里若还带着 `entities.map_id` / `row` / `col` → **拒绝启动**。
    理由比 v9 更硬：放行一个位置在表列里的旧库会得到"**每个实体都不在世界**"——
    那是"无必填"合法状态的**最坏误用**（迁移事故被合法语义掩盖，地图看着是空的但库是"好"的）。
    → **升级方式同上：删除数据目录下的 `world.db` 后重新启动**。
  - **`clear_position`**（内核 + 玩法包 API）：让实体**离开世界**（下线 / 收进容器 /
    传送中间态）——`core:` 直写对玩法包关闭（D33），若没有这条窄口受控入口，位置可选
    就成了一道**单向门**（造得出不在世界上的实体、却永远送不回去）。与 `set_perception`
    同一性质（§12.2：规则不放宽，能力不丢失）；`move_entity` 侧则早已放开"从不在场到在场"
    （它接受不在场的实体）。
  - **前端**：位置/名字的读法收进 `webui/src/entity.js`
    （`entityPosition()` / `hasPosition()` / `positionLabel()` / `positionSortKey()` /
    `withoutPosition()`），编辑器组件不再直接读 `e.row` / `e.col` / `e.map_id`——那些键
    **已经不存在**，读到的是 `undefined` 且**不报错**（按格过滤静默返回空、排序静默退化、
    地图网格静默画到 (0,0)）。实体列表的「位置」列对不在世界上的实体显示「不在世界」，
    「定位」按钮置灰。守卫在 `tests/test_editor_integrity.py`。
  - **新建实体可以"不进世界"**（不加坐标即可）：`place_entity` 的位置三参数变成可选，
    **要么全给、要么全不给**——半截坐标直接报错（`""` / `0` 兜底会把"忘了给"变成静默
    出现在 (0,0) 的实体）。管理端 `POST /admin/entities` 同一规则；玩法包 `api.place_entity`
    同步放开（物品放进容器、待投放的 NPC 由此可表示）。
  - **新增 `GET /admin/entities`**（跨地图的全部实体，含不在世界上的）+ 管理台**「全部实体」页**
    （G46）：支持 `?absent=0|1` 过滤、"放进世界"开关（不勾 = 造一个不在世界上的实体）、
    「定位」跳到地图编辑器并选中该格。地图详情是**地图视角**，按 `core:position` 裁，
    不在世界上的实体一个都看不见——没有这条全局入口就等于"内核造得出、编辑器管不着"。
  - **实体模板不再带位置**：模板是"这东西是什么"，不是"它在哪"——带上位置会让套用
    静默把实体搬回老地方（`withoutPosition()`）。

- **内核移除物品（D37，取代 D8）**：物品**定义与持有都下沉玩法包**——内核只有实体。
  删除面：`ItemDef` / `items` 表 / `store.items` / `save_item` · `delete_item`、
  `register_item_def` · `save_item_def` · `add_item_fields` · `get_item_def` ·
  `list_item_defs` · `delete_item_def` · `flush_item_defs`、
  `InteractionRequest.item_id` 与 `interact(..., item_id=…)` 参数、
  内核事件 `on_item_used`（**内核事件现为 7 个**）、
  `clear_play_registrations(keep_user_items=…)` 参数、`world.__init__` 的 `ItemDef` 导出。
  **替换关系**：物品**类型** → 组件声明（`register_entity_tag`：名字 + 字段 schema + 归属）；
  物品**实例** → 实体 + 组件；`use_action` → interaction 名；`stackable` / `icon` → 组件声明属性与字段；
  管理员手工维护的定义 → **实体模板**（`register_entity_template` 随卸载消失 /
  `save_template` 落 `templates` 表不受影响）；`item_id` 槽位 → `args`（自由 dict）；
  `on_item_used` → 玩法包**自定义事件**（事件总线本就支持任意事件名）。

### 未做（见 `GAPS.md` G40 / G47 / G48）

- **第 2 期（D41–D44 + 前端）已全部落地**：`core:info` / `core:account` / `core:position`
  已分别随第 1c / 1d 期落地，能力面与卸载 / 清理语义随本期完成——见上面的
  "能力面折叠"条目。**第 2 期到此完整**（本版即 v0.7.1 的版本 bump）。
- **实体模型 v2 的 D32–D40 亦全部落地**（数据面组件化 / `state` 退役与阻挡移除 /
  `kind`·`tags` 折叠 / 内核移除物品 / 位置索引 G42）：`DESIGN.md` §12 与
  `GAPS.md` G40 已同步为完成状态。**D40 的边界照旧不实现**——内核不做通用实体渲染、
  不做 `/components` 声明端点、不做组件渲染器（见 G43）。

## v0.7.0（2026-09-25）

**废弃全部内置行为玩法包（BREAKING，D31 / GAPS G39）**——内置目录里不再有"官方玩法"。

### 破坏性变更
- **删除 6 个内置领域包**：`worlditor_play_items` / `movement` / `social` /
  `interaction` / `player` / `starter`（1139 行 Python + 1013 行 JS + 其包自身测试
  43 个）。**内置只剩世界内容包** `worlditor_play_demo_world`（只导入示例世界数据，
  不注册工具/视图/服务/过滤器/kind）。
- **影响**：全新安装不再自带背包/视野/说话/交互/角色卡/出生礼包；玩家端默认**没有
  视图 tab**，世界数据仍在（有地可站）。升级现有实例：这些包的数据（`play_data`）
  留在库里，但没有任何包再读写它们。
- **理由**（完整论证见 DESIGN D31 与 GAPS G39）：这些包是按"内核机制逐项验收"切的
  （M3：一个机制一个包），**不是按玩法切的**；留作社区参考实现会教错地基。同时审计
  确认：**包间契约（属性键 / `play_data` key / UiBlock kind / 名字引用）在系统里没有
  任何表示**——不可见、不可校验、不可查询，包一多必然失去控制。

### 覆盖没有跟着被删（本轮的重点工作）
- **机制覆盖本来就在外壳测试里**，已逐一核实不依赖内置包：`test_engine`
  （ui_hook before/after/replace/递归）、`test_filters`（过滤器链三态/互斥/遮蔽）、
  `test_services`（跨包服务/异常隔离/清理）、`test_play_runtime`（视图注册/冲突/清理）、
  `test_admin_pages` 前四个（管理页协议，用夹具包）。
- **行为集成覆盖移交夹具包**：`tests/play_fixtures.py` 扩展——物品定义
  （apple/megaphone）、视图注册、`world_whoami` 产出 `character` 块并 `apply_ui_hooks`
  展开（部件聚合链）；新增更小的**探针夹具包**（工具 + 视图，供世界激活对照）。
- **新增提交在案的参考组件**（仓库里唯一的视图/管理页组件，也是文档的活例子）：
  `tests/fixtures/plays/worlditor_play_demo/web/view.js`（MCP 会话 + `wt-*` 样式约定）
  与 `web/admin-shop.js`（管理页代理端点）。夹具包安装时**复制**它们，而不是就地写占位符。
- **两处"目标消失后会静默空转"的守卫改指参考组件**：`test_web_view_styles`
  （视图组件样式约定）与 `test_version_consistency`（组件上报的 `clientInfo.version`）。
  两者原本扫 `builtin_plays/*/web/*.js`——包删掉后一个会红、一个会变成空循环。
- **重指受影响的内核测试**：`test_play_replacement`（原以 movement 包的 `move` 过滤器
  为互斥方 → 改为内联 mover 夹具包）、`test_world_activation`（原以 `world_look`/
  `world_say`/三个视图验世界激活 → 改为夹具包 demo + probe 对照）、`test_mcp_tier`
  （原调 `world_look` → 改调夹具工具）、`test_admin_pages`（G31「停用保留用户物品
  定义」回归测试 → 改用夹具包 + `api.save_item_def`）。
- 测试总数 **344 → 300**（删 43 个包自身测试、删 1 个内置包管理页端点测试，新增/改写
  的重指测试计入既有文件）；`ruff check` / `ruff format --check` / UTF-8 普查 / 4 套
  浏览器 E2E 全绿。

### 设计文档同步
- DESIGN：§1 架构图、§4.3 物理位置、§4.5 部件模式（**保留设计、标注实现归社区包**）、
  §5 行为归属表（内置不再提供任何行为能力）、§6 重写为「内置包（1 个世界内容包）」并
  **据实修订协作模型**（原文"零包间调用"在 D8/M3 引入跨包服务后已不成立，改为三档
  关系：事件 / 软依赖 / 硬依赖）、新增 **D31**。
- GAPS：新增 **G39**（含根因诊断与四条残留）、G6/G19/G20 状态更新（G19 已失效、
  G20 守卫改指参考组件）；编号范围更新为 `G1–G39`。

### 审查修复（同日，零玩法包视角的内核审查发现）
- **`instructions` 运行期刷新是死代码**：`_refresh_instructions` 写的是
  `mcp.settings.instructions`，而 SDK 的 `Settings` **没有**该字段 → 赋值抛
  `ValueError` 被宽 `except` 吞成 debug 日志，于是"随注册表刷新"从未生效：
  装/启用玩法包后 `tools/list` 更新了、`initialize` 的 instructions 不变
  （**工具在、说明书不在**）。改为写 lowlevel server 的 `instructions`
  （`FastMCP.instructions` 是只读 property 读它），并收窄异常处理。
- **零工具时的 instructions 文案不实**：原来说"未加载任何玩法包"，而世界内容包
  是加载着的（只是不注册工具）——v0.7.0 起内置只剩它，所以这句假话正是**每个
  全新安装的默认说明书**。改为"当前没有任何可用工具……也可能已装的包没有注册工具"。
- **`/plays/{id}/web/` 路径校验用 `str.startswith`**：`<pkg>/web-evil/x.js` 会被
  误判为"在 web/ 之内"（可读到包内 `web*` 兄弟目录）。改用 `Path.is_relative_to`
  ——与 PlayLoader 的路径安全检查同一套语义。
- **JSON-RPC 批处理请求不注入身份**：`_inject_identity` 遇数组直接 return，持合法
  play 凭据发批量 `tools/call` 一律被判"未认证"且**静默失败**。改为逐条注入。
- **G26 收口**：管理端 20 处裸 `int()` 统一走新助手 `_as_int`，坏入参 **400**
  （原先 500）；两个 app 都注册 `HTTPException → {"error": …}`，401/403/404 不再是
  纯文本（原先与"失败返回 `{"error":…}`"的约定矛盾）。
- **新增 `plays_changed` 信号事件**：`PlayLoader` 在 load_all / enable / disable /
  install / uninstall 之后广播，**另外** `engine.update_world(play_ids=…)` 改世界激活
  集合时也广播（reason = `world_plays`）——玩家看到的视图 tab 由**所在世界的激活集合**
  决定，只覆盖包生命周期是不够的。供前端 SSE 订阅，装/卸玩法包或改世界激活后自动刷新
  视图 tab，不再需要手动整页刷新（载荷 `{"event":"plays_changed","data":{"reason":…,…}}`，
  自定义事件的数据在 `data` 键下；刻意不写 world_log）。
- 新增回归测试 `tests/test_review_fixes.py`（8 条 → 后补世界激活一条共 9 条，逐条注明
  发现来源、位置与"不修会怎样"）；测试 300 → **309**。
- **玩家端 SSE 自动刷新视图 tab（第 4 条前端半边）**：`App.vue` 用原生 `EventSource`
  订阅 `/events?token=…`，只在 `payload.event === "plays_changed"` 时重拉 `/views`——
  选中视图仍在列表就原样不动（组件不重挂、状态不丢），消失了就回退到第一个可用视图或
  空态。生命周期：未登录 / 管理端口（无 `/events`）/ 退出登录一律不连，失败只
  `console.warn`（零 toast），403 后不重连。装/卸玩法包或改世界激活集合后，**玩家端
  无需整页刷新**。
- **管理页切页重载组件（第 2b 条）**：`PlayPageHost` 原先只在 `onMounted` 里 load，
  而宿主用常量 key 渲染 → 从管理页 A 切到 B 会渲染成 **B 的标题 + A 的界面**。
  改为身份化重载（`watch([playId, pageKey], load, {immediate:true})` + 加载期清空
  `comp` + `loadSeq` 竞态守卫丢弃迟到结果），`AdminPanel` 的宿主 key 也带上
  `play_id/page_key`（结构层保证"实例身份 = 路由身份"）；顺带修掉一个每次挂载都
  加、从不摘除的 `hashchange` 监听泄漏，以及"错误行与加载中同时显示"。
- **夹具包新增第二个管理页**：`tests/fixtures/plays/worlditor_play_probe/` 现在含
  视图与管理页组件（`PROBE-PAGE-MARKER` 作为切页验收锚点），两个夹具组件文件都
  **提交在案**并由夹具安装时复制（与 demo 包同一约定）。
- 独立的浏览器验收（`.uitools/`，不入库）：`verify_sse_refresh.mjs`（停用/启用包 →
  tab 自动增减，且用 window 标记证明**全程未重载**）与 `verify_page_switch.mjs`
  （A→B→A 切换无错组件、无残留）——两条既有 4 套 E2E 都不覆盖。E2E 结果：
  `EDITOR V0.5 UI OK` / `MAP GOVERNANCE UI OK` / `WORLD GOVERNANCE UI OK` /
  `V0.2.0 UI OK`，外加 `SSE REFRESH OK` / `PAGE SWITCH OK`。
- **`custom` UiBlock kind / `register_ui_component` 统一文档口径（不实现）**：
  内核注册表只写不读、既无 list 也无 HTTP 出口，前端渲染器只显示 `fallback_text`
  （`component`/`props` 一个字节都不读；旧注释写着"组件加载 v4.2"，从没来）——
  包作者照文档做自定义界面只会看到一句降级文本，**无报错、无日志、也无法自救**。
  DESIGN §4.1 / PLAY_DEV §4 / `model.py` 的 kind 说明统一标注**预留未实现**，并给出
  替代路径（自定义界面用 `register_view` + provider；往块里加内容用 `register_ui_hook`）。
  GAPS G35 同步。**不实现**：`register_view` 已覆盖其全部价值，`custom` 的唯一额外
  能力是"UiBlock 树内联自定义组件"，当前无真实需求，真做时代价一样。

### 部署事故修复：不兼容的历史数据改为「拒绝 + 说清楚」（v0.6.0 线上启动崩溃）
- **现象**：自建容器启动即退出，栈落在 `store._load_all → parse_map →
  parse_text_schedule`，末句是 `文案格式：{…}（收到 str）`。
- **根因**：库里的地图描述是**纯字符串**。v0.1.x 有两条播种路径——`store.py` 写
  结构化、`v4store.py:329`（v4 路径）直接 `json.dumps(字符串)`——两者共用同一个
  `world.db`；v0.5.2 收紧解析器（G34）后，这类库**启动即崩**。`model.py` 原先的
  注释断言"读取路径不存在需要容忍的历史形态"，该前提**只对 v3 播种路径成立**。
- **裁定（D13 不变）**：**不迁移、不容忍、不自动清理**——只把失败信息变得可执行。
  新增 `IncompatibleDataError`（`WorldError` 子类）：`_load_all` 读
  maps / locations / templates 时定位坏行（**逐字段单独解析**，只在失败路径执行），
  抛出「表 / 行键 / 字段 + 删除 `<数据目录>/world.db` 后重建（可先 mv 留档）」；
  `cli` 捕获后打印这段话并以**退出码 1** 结束，**不再打一屏 traceback**。
  不自动删行：数据删除必须是操作者按下去的动作。
- **顺带**：`_serve` 的启动失败路径现在会先 `service.stop()`——原先启动抛错时
  SQLite 连接与心跳任务被丢下不管。
- **回归测试**：`tests/test_text_schedule.py` 新增 7 条（模块 docstring 从"守住三条"
  改为四条）——旧格式描述 / 地块描述 / 连接 label 各自指到**正确的字段**、坏 JSON 报
  "不是合法 JSON"、**抛错时数据库一个字节都没改**（拒绝 ≠ 静默降级）、正常库跨重启
  照常载入（防误报）、CLI 端到端（指引 + 退出码 1 + 无 `Traceback`）。测试 309 → **316**。
- 独立复现（`.uitools/`，不入库）：造一个含该老行的库，用**真实 CLI** 跑一遍确认
  输出与退出码。副作用记录：`parse_location` 对**非法方向键**仍是静默忽略
  （`if d in DIRECTIONS`），即"连接方向写错"不会报错只会少一条路——与本次的严格
  拒绝口径不一致，记为待议（未改）。

### 前端登录态修复：失效凭据在界面上没有出口（"网页不用登录就能进"）
- **现象**：删库重启后打开玩家端，**不显示登录页**，直接进到"已登录"的界面
  （空视图 + header 两个按钮），点什么都失败，且没有任何提示。
- **根因不在服务端**（实测：无凭据 / 陈旧凭据下 `/state`、`/scene`、`/world/mcp`、
  `/auth/logout` 一律 401；免认证的只有 `/meta`、`/views` 与注册类），而在**客户端**：
  登录与否只由 `localStorage` 里"有没有一串字符"决定（`App.vue` 的 `hasToken`），
  从不向服务端校验；而唯一会清掉失效凭据的自愈路径是 `api.js` 里"某个非 `/auth`
  请求收到 401"——启动只打 `/meta` 与 `/views`，两个都免认证、**恒 200**，于是
  **这条自愈永远不会触发**；SSE 的 401 也只 `console.warn`（零提示）。
  → "凭据失效"在 UI 上零出口：不显示登录页、不报错、不清凭据。
- **修法**：`/meta` 增加 `authenticated`（有效时补 `tier` / `entity_id` / `username`），
  两个端口共用 `meta_payload`；前端启动时若本地有 token 而 `authenticated === false`
  → 清凭据 + 回登录页 + 提示"登录凭据已失效，请重新登录"。**零新增端点、零额外请求**
  （`/meta` 本来就必打一次）；判定用 `=== false`，老服务端无此字段时维持原行为。
- 顺带修掉一个"每次刷新都闪一下登录页"的老毛病：`store.token` 原先只在 `onMounted`
  里从 localStorage 读入 → 首帧必然先渲染登录页（已登录的玩家每次刷新都看得见）。
  改为**模块加载时就位**。
- 顺带：界面从此有了"我是谁"的依据（原先 header 完全不显示身份与档位）。
- 测试：`test_meta_endpoints` 扩展 + 新增
  `test_meta_reports_stale_token_as_unauthenticated`（有效 / 伪造 / 无凭据 / 吊销后
  四种状态 × 两个端口）；`docs/HTTP_API.md` §1、§2.1 同步；`webui/dist` 重新构建。
- 独立浏览器验收（`.uitools/verify_stale_token.mjs`，不入库）：陈旧 / 有效 / 无凭据
  三种初始状态各跑一次，断言最终界面、本地凭据是否被清、提示语是否可见 →
  `STALE TOKEN OK`；另用既有 `verify_sse_refresh.mjs` / `verify_page_switch.mjs`
  回归前端改动 → `SSE REFRESH OK` / `PAGE SWITCH OK`。
- 同族记录：与"`rm -f` 对错路径静默成功""`instructions` 刷新失败被吞掉"一样——
  **失效没有信号**。

## v0.6.0（2026-09-24）

**按 ECS 对照清单补齐 A–D 四项**：一次架构自问"我们现在算 ECS 吗"引出逐项盘点
（实体 ✅ / 组件只有声明 ✅ / **查询 ❌** / **调度 ⚠ 隐式** / **删字段 ❌** /
**变更检测 ❌**）。裁定：**除 E（组件独立存储 / archetype / SoA / 并行系统）外全补**——
补这四项让玩法包能用 ECS 式写法写逻辑，同时不动存储形态、不丢 D21 世界治理。
设计结论与新边界写进 DESIGN §11（新增决策 D26–D30）。

### 新增：实体查询原语（D26 / GAPS G38）
- **`engine.query_entities` / `api.query_entities`**：按 `tags`（AND）、`exclude_tags`、
  `map_id` / `world_id` / `row` / `col`、`viewer_id` 感知、变更游标、`where` 谓词筛选，
  稳定排序 `(map_id,row,col,id)` + `limit`。此前玩法包要"所有带中毒标签的实体"只能
  `list_entities()` 全量拿 + 自己筛（movement 看一次视野打 9 次位置查询）。
- **标签匹配按 D21 激活语义**（避免"query 说是商贩、菜单说没动作"）：标签由某包声明、
  而该包**未加载**或在该实体所在**世界未启用** → 不匹配；无声明者的实例标签
  （`set_tags(["my_marker"])`）照常匹配。为此新增**标签归属记忆** `_tag_owner`
  （停用不清、真卸载 `purge` 才清——否则停用包声明的标签会"诈尸"成纯数据标签）。
- 包含与排除共用同一份"活标签集"，语义天然对称；**严格校验**（拼错的地图/世界、
  空标签报错，不静默返回空）。
- 老接口 `list_entities` 行为不变（宽松位置筛选、不校验地图存在），与 query 共用
  **G12 感知判定**（`_filter_perception` 单一判定点）。

### 新增：事件执行顺序（D27）
- **`register_world_event(..., phase=, order=)`**：同事件执行顺序 = `(phase, order, 注册序)`，
  `phase ∈ input → simulate（缺省） → present`，未知名报错；覆盖**全部事件**（含 `on_tick`）。
  注册时排序，emit/心跳热路径不排序；不给参数 = 注册序（老行为不变）。
  动机：跨包顺序原本等于"包加载顺序"这个隐式事实，包一多就成了不能碰的意外契约。

### 新增：删字段原语（D29）
- **`remove_data`（进分派表：可被过滤/覆盖/禁用）与 `remove_state`**——D23"不静默丢字段"
  的另一半：能**明确地删**，而不是只能"整体覆盖 attrs"顺手连坐别人的字段。
  字段不存在 = 幂等 `False`（不落盘、不发事件、不推进变更号）；删除发
  `on_entity_changed {attrs_removed:[name]}` / `{state_removed:[name]}`。

### 新增：变更检测（D28）
- 实体新增 `revision`（全局单调写序号，**落库那一刻盖章**——`save_entities` 是唯一盖章点，
  写入路径不可能漏盖）与 `changed_tick`（tick 窗口；`_tick_once` 每轮 +1，**哪怕没有任何
  on_tick 订阅者**）。库结构 v7（`entities.revision` / `changed_tick`，老库自动补列）。
- 全局号与业务写**同一事务**落 `world_meta`，启动在**任何写之前**续号 → 重启不回退
  （漏报是这类机制里唯一不可接受的错）。
- 两个增量游标：`changed_since_revision`（精确，既不多报也不漏报）/
  `changed_since_tick`（窗口粒度，宁可多报绝不漏报）。
- 出口：`/state` 顶部带 `revision`/`tick`，实体序列化自带两字段，SSE payload 也带。

### 设计记录
- **DESIGN**：新增 §2.5（事件顺序与变更检测）、**§11「与 ECS 的关系」**（逐项对号 +
  E 项不采纳理由 + "为什么不该整体转 ECS"），§9 标题 → D1–D30 并补 D26–D30 五行；
  §1/§2.1/§2.2/§2.3/§2.4/§3.1/§4.1/§4.2 同步（原语表 + `remove_data` + `query_entities`、
  实体字段 + 两枚戳、注册面 + `query_entities`/`current_tick`/`world_revision`）。
- **GAPS**：新增 G38（A–D 已落地 + 五条残留：线性扫描待倒排索引、只到实体级变更、
  `where` 不可用于工具、地图级可见性不进查询、事件顺序管理端不可见）；
  G35 那条"5 个可覆盖原语"的过滤器链表述随 D29 更新为 6 个。
- **PLAY_DEV**：§5 拆成 §5.1 原语与过滤器 / **§5.2 实体查询** / **§5.3 事件顺序** /
  **§5.4 变更检测与增量遍历**（各带可抄的代码块与"标签活性"语义说明）。

### 测试
- 新增 28 条：`test_entity_query.py`（8：标签 AND/exclude、世界激活、停用/真卸载、
  范围与排序、感知过滤、where/limit、严格校验、play API 出口）、
  `test_event_phases.py`（6：阶段优先、order、注册序兜底、on_tick、校验、API 出口）、
  `test_change_detection.py`（8：盖章、批量同号、无写不跳号、tick 无订阅者也走、
  两游标、重启续号、SSE payload、实体序列化）、
  `test_primitive_remove_data.py`（6：默认实现、重启保留、幂等 no-op、state 对称、
  分派三态、override/disable）；`test_world_service.py` 的 `/state` 断言补
  `revision`/`tick`/实体 `revision`。**316 → 344 条全绿**。

## v0.5.2（2026-09-24）

**文档规整 + 六处静默缺陷修复**：v0.5.1 发布后对项目与文档做了一次全面审查
（后端 / 前端 / 文档三路），先把文档里"说过头、说过期、互相打架"的地方对齐，
再修掉审查揪出的六条**静默**缺陷——都是"数据悄悄丢了""功能悄悄不生效"这类
用户看不出来的问题。

### 修复：数据正确性（G28–G31）
- **文案格式统一为一种**（G28，G24 同族）：过去"纯文本"与"结构化 JSON"两种写法
  并存，`08:00–18:00` 的单时段文案被当纯文本读进来又存回去 → 时间窗静默丢失，
  差异预览还显示"无变化"。现在**全链路只有结构化一种格式**：
  - 内核 `parse_text_schedule` 只认 `None` 与 `{"periods": [...]}`，**纯字符串直接
    报错**（消息带格式示例）；**非法条目不再静默丢弃**而是整段报错；
    `WorldError` 抽到 `world/errors.py`（`world.engine` 仍可导入，旧路径不破）；
    地块模板的文案也在**保存点**校验（模板 data 原样入库，不能等套用才炸）；
  - 前端 `webui/src/textSchedule.js` 只剩 `scheduleToJson` / `parseScheduleText`
    两个函数，出口与地块描述**都是 JSON 编辑框**（没有纯文本模式），非法就不提交；
  - 内置世界包 `world.json`、测试夹具、DESIGN / PLAY_DEV / HTTP_API 全部改成唯一
    格式（历史纯文本只在**显示**时归一成标准结构）。
- **JSON 写坏不再清空整袋数据**（G29）：`FieldForm` 的 `attrs`/`state` 原始 JSON
  非法时过去会 `|| {}` 把整个容器替换成空对象再提交；现在**拒绝落盘**并保留旧值，
  错误提示也移出默认折叠的 `<details>`。
- **复制地图不再丢实体标签**（G30）：`copy_map(with_entities=True)` 漏传 `tags=`，
  带 `spawner` 的实体复制后变裸实体。
- **停用 items 包不再删掉管理页建的物品定义**（G31）：物品定义区分"代码声明"
  （`api.register_item_def`）与"用户数据"（新增 `api.save_item_def`）——停用/整体
  卸载保留用户数据，只有真卸载（删包目录）才删；顺带修掉 `delete_item_def` 的归属
  记账与管理页 update 的"先改后校验"。

### 修复：功能空转与崩溃（G32–G34）
- **`async def teardown(api)` 现在会被 await**（G32）：过去不检查 awaitable，
  "在 teardown 里取消自管后台任务"（G5 约定）静默不生效。
- **`/views` 真正按调用者世界过滤**（G33）：`/views` 免认证，中间件过去遇到公共
  路径直接放行且**不解析 token** → 过滤退化成匿名/默认世界。现在"免认证 = 不要求
  凭据，不等于忽略凭据"，带了 token 就解析身份。
- **编辑器删格/空图后"在此新建地块"不再崩**（G34）：`primary` 为 null 时保存逻辑
  读 `null.row`，异常被 Vue 吞进 console，界面毫无反馈。现在选中格在加载后必有
  具体坐标（初次打开落出生点），删格后保留该格坐标可就地重建。

### 文档规整
- **新增 `docs/HTTP_API.md`**：玩家端口 + 管理端口全部端点的路径/档位/请求体/示例
  （此前管理端 12 个端点、`/auth/*` 与 CLI 参数在文档里零覆盖）。
- **README 备份命令改正**：原先 `-v worlditor-data:/data` 的卷名与 compose 实际
  卷名（`<项目目录名>_worlditor-data`）不符，`docker run` 会新建空卷 → **备份静默
  变空包**；改为按服务 `docker compose exec … tar`，并补恢复步骤与 CLI 参数全表。
- **DESIGN**：§9 标题（D1–D16 → D1–D25）、头部版本范围、D24 补 v0.5.1 三视图修订、
  §8 M4 的"⏳ 正式发布"改 ✅；新增**编号说明**（A/B/C/R/P0 与新旧两套 G 编号的关系）；
  §4.2 去掉"`/state` 同步遵守隐身过滤"的错误承诺（标注未实现 + 指向 G12 尾巴）；
  §3.0 的 `world_list`/`world_travel` 标注"未实现"、新增**文案（TextSchedule）唯一格式**
  一行；§4.3 补物品定义生命周期。
- **GAPS**：G1 从"✅ 已解决"降级为"⚠ 部分解决"（`list_maps` 过滤参数与
  `/scene`/SSE/interact 从未做）；G8/G20/G23 状态过期修正（G8 早已解决、G20 已解决、
  G23 的"按 kind 过滤"v0.5.1 已做）；G6/G7 补状态（交付物在 PLAY_DEV §11）；
  G16/G17 更正行号并复核——**两条 ⏸ 全部仍成立**；新增 G25/G26/G27 与
  "v0.5.2 审查未修清单"G35/G36/G37。
- **PLAY_DEV** 补 7 个漏掉的公开方法（`create_location` / `get_item_def` /
  `list_item_defs` / `delete_item_def` / `apply_ui_hooks` / `list_admin_pages` /
  `flush_item_defs`）与 `save_item_def`；**NGINX_DEPLOY** 更正"端口都收敛到回环"
  的说法（实际 6288 是 `0.0.0.0`，公网暴露靠防火墙）。

### 版本串一致性
- 新增 `tests/test_version_consistency.py`：`pyproject` / `__init__` / CHANGELOG /
  `webui/package.json`（含 lock）/ 4 个内置视图上报的 `clientInfo.version` 必须全部
  等于当前版本（此前前端与视图还停在 `0.1.0`）——发版漏改一处 CI 直接点名。

### 测试
- **316 passed**（v0.5.1 的 284 + 32 条新回归：文案格式统一 19、编辑器完整性守卫 5、
  版本一致性 3、窗口文案往返 1、复制地图标签 1、停用保留物品定义 1、`/views`
  调用者世界 1，另含地块模板文案在保存点的校验）。六条修复都能**反向复现**：
  把旧行为改回去，对应测试立刻红。
- E2E `verify_editor_v05.mjs` 扩到 **54 项全绿**（新增：文案只有一个结构化编辑框、
  无纯文本模式开关、非法 JSON 不提交并报错、时间窗保存后仍在、删格后原地重建、
  JSON 写坏不清空数据、实体保存差异预览）；另三套 E2E 回归通过。

## v0.5.1（2026-09-17）

**编辑器重排为三视图 + 可视化地图可缩放**：v0.5.0 的地图编辑 / 实体 / 模板挤在一个
纵向长页里，谁都不好管。现在按"一次只做一件事"拆成三个可切换视图，地图视图不再
纵向滚动、可视化面板占据主区，实体视图按"一张图上千实体"的规模重做，并且可以从
地图上选一个地块直接管那一格的实体。

### 变更：三个可切换视图
- 顶部 `🗺 地图编辑 ｜ 🧍 实体 N ｜ 🧩 模板 N`（带数量）；地址可深链：
  `#/admin/maps/{id}`、`#/admin/maps/{id}/entities`、`#/admin/maps/{id}/templates`
  （`replaceState` 切换，浏览器后退不受干扰）。
- 编辑器壳高 = 视口内（`100vh`），**地图视图不纵向滚动**：左侧可视化画布吃掉剩余
  空间，右侧侧栏（地块 / 本格实体 / 出口）自己滚；「地图信息与危险操作」收进
  折叠区，给画布让位。

### 新增：可视化地图（缩放 / 平移 / 适应）
- **滚轮以光标为中心缩放**（25%–250%），工具栏 `－ / 百分比 / ＋ / 适应 / 1:1`。
- **拖空白平移**；另加**平移模式**开关——开启后拖任意处都平移，且"平移过就不误触发
  格子点击"（4px 阈值）。默认模式仍是"拖格子框选"。
- **「适应窗口」**按内容尺寸缩放并居中；小图最多放到 150%（不再把三个格子撑满屏）。
- 网格右下多留一行一列 + 地块面板的坐标输入框：包围盒之外与负坐标都能去。

### 新增：实体视图（按规模设计）
- 工具条：**搜索**（名称 / 类型 / 标签 / id）+ **类型筛选** + **标签筛选** +
  **排序**（位置 / 名称 / 类型）+ **分页**（50 / 100 / 200 每页，含"第 x / y 页"）。
- 列表列：名称（含描述摘要）、类型、标签、位置、**能力摘要**（挡路 / 动作 /
  ⚠未注册 / ⏸未激活）、快捷操作（定位 / 删除）。
- 右侧**详情面板**：名称 / 描述 / 类型（身份实体锁定）/ 标签（TagPicker）/ 字段
  （FieldForm，声明外走原始 JSON）/ 合并后的能力 / 保存 / 存为模板 / 定位 / 删除。
- 「＋ 放置实体」：从模板 / 类型 / 标签组合创建，带坐标。

### 新增：地块级实体管理
- 地图视图选中地块后，侧栏出现「**本格实体**（N）」：列出该格实体，可就地
  `编辑`（跳到实体视图并打开详情）/ `删除`。
- 「**在地块外管理 ›**」跳到实体视图并**锁定该地块**（工具条出现"只看地块 (r, c)"）。
- 实体列表的「定位」回到地图视图并选中它所在格（primary 高亮）。

### 新增：接口
- `GET /admin/maps/{id}` 的 `entities[]` 带上 **`capabilities`**（服务端算的合并能力，
  已按世界过滤）——编辑器不再自己重算并集，也就不会与内核规则漂移。

### 测试 / 文档
- 样式守卫增至 **17 条**（新增：三视图可切换 + 画布缩放/平移、实体视图规模化与
  地块过滤）；E2E `verify_editor_v05.mjs` 扩到 **41 项全绿**（新增三视图、缩放、
  实体视图筛选/详情、地块 → 实体 → 定位 的往返），另三套 E2E 回归通过。
- 共 **284 passed**。DESIGN §4.3.3 更新为三视图 + 缩放 + 规模化实体的形态。

## v0.5.0（2026-09-17）

**实体声明体系 + 编辑器重构**：`kind` 从"决定一切的身份标签"退化为**预设的标志位**，
**能力由标签承载**（一个实体可以既是玩家、又挂刷怪笼标签）；地图编辑器重写为
**不依赖任何玩法包的世界数据编辑器**，并修掉 G24（连接编辑器会**静默**丢
跨图目标 / 权重 / 文案）。

### 新增：实体标签体系（D18–D21 / D25）
- **`Entity.tags[]`**（有序、去重保序）+ `entities.tags_json` 列（`_ensure_columns`
  幂等补列，旧 `world.db` 直接可用，`SCHEMA_VERSION` 6）。标签顺序有语义——
  参与字段覆盖优先级。
- **类型与标签共用一个命名空间**：`register_entity_kind("door", ...)` 现在就是注册
  一条**隐式同名标签**（`implicit=True`）——**旧玩法包与全部既有测试零改动**
  （~60 处 `place_entity("player", …)` / `register_entity_kind` 调用一行没动）。
- **新 API**：`register_entity_tag(tag, label, block_move, interactions, fields, categories)`
  声明一条可叠加的能力标签；`register_entity_type(kind, tags=[...])` 表达
  "类型 = 标签预设"（`A = {A, C}`、`B = {B, C}`，即本次需求的原话）。
- **`add_tag_fields`**（旧名 `add_kind_fields` 保留）语义扩张为"给**所有带该标签的
  实体**加字段"——顺手销掉 D9 里"B 包拿字符串改 A 包命名空间"的别扭做法。
- **能力并集规则**（D19）：`block_move` **任一标签为真即阻挡**（`state["block_move"]`
  仍是最高的动态覆盖）；`interactions` 并集；`fields` 覆盖顺序**定死** =
  隐式 kind 标签 → 实例 tags（数组序）→ 分类字段。**不做负标签**（要"去掉"就换
  kind）；**允许未注册标签**（编辑器可手输，实体照常存在，只是不贡献能力）。
- **逐标签世界激活过滤**（D21）：标签所属玩法包在某世界未启用 → 该标签不参与并集
  （没装刷怪笼包的世界里，刷怪笼标签静默失效）。
- **身份判定只看基底 kind**（D20）：标签里写 `player` 不改变身份，
  `IDENTITY_KINDS` 的 4 处保护一行未改——"删标签绕过 D14"的路径根本不存在；
  NPC 升格为可登录角色必须经身份服务换基底 kind。
- `EntityKindSpec.tick` **死字段已删**（写了从没被读过、`list_kinds` 也不返回）；
  `EntityKindSpec` 改名 `TagSpec` 并保留旧别名。`list_kinds()` 现在同时返回类型与
  标签，带**来源包 / 是否隐式 / 预设标签**。
- `place_entity(..., tags=[...])`、`update_entity(..., tags=/kind=)`、`api.set_tags()`、
  `api.capabilities(entity)`（合并能力诊断，含 `inactive_tags` / `unknown_tags`）。

### 新增：模板统一（D22）
- `templates` 表加 **`scope`**（`location` / `entity`）——解决"地块模板与实体模板
  撞名"；**地块模板补上"套用"**（语义早在模型注释里写好、一直没实现：
  同图目标按相对偏移平移、跨图目标原样复制、目标格已被占则拒绝）。
- **实体模板 = 玩法包注册（内存，随包卸载消失）+ 管理端本地（落库）**，合并成一个
  选择列表（同 id 本地优先，`source` 标明来源）；负载 `{kind, tags[], name, desc,
  attrs, state}`，套用后仍可改。不做多实体模板（"房间模板"留待真实需求）。

### 修复：G24 连接编辑器静默损坏数据（D23）
- **问题**（v0.1 起就存在，实测复现）：在编辑器里打开一个地块再保存，
  跨图出口的 `map_id` 消失（变成同图、出口变原地打转）、路径权重全被抹成 1.0、
  路径文案被写成 `"[object Object]"`——**且是循环把 4 个方向全量重写**，
  改一个方向会毁掉其余三个方向；lint 也抓不到（损坏后的目标地块存在）。
- **修法**：出口编辑改为**结构化表单**（目标 = 地图下拉 + 坐标 + 权重；
  文案 = 纯文本或分时段 JSON），并且**凡是整对象替换的保存都先弹差异预览**
  （旧值→新值，取消即不落盘）——新增全局 `askDiff()` / `DiffModal`（同确认层套路）。

### 新增：编辑器重构（D24）
- 拆成 **地图网格 / 地块面板 / 出口面板 / 实体面板 / 模板面板**（原 780 行单体组件）。
- **网格**：多选（Ctrl/⌘）、**框选**（按住拖过格子）、**出口方向箭头**（简版可视化）、
  右下多留一行一列 + 坐标输入框（包围盒之外与负坐标都能去）。
- **多选复制粘贴**：复制选中地块（存相对位移）→ 粘贴到锚点，已占格跳过；
  同图出口按位移搬、跨图出口原样。
- **移动地块**：接上 `engine.move_location`（内核早有、一直没有入口）——
  原子重写自身坐标 + 全图指向它的连接 + 其上实体。
- **实体面板**：类型（可自由输入）+ 标签组合（勾选已声明 / 手输未注册）+ 按声明
  渲染字段控件（`FieldForm`）+ 未声明字段原始 JSON 兜底 + `attrs`/`state` 分开标注
  （提示 `block_move`/`invisible` 等内核约定键）+ **合并后的能力预览**（挡路/动作/
  字段/未激活/未注册标签）。
- 管理端新增 **`GET /admin/kinds`**（类型 + 标签清单，编辑器下拉与标签勾选的数据源）、
  `GET /admin/templates?scope=`、`POST /admin/templates/apply`、
  `POST /admin/locations/move`。

### 顺手项（G23 清单）
- 批量搬家报进度（"已移动 k/N + 失败清单"，不再只弹第一条错误）；
- 跨世界总览页可直接**新建地图并归属**；
- 组织树行内 **▲▼**（或聚焦行 `Alt+↑/↓`）排序——拖拽之外的键盘/按钮替代；
- `GET /admin/lint?world_id=`：只算本世界的地图（未归属地图算在默认世界）；
- 编辑器拆分后仍**全程无原生 confirm/prompt/alert**（有测试守着）。

### 变更 / 兼容
- `register_entity_kind` 去掉 `tick` 参数（死字段）；`EntityKindSpec` → `TagSpec`
  （旧名保留别名）。**其余全部向后兼容**。
- `add_kind_fields` 语义扩张（只影响"带该标签的实体"，比原先"kind 精确相等"更符合直觉）。
- 数据层加两列（`entities.tags_json` / `templates.scope`），旧库自动升级。

### 测试 / 文档
- 新增 `tests/test_entity_tags.py`（**24 条**）：隐式同名标签、组合（玩家+刷怪笼）、
  类型预设标签、并集与冲突规则、字段覆盖顺序、未注册标签、身份只看基底 kind、
  逐标签世界过滤、缓存失效、持久化与解析、模板（相对平移/跨图原样/占位拒绝/
  两种来源/卸载清理/负载校验）、管理端 `/admin/kinds` 与模板接口。
- `tests/test_map_governance.py` 增至 **22 条**（新增 `locations/move`、身份类型锁定）；
  样式守卫增至 **15 条**（编辑器分面板、diff 预览、结构化出口、schema 表单、网格多选）。
- 浏览器 E2E 新增 `verify_editor_v05.mjs`（**31 项全绿**，含 G24 逐字段回归 +
  "取消 diff 不落盘"）；`verify_map_governance_ui.mjs` / `verify_world_governance_ui.mjs` /
  `verify_v2_ui.mjs` 全部回归通过。
- 共 **282 passed**。
- 文档：DESIGN §3.1（标签模型与解析规则）、**新增 §4.3.3 编辑器**、决策表
  **D18–D25**；PLAY_DEV 注册面/动作/模板段全面更新（含逐标签世界过滤的写包须知）；
  GAPS 的 G21/G22/G23/G24 全部收口。

## v0.4.0（2026-09-17）

**管理端地图治理**：把「世界 → 组织树 → 地图」这一层的管理能力补全，并修掉
v0.3.0 组织树页的三个真实缺陷。地图编辑与玩法包**彻底解耦**——编辑器只认内核
字段，玩法包提供"名词表"做增强（实体声明体系见 v0.5 / GAPS G21）。

### 修复（v0.3.0 组织树页的真实缺陷）
- **第三层文件夹在 UI 里完全看不见**：页面只渲染两层（`store` 早就支持任意层级、
  防环逻辑也写好了），现在**递归渲染任意层级** + 折叠。
- **二级文件夹里的地图移不出来**：那层地图行根本没有移动入口——现在拖拽与
  「移动」面板对所有层级一致可用。
- **`world_maps.sort` 从建表起没被写过**（永远是 0，顺序实际由名字决定）：
  新增 `sort` 列（`_ensure_columns` 幂等 `ALTER TABLE`，旧库自动补列）+ 排序全链路。
- **删除非空文件夹的文案与引擎行为不符**：旧文案承诺"子文件夹与地图回到世界根"，
  引擎实际直接拒绝——现在真的先**把内容上移到上级节点**再删除（空文件夹直接删）。

### 新增
- **组织树（世界地图页重写）**：
  - 拖拽移动（文件夹↔文件夹、地图↔文件夹）与**同级排序**（拖到行之间），
    拖到文件夹上 = 放进去，拖到空白处 = 移到世界根末尾；把文件夹拖进自己或
    自己的后代会被拒绝（前端拦截 + 引擎 `防环` 双保险）
  - **文件夹与地图共用一个序号空间**：容器内 `sort` 构成全序，新建/移入默认排到
    末尾；`POST /admin/worlds/{id}/reorder` 一次性绝对化整个容器的序号
  - 面包屑聚焦（点文件夹显示完整路径、「＋ 文件夹」在聚焦节点下新建）、
    内联重命名、按名称/地图 id 搜索（命中子节点时父文件夹保留）
  - 行内操作：编辑 / 移动（含**跨世界**）/ 复制 / 删除；打开编辑器时按地图归属
    回填侧栏世界上下文
- **地图搬家（统一入口）**：`POST /admin/maps/{id}/move`——世界 / 组织节点 / 序号
  三者可任意组合；**跨世界自动落到世界根**（旧节点不属于新世界）；`world_id=null`
  = 解除归属（地图保留，运行时按默认世界规则）。
- **地图复制另存**：`POST /admin/maps/{id}/copy`——地图元信息 + 全部地块 + 连接
  另存为新地图；**同图目标重写为副本自己**（副本内自洽）、**跨图目标原样保留**
  （作者写的跨图连线）、**身份化实体永不复制**（人是人，不是布景）、
  可选 `with_entities` 带布景实体、归属默认跟随源地图（同世界同组织节点，排到末尾）。
- **地图体检**：`GET /admin/lint[?map_id=]`（引擎 `lint_map` / `lint_maps`，纯数据
  检查）——**死连接**（主目标不存在；运行时是**静默剔除**，只有体检能提前告知）、
  意外目标失效、孤立地块（无进无出）、无出口 / 无入口、**出生点落空**、
  **实体悬空**、未归属世界、空地图；错误 / 提示两级，按严重度排序。
  地图行显示 ⚠ 徽章，点开列出问题原文。
- **跨世界「全部地图」总览**（`#/admin/maps`，侧栏「通用管理」入口）：全部地图
  表格（地图 / 世界 / 组织路径 / 地块 / 实体 / 可见性 / 体检 / 操作）、
  世界与「未归属世界」过滤、搜索、**多选批量归属与转移**（含批量解除归属）、
  孤儿行高亮；旧链接 `#/admin/worlds` 收敛到此页。
- **交互统一**：管理端**不再使用原生 `confirm`/`prompt`/`alert`**（iframe/沙箱
  环境下会被浏览器直接屏蔽，且样式与暗色主题脱节）——新增站内确认层
  `askConfirm()`（`webui/src/confirm.js` + `ConfirmHost.vue`，Promise API，
  Enter 确认 / Esc 取消）与内联编辑组件 `InlineEdit.vue`；全部页面（账户、邀请码、
  玩法包、世界设置、地图编辑器、地图治理）一并替换。

### 变更
- **`#/admin/maps` 语义**：从"地图选择器"变成**跨世界全部地图总览**；地图编辑器
  一律带地图 id（`#/admin/maps/{map_id}`），不带 id 时自动跳转到总览页。
- 管理端地址栏**统一规范化**（旧链接与新式路由都收敛到规范地址）。
- `engine.assign_map/move_map_folder`、`api.assign_map` 支持 `sort`；新建文件夹
  默认排到末尾（原为固定 0，会插到最前）。
- `world_maps.sort` 列 + `SCHEMA_VERSION` 5（`_ensure_columns` 幂等补列，
  旧的 `world.db` 直接可用，无需手工迁移）。

### 测试 / 文档
- 新增 `tests/test_map_governance.py`（**18 条**）：排序全序与落盘、批量重排、
  跨容器校验、跨世界搬家、同节点重挂保留原位、副本目标重写与实体可选、
  体检八类问题、管理端 REST 全链路（建文件夹→排序→搬家→复制→体检→删除）。
- 新增样式守卫 4 条（治理页形状、**禁用原生弹窗**、确认层挂载、跨世界入口）。
- 浏览器 E2E `verify_map_governance_ui.mjs`（**25 项全绿**）：三级文件夹可见、
  拖拽移动与排序、防环拒绝、内联重命名、体检徽章与明细、复制另存、跨世界移动、
  统一确认层删除、非空文件夹内容上浮、总览批量归属、旧链接收敛、编辑器往返、
  **全程零原生弹窗**；`verify_world_governance_ui.mjs` 与 `verify_v2_ui.mjs`
  同步适配新交互并回归通过。
- 文档：DESIGN §3.0（`sort` 与序号空间）、§4.3.1（导航与路由）、**新增 §4.3.2
  地图治理**、决策表 **D17**；PLAY_DEV 地图编辑段补 `assign_map(sort)`；
  GAPS 新增 **G21**（实体声明体系评估，v0.5 方向）与 **G22**（编辑器增强候选）。
- 共 **249 passed**。

## v0.3.0（2026-09-16）

**多世界治理**：世界从"数据表里的一个字段"变成真正的治理单位——管理端以
世界为参考系（通用管理 / 世界下拉 / 该世界的玩法包与地图），每世界的玩法包
启停**在运行时装真生效**（GAPS G15 收口）。地图治理（组织树）与世界概念相对
独立，本轮只做世界层。

### 新增
- **管理端侧栏 = 通用管理 + 世界上下文**：
  ```
  通用管理            账户管理 / 邀请码
  世界 [下拉] ＋ ⚙     玩法包（本世界启停）/ 地图（本世界）
  玩法包管理页（可收起） 各包注册的管理页（按当前世界激活集合过滤）
  ```
  路由带世界：`#/admin/world/{id}/plays`、`#/admin/world/{id}/maps`；
  选中世界存 localStorage，地图编辑器按地图归属回填世界上下文；
  旧链接 `#/admin/plays`、`#/admin/worlds` 自动收敛（URL 规范化）。
- **每世界玩法包启停页**：`play_ids` 空 = 「全部启用」/ 非空 = 「自定义」
  二态（切自定义时以当前已加载包生成名单，不改数据结构、旧数据语义不变）；
  每行一个「本世界 启用/未启用」开关（全局未加载的包置灰并说明）；
  全局 enable/disable/uninstall 收进「高级：全局加载状态（影响所有世界）」。
- **世界地图页**：该世界的组织树（多级文件夹）+ 建图**自动归属当前世界** +
  「未归属世界的地图」区（一键归属本世界）；`engine.delete_world` 的删除保护、
  文件夹增删改移保持不变。
- **世界设置弹层**（侧栏 ⚙/＋）：id（创建后不可改）/ 名称 / 描述 / 删除世界。

### 修复 / 行为变更（G15 收口：能力面全路径按世界过滤）
- **MCP 工具**：动态工具入口按**调用者所在世界**检查，未激活 → 明确拒绝
  （"「竞技场」未启用该玩法包（worlditor_play_movement）……"），不再照常执行。
- **原语覆盖/过滤器**：`_dispatch_locked` 按**行为主体所在世界**过滤——
  未激活者视为不存在、**回落内核默认实现**（语义定为"这个世界的规则里没有它"，
  不是"拒绝调用"；disable 登记同理会"复活"为默认实现）。
- **kind**：`block_move` 与 `available_actions`（动作菜单）按实体所在世界过滤
  （未激活世界里墙不挡路、动作不出现在菜单里，与 interact 的拒绝判定同源）。
- **玩家视图**：`GET /views` 按调用者世界过滤（未激活包的 tab 不出现）。
- **部件 UI**：`apply_ui_hooks` 按查看者世界过滤（注入方不在该世界 → 不注入），
  交互结果与角色卡两条路径都传了查看者实体。
- **未归属世界的地图**改按**默认世界**的激活集合算（此前 = 全部激活，等于
  逃逸世界过滤）；管理端建图即归属 + 孤儿地图一键归属，避免踩坑。

### 测试 / 文档
- 新增 `tests/test_world_activation.py`（4 条）：工具 + 视图端到端（真实 HTTP
  + MCP 会话）、原语过滤器、kind 阻挡与动作菜单、ui_hook 注入——共 **228 passed**。
- 前端防回归：侧栏必须带世界上下文与「通用管理」、旧页面文件不得复活。
- DESIGN §3.0（世界过滤全路径表）/§4.3（全局层 vs 世界层）/新增 §4.3.1（管理端
  导航）、D15 更新；PLAY_DEV §3 写包须知（不要假设工具在所有世界可用）；
  GAPS G15 结项并列出仍留项（world_list/world_travel、按世界出生点、/state
  数据边界、跨包服务仍全局）。

## v0.2.1（2026-09-16）

**管理端导航改造**：玩法包注册的管理页从"玩法包详情里的一个 tab"升格为
侧栏一级分组——管理端导航只反映"有哪些治理入口"，不再按包组织。

### 变更
- **玩法包管理页进侧栏**：所有 `register_admin_page` 注册的管理页，在管理端
  侧栏自成一级分组「玩法包管理页」——**可收起展开**（状态存 localStorage，
  刷新后保持；当前所在管理页会自动展开以免找不到自己）、当前页高亮、
  分组内条目显示页图标 + 标题。多个玩法包都注册管理页时，条目前补显示
  所属包名（单个包时省略，避免噪音）。
- **注册表变化实时同步**：安装/启用/停用/卸载玩法包后侧栏分组即时增删
  （玩法包页广播 `worlditor:plays-changed`，侧栏重取 `/admin/play-pages`），
  不需刷新页面；管理页被停用/卸载而失效时也会同步收缩。
- **玩法包页不再重复列管理页**：去掉「管理页」tab（以及对应的清单拉取与
  入口按钮），详情页只保留 工具/服务/视图/原语 —— 管理页入口统一在侧栏。
- **管理页去掉"返回玩法包"按钮**：管理页现在是管理端的一个导航页面，
  页头只留标题与 `play_id · page_key` 标识。

### 修复
- 管理端加载时不再多打一次 `/views`（404）：`store.mode` 在 `/meta` 回来前
  是默认值 `play`，token watcher 会误判为玩家端口——加 `metaReady` 门闩。

### 文档
- DESIGN §4.6 / PLAY_DEV §13：管理页入口 = 管理端侧栏分组（可收起展开、
  实时刷新、多包显示包名），玩法包详情页不列管理页、管理页无返回按钮。

### 测试
- 新增 `tests/test_web_view_styles.py` 两条源码级防回归：侧栏必须承载管理页
  分组（含收起记忆与 `plays-changed` 刷新）、玩法包页不得再拉 `/admin/play-pages`
  且管理页不得有返回按钮——共 **223 passed**。

## v0.2.0（2026-09-15）

**内核边界收口**：内核不再内置任何世界内容、身份类型统一。审查报告与决策
记录见新增的 `docs/CORE_AUDIT.md`。

### 破坏性变更
- **内核不再播种世界内容**：原本硬编码在 `store.py` 的 41 地块主题世界
  （小镇广场/步行街/AstrBot大道/开源小区/迷雾森林 + 商贩·阿福/告示牌/木门）
  整体外置为**世界包** `worlditor_play_demo_world`（`world.json` 数据 +
  `async setup` 导入；地图已存在则跳过、不覆盖用户改动）。空库只建一个空的
  「默认世界」：0 地图/0 地块/0 实体/0 物品——"删光地图重启复活"的老问题
  随之消失；喇叭物品定义改由 social 包注册（谁用谁注册）。
- **移除 agent 实体类型**：实体 kind 只有 `player`（人类玩家与 agent **不区分**）
  ——`IDENTITY_KINDS` 权威定义移入 `model.py`；无密码自助注册
  （`/auth/agent-register`）创建的实体 kind、实体名（不再加 `AI·` 前缀）与
  凭据 kind 一律为 player；礼包/视野等判定同步统一。
- `PlayLoader` 支持 `async def setup(...)`（世界包导入需要写世界）。

### 新增
- **管理端安装玩法包**：`POST /admin/plays/install`（zip 字节流上传）+ 玩法包页
  「安装玩法包（zip）」按钮——单顶层目录/play.yaml+main.py/体积/路径穿越/命名
  校验齐全，加载失败自动回滚目录；零包部署终于有自助闭环。
- **MCP instructions 动态化**：按当前工具集生成（不再写死某几个工具名），
  零工具时明确提示"当前世界未加载任何玩法包"，工具集变化时自动刷新。
- `tests/world_fixtures.py`：测试世界夹具（`seed_test_world` 最小十字世界 /
  `install_demo_world` 演示世界），全部测试据此适配新基线。

### 修复
- `worlditor_tier` 真正生效：read（围观）凭据在工具调用入口被拒绝并给出明确
  文案（此前只写不读，工具授权全靠玩法包自觉）。
- 玩家端登录后不再硬编码跳 `#/world`（导致"有视图也显示没有任何视图"）——
  改为按 `/views` 进默认视图；未登录不再预加载视图组件（避免 401 留下误导性
  toast）；全局错误 toast 4 秒自动消失。
- 玩法包卸载/停用清理其注册的持久化物品定义（不再残留"幽灵物品"）。
- `block_move` / `invisible` / `see_invisible` 提为协议常量（`model.py` 导出）。
- **解掉零包部署死锁**：内核不再播种地图后，"没有地图就注册不了账户"会让
  管理员也进不去管理端启用世界包——身份层改为：无地图时账户与凭据照常发放
  （`entity_id` 为空）、登录不阻塞，世界就绪后登录/注册自动补建 player 实体。

### 文档
- 新增 `docs/CORE_AUDIT.md`：零玩法包审查（剩什么/真空什么/内容伪装成内核
  的清单）+ 决策记录 + 待办（出生点与世界·地图治理等）。
- DESIGN / PLAY_DEV / README 同步：世界包、身份统一、安装端点、async setup。

### 测试
- 全量测试适配"内核无世界内容"新基线；新增 `tests/test_mcp_tier.py`
  （档位消费端到端）与 `test_register_and_login_without_map`（无地图不死锁）。
  共 **221 passed**。

## v0.1.18（2026-09-15）

- refactor: **内置 movement 包移除「朝向」概念**（设计决策：内置包不钦定具体
  玩法机制）——"朝向/视角"是玩法包的发挥空间，不该由内置包强加：
  - 删除 `world_turn` 工具、`attrs["facing"]` 约定、相对方向（forward/back/
    left/right）换算；`world_move` 直接用内核地块连接槽的绝对方向
  （up/right/down/left）——玩家/agent 不必"先转身再前进"（少一轮往返、
    少一次换算错误）
  - G14 过滤器演示保留并改为**方向别名归一**：`上/北/north` → `up`（中英文
    方位都能收，对 LLM 更友好）；`world_move` 缺 direction 时明确报错
  - `world_look` 返回 `location`（当前地块）与中文可走方向，不再有 facing
  - 视图 `web/view.js`：去掉「你面向 ▲ up / ← 左转 / 右转 →」，改为**点相邻
    格直接走**（箭头提示 ↑→↓← + 中文方位），顶部显示当前地块名
  - 包版本 0.1.0 → 0.2.0（破坏性：工具集变化）
- test: `tests/test_plays_movement.py` 同步重写（11 项）——含防回归
  `test_package_has_no_facing_concept`（包内不得再出现朝向/相对方向字样）
- docs: PLAY_DEV §5 过滤器示例 / §11 命名契约（移除朝向行，注明朝向不在内置
  约定内）/ §12 内置包一览；DESIGN §5 行为归属（朝向移动 = 玩法包自定）

## v0.1.17（2026-09-15）

- fix: **玩家端视图"整片发白、样式崩坏"**——三处根因一并修：
  - 玩家端布局样式类**从未定义**（`.app-header`/`.view-tabs`/`.view-host`
    在 styles.css 中不存在，遗留的是底部导航时代的 `.tab`）：视图 tab
    竖排堆叠、两个悬浮按钮完全重叠、`.app-main` 为 `overflow: hidden`
    导致内容不可滚动、无内边距
  - 玩法包视图组件（背包/世界/日志）**硬编码白底浅色**（`#ffffff` /
    `#f4f4f4` / `#f7f7f7` / `#ddd` …）→ 暗色主题下白底 + 浅色文字看不清；
    且按钮全是**裸 `<button>`**（浏览器系统浅色样式）
  - 修复：styles.css 补齐玩家端头部/胶囊 tab 条/可滚动内容区/空态样式，
    新增**组件样式基石 `wt-*`**（标题行/卡片/格子/按钮/列表/折叠 JSON）；
    `bag.js`/`view.js`/`log.js`/`profile.js` 全部改用 `wt-*` + CSS 变量
- feat: 视图导航改**胶囊 tab（横向可滚动）** + 头部内联图标按钮（退出/注销，
  不再悬浮重叠）；内容区可滚动 + 移动端安全区适配
- feat: 界面可读性打磨——角色卡标题与**中文属性标签**（金币/出生礼包…，
  未知 key 原样显示，身份 kind 中文）、世界日志中文事件名 + 关键字段摘要 +
  「详情」折叠原始 JSON（不再一坨 JSON 糊在列表里）
- test: `tests/test_web_view_styles.py` 防回归（布局类缺失 / 组件硬编码浅色 /
  裸按钮 / `.view-host` 结构）；`tests/test_plays_player.py` 同步中文标签断言
- docs: DESIGN §4.4「视图样式基石」、PLAY_DEV §8 样式约定 + §13 管理页样式

## v0.1.16（2026-09-10）

- fix: **玩家端从局域网 IP / 域名打开时 MCP 初始化 `421 Invalid Host header`**
  （界面报"mcp 初始化失败 http421"）——MCP SDK 在 `host=127.0.0.1`（FastMCP
  构造默认值）时会自动开启 DNS rebinding 保护且只放行 `127.0.0.1:*` /
  `localhost:*` / `[::1]:*`，而世界服务默认监听 `0.0.0.0`（本就是要被局域网 /
  域名 / 反代访问的）。内核改为**显式构造** `TransportSecuritySettings`：
  默认关闭 Host 校验；鉴权仍是主要防线（`/world/mcp` 必须 Bearer token）
- feat: **MCP Host / Origin 白名单可配置**——`WORLDITOR_MCP_ALLOWED_HOSTS`（含
  CLI `--mcp-allowed-hosts`）收紧到指定 Host（无端口条目自动补 `:*` 变体，
  浏览器 Host 头带端口；Origin 按 http/https 同源派生，避免浏览器带 Origin 头
  时 403；`WORLDITOR_MCP_ALLOWED_ORIGINS` 可整体覆盖派生值）
- test: `tests/test_mcp_transport_security.py`（真实 uvicorn + 非 localhost
  Host 头端到端：局域网 IP / 域名放行、白名单收紧后名单外仍 421）
- docs: DESIGN §4.4「MCP 传输安全」、README 配置表、NGINX_DEPLOY 反代说明

## v0.1.15（2026-09-10）

- feat: **玩法包管理页改为管理端独立路由页面**（`#/admin/pages/{play_id}/{key}`，
  PlayPageHost 宿主 + 返回按钮 + 深链接直开）——替代弹窗形式：复杂配置玩法包
  可在管理页内自建二级面板/分栏，避免弹窗套弹窗；导航「玩法包」项联动高亮
- feat: 管理页组件可读 `page` prop（{play_id, key, title, actions}）
- docs: DESIGN §4.6 / PLAY_DEV §13「管理页 = 独立路由页面」约定（组件可自建二级面板）

## v0.1.14（2026-09-10）

- fix: **视图/管理页组件协议失效（G3 遗留重症）**——组件文件为 IIFE
  `(function (Vue, UiBlock) {…});`，但加载器 `new Function("Vue","UiBlock",code)`
  的函数体无 return、也不调用该表达式 → 工厂返回 undefined：**玩家端视图
  一直显示"无视图"、管理页一直"加载管理页组件"**。加载器改为
  `return (<code>)(Vue, UiBlock);`（App.vue / PlaysPage.openPlayPage 两处）
- fix: **视图内 MCP 调用全部 400（Missing session ID）**——streamable HTTP
  要求先 initialize 拿 `Mcp-Session-Id` 头；4 个视图组件
  （bag/view/log/profile.js）的 callTool 补 `ensureSession()` 懒初始化 +
  请求头带会话
- fix: 管理端「物品管理」页实测打开（物品定义 3 项 CRUD + 新建表单）；
  玩家端背包视图实测渲染**出生礼包真数据**（背包 2/20：苹果×3、面包×2）
- test: 防回归 `test_web_component_protocol_guarded`（内置包 web 组件 IIFE 形态
  + MCP 会话管理静态校验）
- docs: DESIGN §4.4 视图协议 / PLAY_DEV §8 组件协议表述修正（IIFE 形参注入 +
  MCP 会话约定）；§13 管理页组件协议同步

## v0.1.13（2026-09-10）

- fix: **管理端布局改 PC 优先**——管理台脱离玩家端 720px 容器（App.vue 重构，
  `admin-shell` 全宽 + 230px 固定侧边栏 + max 1200px 内容区；窄屏 <900px 降级
  顶部横滚导航）；玩家端保持移动优先不变
- fix: **管理端路由切换**——登录后 hash 残留（#/world/#/auth）导致导航状态
  错乱：进入时规范化到默认管理页；点击导航立即切换（不依赖 hashchange 时序）
- fix: **管理端通用样式类缺失**（.card/.table/.ops/.tag 等无定义）导致账户页
  等布局异常——styles.css 增补管理端样式块（PC 表格/滚动包裹/窄屏降级）
- fix: 世界页地图入口原先收在 `<details>` 折叠里不可见（"找不到地图编辑器"）
  ——根目录与文件夹改为默认展开平铺展示
- fix: 退出登录按钮被玩家端全局 `.logout-btn`（fixed 右下角）样式劫持——
  管理端改用 `.side-logout` 归位侧栏底部
- test: 管理端 UI 端到端验证脚本（Playwright + 系统 Edge，.uitools/ 本地工具
  不入库）：导航四页切换 + 地图编辑器进入 + 布局断言全通过
- fix: **.gitignore GBK 编码损坏导致 CI 发布失败**——追加 .uitools/ 行时用
  PowerShell Add-Content（GBK 编码）写入中文注释，hatchling 构建时读取
  .gitignore（VCS 排除模式）UTF-8 解码崩溃（0xb1），`pip install -e .`
  在 CI 失败（release 不产镜像）；已以纯 UTF-8 重写并全仓库编码普查

## v0.1.12（2026-09-10）

- feat: **管理端重构（多页面）**——侧边栏导航拆分：账户管理（搜索/角色筛选/
  分页/排序 + 玩家实体与凭据概览 + 凭据明细吊销）、玩法包（产品库 + 详情
  tabs：管理页/工具/服务/视图/原语覆盖与过滤器）、邀请码（独立页平移）、
  世界与地图（世界 CRUD + 组织树 + 地图归属）
- feat: **玩法包管理页注册协议（DESIGN §4.6 / PLAY_DEV §13）**——
  `api.register_admin_page(key, title, icon, component_url, actions)`；
  `GET /admin/play-pages` 清单 + `POST /admin/play-pages/{play_id}/{page_key}/{action}`
  锁内代理（异常隔离，tier=admin）；组件协议同视图（new Function 动态加载）；
  **数据语义归玩法包**（内核不裸露 play_data 编辑）
- feat: **items 包「物品管理」页**——物品定义 CRUD（id/name/desc/icon/stackable/
  use_action/attrs），创建/更新即落库（flush_item_defs）；web/admin-items.js 组件
- feat: **地图编辑器**——网格视图（地块卡片/四向连接标记/实体徽标）+ 地块
  新建/编辑/删除 + 连接（多路径/目标/文案）+ 实体列表/放置/定位/编辑 +
  模板管理 + 地图元信息编辑（名称/可见性/出生点/时区）
- feat: 后端新端点——账户检索（q/role/page/page_size/sort）、账户凭据明细
  （/admin/accounts/{id}/tokens）、地图列表/详情（/admin/maps GET）、模板列表、
  地块 upsert（/admin/locations POST 创建或更新）、地图 PATCH、实体 PATCH、
  物品定义删除（engine.delete_item_def + api.delete_item_def）
- feat: 玩法包 API 新方法——`register_admin_page`/`list_admin_pages`、
  `delete_item_def`
- docs: DESIGN §4.6 管理页注册协议；§5 行为归属表（账户管理/玩法包内容治理）；
  §6 items 包行更新；PLAY_DEV §13 玩法包管理页规范
- ⚠️ 兼容注意：`GET /admin/worlds` 的 maps 字段由 id 列表改为
  `[{id, folder_id}]` 对象（管理端组织树需要）；`/admin/accounts` 保留
  `accounts` 键（新增 total/page/page_size 与行扩展字段）

## v0.1.11（2026-09-10）

- fix: **玩家壳零部件引用彻底化**——world_profile 移除对 items 包的
  探测与调用（`ITEMS_PLAY`/`_has_service`/`bag_get`/返回 `bag` 键全部删除）：
  背包文本信息归 items 包 `world_bag` 工具，背包面板仍由 ui_hook 注入——
  player 包 main.py 零部件引用（新增静态契约测试 test_player_shell_zero_part_reference）
- docs: DESIGN §4.5 / PLAY_DEV §11 软依赖表述更新（玩家壳零引用；
  `list_services` 探测方式不再作为消费方推荐模式）
- ⚠️ 工具返回结构变化：`world_profile` 不再返回 `bag` 键、text 不含背包摘要
  （agent 查背包请用 `world_bag`——行为零损失）；内核零改动

## v0.1.10（2026-09-09）

- feat: **背包追加到玩家界面（玩家聚合视图）**——player 包 world_profile 生成
  角色卡 UiBlock 并经 `api.apply_ui_hooks` 服务端展开；items 包注册
  `ui_hook("character", "after")` 追加背包面板（list 子块，经 bag_get 服务读取）
  ——玩家视图 = 角色卡 + 各包 hook 追加的面板，**player 包零依赖不变**
- feat: 玩法包 API 新增 `WorlditorPlayAPI.apply_ui_hooks(block)` 透传
  （服务端展开注入；软依赖天然：部件包未装 → hook 不存在 → 无该面板）
- refactor: profile.js 重写——视图组件改经 MCP 工具 `world_profile` 取
  `{text, ui}` 并用 UiBlockRenderer 通用渲染（替换手写属性表 + /scene 依赖）；
  视图配色对齐暗色主题（var(--text-dim)）
- test: 新增「world_profile ui 聚合背包面板（items 在）」「无 items 时仅角色卡」
  两个用例；36 受影响测试 + 全量通过
- docs: DESIGN §4.5 部件「工具/视图」行更新（hook 注入玩家聚合视图）；
  PLAY_DEV §11 玩家部件加「UI 注入」约定 + §12 表注记；GAPS 记 G20
- ⚠️ 玩法包 API 兼容（新增方法）；内核零改动

## v0.1.9（2026-09-09）

- refactor: **玩家部件模式落地（阶段 1+2，DESIGN §4.5）**——`worlditor_play_player`
  拆分为「玩家壳」（角色视图 + world_profile，**零包间依赖**）+ 新包
  `worlditor_play_starter`（出生礼包，requires items）；world_profile 背包摘要
  改为**软依赖**（list_services 探测 bag_get，items 未装时仅显示属性）
- feat: 新内置包 `worlditor_play_starter`——出生礼包独立可停用/可替换（社区
  同 play_id 覆盖即自定义礼包）
- docs: DESIGN §4.5「玩家部件模式」定稿（部件 = 数据/服务/工具/视图 + 生命周期；
  数据默认玩家级跟人走、世界级可选）；DESIGN §5/§6、PLAY_DEV §11/§12、README
  同步（5 个 → 6 个领域包）；GAPS 记 G19（包裹覆机制未背书，观察）
- test: 测试迁移与新增——礼包用例移至 test_plays_starter.py；新增
  「player 无 items 仍可加载」「world_profile 软依赖」价值主张测试
  （42 受影响用例 + 全量通过，见验证）
- ⚠️ 内核零改动；玩法包 API 不变（player 包去掉 requires = 纯增益）
- fix: **阶段 3 视图注入落地（G18 解决）**——ui_hook 接线到 interact 结果
  （`_interact_default` 返回前 `apply_ui_hooks`，服务端展开、WebUI 零改动），
  端到端测试 test_interact_result_applies_ui_hooks
- fix/feat: **视图安全硬化**——`register_view` 校验 provider.url 必须站内本包
  （`/plays/<play_id>/web/…`；WebUI fetch 附 Bearer，防跨站凭据外泄）；
  相对/跨站/跨包地址一律拒绝（WorldError）
- docs: 视图注入双通道定稿（DESIGN §4.4 表：ui_hook=已接线 / 挂载点 slot=
  设计稿；PLAY_DEV §8 url 校验 + 注入说明）；GAPS G4 更新（UiBlock 路径闭环、
  slot 待实现）、G18 标记已解决
- ⚠️ 内核小改（_interact_default 接线 + register_view url 校验）；玩法包 API
  兼容（仅 provider.url 新增校验——现有内置包均站内前缀，无影响）

## v0.1.8（2026-09-09）

- fix: **管理端前端暗色主题配色修复**——AdminPanel 卡片/表格/危险色硬编码
  浅色（`#fff`/`#e2e2e2`/`#eee`/`#b00020`）与全局暗色主题（近白文字）冲突，
  白底白字难以阅读（v0.1.3 引入，v0.1.5 未及）；全部改用主题变量
  （`--bg-2`/`--bg-3`/`--text`/`--danger`）；webui dist 重构建
- fix: **P0-1 锁语义收敛**——原语分派入口（override / 过滤器链 / 默认实现）
  与 MCP 工具回调改在引擎锁内执行（AsyncRLock 任务级可重入），`emit` /
  `call_default_primitive` 入口自持锁；DESIGN §2.4「handler 锁内执行」
  承诺与实现重新对齐，多段「读-判-写」从此原子
- test: 新增 2 个并发回归测试（override 分派 / MCP 工具两路，修复前可稳定
  复现丢失自增 n=1 → 修复后 n=2）
- docs: DESIGN §2.4 并发模型 + PLAY_DEV §11 锁约定（任务级重入红线：
  子任务禁止调引擎 API）+ GAPS G5 状态更新
- ⚠️ 玩法包 API 与对外行为不变（193 测试全绿）；handler 并发窗口收紧
  （锁内执行即设计意图）

## v0.1.7（2026-09-01）

- refactor: **移除 `mcp-stdio` 入口**——本地/远程 agent 统一走
  `worlditor serve` 的 MCP streamable HTTP（`/world/mcp`）；删除
  stdio.py、CLI 子命令、`fixed_identity` 全链路（`build_mcp_server`/
  `attach_mcp`/`build_dynamic_tool`）与 stdio 端到端测试；文档同步
  （README/DESIGN/PLAY_DEV）
- refactor: 内核清理——删除 effects 结算（D12 无 effects）、`on_say`
  事件负载（9→8 事件）、`Player`/模板解析函数（model）、未用
  `require_entity`/`require_admin`（identity）、`delete_item`（物品定义
  随玩法包注册刷新，无内核删除 API）；字段容器与 state 语义明确分离
- refactor: WebUI 精简——删除 mcpc.js 与 474 行未用样式；dist 重新构建
- test: 移除 REPO_ROOT/`v4` 文档痕迹等测试清理；`test_play_integration`
  收敛（46 行删除）
- docs: GAPS 追加 G15 观察（多世界激活未覆盖 MCP 工具与原语分派）
- ⚠️ 行为零变化（191 测试全绿）；玩法包 API 不变，单机部署无感

## v0.1.6（2026-08-27）

- refactor: 内核语义命名重构（维护性审查整改）——v4engine→engine、
  v4store→store、v3model+v4model→model（统一数据模型层）、类名
  WorldEngine/WorldStore；测试文件语义改名；代码零 v3/v4 版本痕迹
- feat: 玩法包 **SDK 稳定出口**——`from worlditor_mcp.world import ...`
  （官方 import 约定，内置包已统一，内核模块路径可自由重构）
- 删除 v3 WorldStore 死代码（~210 行）与共存测试；engine 分区导航注释；
  文档同步（DESIGN/PLAY_DEV/GAPS）
- ⚠️ 行为零变化（193 测试全绿）；玩法包 API 不变，容器部署无感

## v0.1.5（2026-08-27）

- fix: `/views` 改公共端点（登录页初始化也需视图列表，D7 前端路由共用；
  消除登录前 401 误弹"凭据已失效"）
- fix: 视图组件加载 fetch 带 Authorization 头（此前 401 导致"视图加载失败"）
- fix: 视图列表失败静默（不再弹全局错误）；管理面板各区块独立加载 +
  403 明确提示"用管理员账号登录"（不再纯白）
- fix: 内联 favicon（消除控制台 favicon.ico 404）

## v0.1.4（2026-08-27）

- fix: 管理模式误请求玩家端点 `/views` 导致 404 红色提示——onMounted 按模式
  守卫（管理模式不加载玩家视图，D16 界面分离）

## v0.1.3（2026-08-26）

- refactor: **前端按端口模式分离**（修复界面功能错乱）——新增 `/meta` 模式端点；
  AuthPage 按模式裁剪：管理端仅登录/管理员注册（无围观/agent/邀请码），玩家端
  注册补**邀请码字段**、移除管理员密钥框；管理端口登录后显示 **AdminPanel**
  （账户管理/玩法包启停/邀请码），不再复用玩家视图宿主
- feat: 管理端邀请码吊销端点（DELETE /admin/invite-codes/{code}）
- 2 个新测试（meta 端点 / 邀请码吊销）

## v0.1.2（2026-08-26）

- feat: **账户生命周期**——本人永久注销（`POST /auth/delete-account` + WebUI 🗑
  按钮，级联吊销凭据 + 删除玩家实体）、管理员删除账户（`DELETE /admin/accounts/{id}`）、
  角色变更（`PATCH /admin/accounts/{id}`，升降级即吊销旧凭据强制重登）
- fix: D14 真落地——`remove_entity` 拒绝身份化实体（文档与实现脱节），身份服务
  专用受控通道 `delete_identity_entity`
- feat: WebUI 注册页管理员注册密钥输入框（带 `admin_key` 注册即 admin 角色）
- 7 个新测试（账户生命周期 + 端点 + D14 保护）

## v0.1.1（2026-08-25）

- fix: Docker 构建失败——`.dockerignore` 排除 `*.md` 导致容器内 README.md
  缺失，hatchling 生成 wheel 元数据报 `file does not exist: README.md`
- fix: tzdata 改为无条件依赖（python:3.12-slim 无系统时区数据，容器内
  首次 `astimezone()` 会崩）
- fix: WebUI 打进 wheel（force-include `webui_dist` + 包内探测兜底），
  pip 安装场景也有界面；Dockerfile 显式 `WORLDITOR_STATIC_DIR`

## v0.1.0（2026-08-25）

独立世界服务首版（插件仓库作废后全新重开，D4）。

### 平台（内核）

- **独立服务**：`worlditor serve` 一行部署；pip 包 `worlditor-mcp`；双端口
  物理隔离（D16）——玩家 6288（MCP + 游玩 WebUI + 快照/SSE + 身份）与管理
  6289（默认 127.0.0.1，/admin/* 仍要求 tier=admin 双保险）
- **世界与组织**（D15）：worlds（玩法包激活集合）+ 多层组织树（文件夹）+ 地图
  归属；身份全局、玩家数据跟人走；play_data 按 (世界, 玩法包) 双层隔离
- **纯内核 + 玩法包**：行为全由玩法包承载；原语分派（D11）——move/move_entity/
  set_data/get_data/interact 可被玩法包 override/disable；**通用过滤器链**（G14）：
  多过滤器否决/改参/短路，链尾默认实现，与 override 互斥
- **玩法包体系**：list/enable/disable/uninstall + 依赖拓扑（requires.plays）+
  状态持久化；内置包只读可停用；跨包**服务机制**（M3：锁内 + 异常隔离 +
  生命周期清理）；MCP 动态工具（array 参数 G11，参数声明即可选）
- **编辑原语开放**（D14）：spawn/移除实体、地块/连接/地图/模板编辑；delete_map
  级联清理（G2）；身份化实体不可 remove
- **感知与隐私**：地图可见性 public/private（G1）；list_entities(viewer_id)
  隐身过滤（G12）；SSE 事件流 + world_log（上限 5000）
- **字段设施**（D9/D10）：kind 字段 schema、分类字段、物品定义字段追加
- **物品**（D8）：定义 = 内核注册表；持有（背包）全下沉玩法包，无 inventories 表
- 身份：注册/登录/agent 注册/read-token/token 三档（read/play/admin）

### 内置领域包（M3，默认启用）

- `worlditor_play_movement`：朝向移动（相对方向过滤器）+ 3×3 视野视图 +
  world_look/move/turn/who
- `worlditor_play_items`：背包（20 格/堆叠 99）+ world_bag/world_use +
  bag_add/take/count/get 跨包服务 + 苹果/面包定义
- `worlditor_play_player`：出生礼包（金币 + 物品，只发一次）+ 角色视图 +
  world_profile
- `worlditor_play_interaction`：种子实体（商贩/告示牌/木门）kind 与交互 +
  商贩交易（跨包交货）+ world_interact
- `worlditor_play_social`：地块说话（自定义事件）+ 全图广播（喇叭消耗 +
  冷却自管）+ 世界日志视图

### WebUI

- 视图宿主（D7/G3）：仅渲染玩法包视图（远程组件协议），无视图兜底提示
- 登录/注册页、token 持久化、SSE 日志

### 质量

- 185 个测试（内核/玩法包/服务/管理/端到端）；ruff 全绿；webui build 通过
- 替代玩法包验证（M4）：社区包 override move 全链路（互斥保护 → 停用接管 →
  恢复默认）；停用全部内置包后世界仍可编辑/浏览（空态）
- 文档：DESIGN.md（设计权威）、docs/PLAY_DEV.md（玩法包开发指南）、GAPS.md
