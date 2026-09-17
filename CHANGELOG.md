# Changelog

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
