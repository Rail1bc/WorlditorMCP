# worlditor 平台缺口清单

> 来源：M2 后玩法评估（朝向移动/快捷栏/养成/空战/自有世界拜访），逐玩法验证
> 基础结构是否优雅支持。每个条目记录：触发玩法、影响、建议方案、成本、状态。
> 状态约定：**待决策**（建议在 M3 前后处理）｜**增强候选**（等真实需求再定）｜
> **文档补充**（PLAY_DEV.md 规范）｜**观察**（暂不动）｜**已解决**（✅，附版本）｜
> **暂缓**（⏸，2026-09 安全审查记录，等排期；审查报告未入库）｜**已记录**（📌）。
>
> 编号提醒：本文的 `G1–G38` 是**本仓库缺口号**；`DESIGN.md` 正文里的 `（G2）`
> `（G3）`… 是**旧插件期**的另一套编号，同号不同义（见 DESIGN §9 编号说明）。

---

## 待决策（建议做）

### G1 地图可见性（隐私）
- **触发**：自有世界与拜访玩法——每个玩家的"家"是私有地图，但 `/state` 快照
  返回**全部地图**（含内部地块/实体），任何登录玩家可见可查，"私有空间"名存实亡
- **方案**：maps 增加可见性元数据（public/private，默认 public）：
  - `/state` 只返回可见地图（private 对非 owner/非成员隐藏）
  - 玩法包 API 读自家/成员家不受限；`list_maps` 带可见性过滤参数
  - 管理端口可见全部
- **成本**：~20 行内核 + /state 过滤 + 测试（事实层轻扩展，不违背红线）
- **状态**：⚠ **部分解决**（地图 `visible` 字段 + `/state` 在场过滤，admin 全见）；
  文档方案里的"`list_maps` 带可见性过滤参数"**没做**（`engine.list_maps()` 无参数），
  `/scene`、SSE、`interact` 仍未过滤 → 真实尾巴记在 **G17**

### G2 delete_map 缺失
- **触发**：自有世界玩法——家地图生命周期需要删除，但 engine 只有
  create_map/update_map/assign_map，无 delete_map
- **方案**：补 `delete_map(map_id)`：级联删地块+实体+世界归属，身份化实体
  在场保护（同 delete_location 语义）；进玩法包 API（D14 范围"地图"本含删除）
- **成本**：~20 行 + 测试
- **状态**：✅ 已解决（engine.delete_map + play API + admin DELETE 端点）

### G11 工具参数缺少数组类型
- **触发**：多玩家互动玩法——子集选取（`targets: [eid1, eid2]`）和 AOE 类
  多目标操作需要数组参数，当前 register_tool 参数类型仅
  string/integer/number/boolean（G2 定稿）
- **方案**：`_TYPE_MAP` 加 "array" → `list[str]` 映射 + 校验放行（FastMCP
  原生生成 array schema，pydantic List[str] 支持）；玩法包侧参数为列表
- **成本**：~5 行 + 测试
- **状态**：✅ 已解决（_TYPE_MAP 加 array → list[str]，FastMCP 原生 schema）

---

## 增强候选（等真实需求再定，KISS）

### G3 tick 粒度 1s 硬编码
- **触发**：空战玩法——需要亚秒级状态推进（0.1s 帧），当前
  `TICK_GRANULARITY_SECONDS = 1.0` 硬编码，on_tick 最细 1s
- **方案**：粒度参数化（如 `WORLDITOR_TICK_GRANULARITY`，interval 语义不变，
  各 handler 各自间隔，仅调度检查更细）
- **成本**：~10 行，零语义破坏
- **状态**：等第二个需要高频的玩法出现再定（KISS：一个玩法不轻易动内核）
- **当前绕道**：玩法包自管 asyncio task 循环（见 G5）

### G4 自定义组件视图的跨包 UI 注入
- **触发**：快捷栏/手持玩法——背包按钮、快捷栏、手持使用按钮需要注入到
  movement 包的世界视图上；ui_hook 只对 UiBlock 渲染树生效，对自定义 Vue
  组件视图无效
- **方案**：视图插槽机制——`register_view_slot(view_key, slot_name, provider)`，
  视图组件声明 `<slot name="...">`，WebUI 渲染时挂载插槽组件（纯增量协议）
- **成本**：内核注册表 + WebUI 渲染器，中等
- **状态**：UiBlock 路径已闭环（**G18 已解决**：ui_hook 已接线到 interact 结果，
  服务端展开）；组件视图注入 = **挂载点 slot 设计稿**（DESIGN §4.4 视图注入表，
  表达力不足时再实现）
- **当前绕道**：世界视图用 UiBlock 构建；或各包独立视图 + goto_view 跳转

### G5 玩法包后台任务生命周期约定
- **触发**：空战等高频玩法——玩法包自管 asyncio task 无官方注册/清理约定
- **方案**：PLAY_DEV.md 规范：自管 task 必须在 teardown(api) 中取消；
  可选内核提供 `api.spawn_task(coro)` 托管（生命周期随包卸载自动取消）
- **成本**：文档 0 行；spawn_task ~15 行
- **状态**：文档已落地（DESIGN §2.4 并发模型 + PLAY_DEV §11——handler
  锁内执行、任务级重入、子任务禁止调引擎 API）；spawn_task 等真实需求

---

## 文档补充（PLAY_DEV.md 规范，M4 编写）

### G6 跨包字段/事件命名契约
- **触发**：养成玩法——exp/level/gain_exp 是玩法包间约定名，无官方规范
- **方案**：PLAY_DEV.md 列命名建议（通用字段/事件名表），D10 分类字段可
  声明字段存在性，但读写仍按约定名
- **成本**：文档
- **状态**：✅ 已落地（`PLAY_DEV.md` §11「命名契约（G6）」表：gold/energy/say/
  broadcast/starter_granted/broadcast_cd；朝向明确不入内置约定）。**注意**：
  表里的通用命名契约目前只覆盖事件名与少量字段，新增跨包约定请 PR 更新该表

### G7 跨包编辑权限约定
- **触发**：自有世界玩法——玩法包 B 的编辑调用不自动过家的 ACL
- **方案**：PLAY_DEV.md 约定"编辑任何地图前先查其 ACL"；家玩法包提供
  "地图权限查询"API（读 home 记录）
- **说明**：符合 D14"内容治理责任归玩法包"，不做内核级强制（让内核认识
  "家"概念会违背纯平台定位）
- **状态**：✅ 已落地（`PLAY_DEV.md` §11「编辑权限（G7）」：编辑前先查 ACL，
  内核不强制）

---

## 观察（暂不动）

### G8 内核持有原语与 D8 的关系
- **现状（历史）**：v4 的 inventories 表 + give/take/count 原语仍在（D8 定稿
  "无 inventories 表"，M2 未清理）
- **影响**：玩法包自管背包时不可混用内核 give/take（双轨数据）；当前
  give/take 对"简单持有"场景可用
- **状态**：✅ **已解决（M2）**——inventories 表与 give/take/count 已删，
  持有全下沉（DESIGN §8 M2 行、CHANGELOG v0.2.0；`engine.py` 明确注释
  "内核无 give/take/inventories"）。本条从"观察"归档

### G9 MCP instructions 拼装
- **触发**：MCP 呈现讨论——instructions 是 agent 的唯一世界观入口，当前
  通用；玩法包不能贡献片段
- **方案**：未来允许玩法包注册 instructions 片段（FastMCP 支持多段）
- **状态**：M3 验证玩法包工具 description 是否足够承载世界观后定

### G10 MCP resources / prompts 未启用
- **触发**：MCP 呈现讨论——resources（按 URI 主动读取）与 prompts（提示
  模板）两类协议能力未注册
- **方案**：某玩法需要"agent 主动查看世界数据"而非"调用工具"时启用
- **状态**：观察

---

## 待决策（追加）

### G12 可见性过滤（隐身）
- **触发**：动态状态玩法——隐身效果（invisible 字段）需要感知统一过滤：
  谁看不见这个实体
- **方案**：`list_entities(..., viewer_id=)` 可选参数 + 约定字段（invisible）
  过滤——所有感知工具（world_who/world_look）统一遵守；也可纯约定层
  （感知工具各自过滤，依赖工具作者遵守）
- **成本**：内核 ~10 行（推荐）或 0 行（约定层）
- **状态**：✅ 已解决（`list_entities(viewer_id)` 过滤 invisible/see_invisible，
  `/scene` 与玩法包感知工具同步）
- **尾巴（2026-09 复核）**：`/state` 全量快照**没走**隐身过滤（`http.py` 的
  `_state` 调 `engine.list_entities()` 不传 `viewer_id`）——`可见性`（public/private）
  与`隐身`（invisible）是两件事，前者做了、后者只做了一半。修法：`_state` 传
  `viewer_id=info.entity_id`（一行），归入"安全/可见性"批次一起做

### G13 效果协调模式（移动类效果）
- **触发**：动态状态玩法——束缚/移动限制/方向障碍多个效果都要拦 move，
  但 A3 每原语至多一个 override，多个效果包会争抢名额
- **方案**：已被 **G14（通用原语过滤器链）取代**——过滤器链是通用机制，
  不再需要"效果集中在单包"的协调约定
- **状态**：已解决（G14 落地后关闭）

### G14 通用原语过滤器链（已采纳）
- **触发**：移动/效果/状态类玩法——多个玩法包需要拦/改**同一原语**
  （move 方向转换+束缚；set_data 锁血+只读；get_data 遮蔽；interact
  沉默/改写），A3 单一 override 名额冲突；move 特化不成立（通用问题）
- **方案**：全部 5 个可覆盖原语支持过滤器链（注册序）：
  - 否决：raise WorldError → 本次调用失败
  - 参数改写：返回参数字典 → 继续链
  - 短路：返回 ShortCircuit(value) → 直接作为结果，跳过后续与默认实现
  - 链尾 = 内核默认实现；过滤器约定纯函数（世界变更只发生在默认实现）
  - 与 override/disable 互斥（保留原语义）；同一包可注册多个过滤器（各带
    label）；生命周期随包卸载清理；管理页可见（谁、顺序）
- **成本**：~60 行内核 + 测试；DESIGN.md §2.4 修订
- **状态**：✅ 已采纳（用户拍板），M3 前落地

---

## 待决策（安全审查记录，2026-09——已记录，暂缓）

### G16 认证端点零防护
- **触发**：全面审查——`/auth/login` / `register` / `agent-register` / `read-token`
  全公开（http.py 公共路径白名单）且无失败计数/退避/锁定；register 报
  「用户名已存在」+ login 对不存在账户跳过 PBKDF2（计时侧信道）→ 用户名
  可枚举；open 模式 `read-token` 无限签发且 token 无 TTL（只查 revoked）
- **影响**：6288 公网端口可无限制爆破/枚举/膨胀 tokens 表；单次 login 为
  200k 次 PBKDF2（身份/identity.py:31），并发请求即 CPU 放大 DoS
- **方案**：按用户名+IP 失败计数指数退避（内存级即可，默认单 worker）；
  统一 401/403 文案 + 不存在账户跑假 PBKDF2；read-token 配额或 TTL；
  启动防呆 WARNING（open + 0.0.0.0 + 空 ADMIN_KEY 三连）
- **状态**：⏸ 暂缓（记录于 2026-09 安全审查——**报告未入库**，本条即 P0-2 正文；
  2026-09-24 复核：无失败计数/退避/锁定、`identity.py` 里 login 对不存在账户
  短路跳过 PBKDF2、read-token 无 TTL/配额——**全部仍成立**）

### G17 G1 可见性只实现了一端（/scene + SSE + 交互缺口）
- **触发**：全面审查——`/state` 按 `map_visible_to` 过滤（G1 部分解决，见 G1 尾巴），
  但 `/scene`（http.py:210-245）不检查——read 档持任意 entity_id 可读 private
  地图场景与动作菜单；SSE `_event_payload`（engine.py:1760-1798）对
  private 地图事件全量下发实体位置（play 档订阅可跟踪）；`interact` /
  `list_actions` 亦不做地图可见性检查
- **方案**：`/scene` 补 `map_visible_to` 过滤（~5 行）；SSE 订阅对象带
  订阅者身份按可见性过滤（~30 行接口变更，admin 全见）；interact 前置
  检查；各补 HTTP 级测试
- **状态**：⏸ 暂缓（记录于 2026-09 安全审查——**报告未入库**，本条即 P0-3 正文；
  2026-09-24 复核：`map_visible_to` 全仓唯一调用点仍是 `http.py` 的 `_state`，
  `/scene`／SSE／interact／`list_actions` 四处缺口**全部仍成立**）

### G18 ui_hook 未接线（已解决）
- **触发**：P0-1 修复期间核查——`apply_ui_hooks` 在生产路径无调用者
  （仅 tests/test_engine.py 直调）；`register_ui_hook` 注册表完整，
  但交互结果渲染未应用钩子，ui_hook 实际不生效
- **影响**：G4「UiBlock 路径先行（视图 = UiBlock + ui_hook 注入）」的
  注入环节空转；玩法包注册 ui_hook 静默无效
- **方案**：interact 结果返回前应用 `apply_ui_hooks`（服务端展开、WebUI
  零改动；注入块随 on_interact 事件同步进 SSE）
- **状态**：✅ 已解决（阶段 3：engine._interact_default 接线 + 端到端测试
  test_interact_result_applies_ui_hooks；注：SceneView 为纯数据无 UiBlock，
  ui_hook 适用面 = 交互弹窗等 UiBlock 渲染树）

### G19 包裹覆（play_id 覆盖）机制未背书（观察）
- **触发**：阶段 1 拆分核查——`discover()` 先扫内置再扫社区目录，
  `load_all` 以 play_id 为键（play/__init__.py:74-85, 112）：社区包同
  play_id 会**静默覆盖**内置包（如世界 http 自定义 `worlditor_play_items`）
- **影响**：这是「替换内置包」的唯一正式路径（M4 验证的是 override 机制，
  非包裹覆），但无告警、管理页无提示、无测试——意外覆盖时难以察觉
- **方案**：正式化——加载时若社区覆盖内置：管理页 list 标注（builtin 标志
  改为来源+被覆盖提示）；`_load_errors`/日志告警；补覆盖场景测试
- **状态**：观察（等真实"替换背包/礼包"需求；阶段 1 的 starter 可替换性
  已实际依赖此机制）

### G20 内置包视图组件内联浅色样式（观察）
- **触发**：背包追加玩家视图时核查——`builtin_plays/*/web/*.js` 自定义视图
  组件内联浅色（bag.js #fff/#f7f7f7/#bbb、view.js/log.js 同类）与全局暗色
  主题不一致（v0.1.8 管理端修复的同族问题，玩家端视图组件未涉及）
- **影响**：独立视图 tab（世界/背包/日志）在暗色主题下颜色突兀、对比度差
- **方案**：视图组件内联样式改用 CSS 变量（var(--text)/var(--bg-3)…）或
  全局类；profile.js 已随重写修复（var(--text-dim)）
- **状态**：✅ **已解决**（2026-09-24 复核：`bag.js`/`view.js`/`log.js`/`profile.js`
  已改用 `wt-*` 类与 CSS 变量，全文无颜色字面量；仅 `admin-items.js:160` 的
  `color:"#fff"` 是强调色底上的按钮文字，属正常）。守卫：
  `tests/test_web_view_styles.py`（**注意**：该守卫只扫 `webui/src` 且显式排除
  `admin-*.js`，玩法包管理页组件不在防线内——见新条目 G27）

---

## 观察（追加）

### G15 多世界激活未覆盖 MCP 工具与原语分派
- **触发**：多世界玩法评估（D15）——世界激活集合按实体所在世界过滤，
  但只落地于事件分发与交互通道；MCP 工具（register_tool）与原语
  override/过滤器（move 等）为全局生效：未激活包的工具在"其他世界"仍可调用
- **现状**：~~`engine._world_play_active` 仅被 `_emit`（事件）与
  `_interact_default`（交互）使用；`build_dynamic_tool` 与
  `_dispatch_primitive` 不做世界检查~~
- **状态**：✅ 已解决（v0.3.0）——全路径按世界过滤：
  - MCP 工具：`build_dynamic_tool` 在 handler 前按**调用者**世界检查，
    未激活 → 明确文案拒绝（含世界名与包 id）
  - 原语 override/过滤器：`_dispatch_locked` 按**行为主体**世界过滤，
    未激活者视为不存在 → **回落内核默认实现**（定了语义：不是"拒绝调用"，
    而是"这个世界的规则里没有它"）；disable 登记同理会"复活"为默认实现
  - kind：`block_move` 与 `available_actions`（动作菜单）按实体世界过滤
  - 玩家视图：`GET /views` 按调用者世界过滤（未激活包的 tab 不出现）
  - 部件 UI：`apply_ui_hooks` 按查看者世界过滤（注入方不在该世界 → 不注入）
  - **未归属世界的地图**改按**默认世界**的激活集合算（原先 = 全部激活，
    等于逃逸世界过滤）；管理端建图即归属当前世界 + 孤儿地图一键归属
  - 测试：`tests/test_world_activation.py`（工具/视图端到端 + 原语/kind/ui_hook）
- **仍留**（新的观察项，非本缺口）：
  - `world_list` / `world_travel` 跨世界传送未实现（设计见 DESIGN §3.0）
  - 出生点不区分世界（`_spawn_pos` 取首张地图；等于"新玩家总进第一个世界"）
  - 世界间的**数据可见性**：`/state` 仍返回全部可见地图（可见性 G1 过滤），
    未按世界做数据边界
  - 跨包服务仍全局（服务是包与包之间的约定，不是世界内能力面）

---

## 待决策（v0.5 方向，已评估未定稿）

### G21 实体声明体系：类型 / 模板 / 标签（能力由标签承载）

- **触发**：地图编辑要"不依赖任何玩法包、又能自然容纳所有玩法包的内容"——
  刷怪笼这类**内核原生不存在**的东西（内核没有"能生成实体的实体"），
  在地图编辑里应该只是"一个叫刷怪笼的实体 + 一份数据"，数据规范由刷怪笼包规定。
  用户设想：玩法包声明 a/b/c 标签，再声明类型 A = {a,c}、B = {b,c}，
  **类型退化为"预设的标志位"，核心是标签**；内核自带的 player 类型也增设玩家标签。
- **现状差距**（已核对）：
  - `entities.kind` 是单值 `TEXT`，同时承担 ①身份（`IDENTITY_KINDS`）②行为声明
    （block_move/interactions/tick）③字段 schema 归属——**组合在库层面存不下**
  - 内核已有 D9/D10 的"类型 + 分类标签 + 字段 schema"设施，但 `categories` 挂在
    **kind 上**（类型级），不是实例级；且**完全没接到管理端**（无 `/admin/kinds`，
    编辑器里 kind 是自由文本框，attrs/state 是整块 JSON）
  - `templates` 表已被**地块模板**占用，实体模板要另起名字
- **评估结论**（方向赞同，两颗钉子必须先钉）：
  - 收益：拆掉 `add_kind_fields` 那种"B 包改 A 包命名空间"的补丁（消化 G6 一大半）；
    能力集 = 标签并集，语义统一（不再有"kind 挡路但标签不挡路"的二分）；kind 变干净
    （= 不含数据的预设，模板 = 含默认数据的预设）；玩家标签化后 NPC 可"升格为角色"、
    玩家标签可被摘掉（石化/附身/夺舍有数据底座）
  - 钉子①：**`player` 必须是内核保留标签**，只有身份服务能加/减——否则任何能改标签的
    通道都能摘掉 D14 的身份保护（删 label → remove_entity 就能删玩家）
  - 钉子②：`register_entity_kind(...)` 保留为**语法糖：自动生成隐式同名标签**——
    旧包零改动、旧数据零迁移，新代码才用真标签组合
  - 还需裁定：多标签能力冲突规则（并集 + 后注册者覆盖 + 管理端可见？）、
    实例标签能否**移除**基底标签（否则要引入 `-spawner` 负标签语法）、
    能力集缓存与失效（每 tick 遍历全实体的场景）、`entities.tags_json` 加列
- **状态**：✅ **已实现**（v0.5.0；结论 = DESIGN **D18/D19/D20/D21/D25**）
  - 实体 `tags[]` + `entities.tags_json`（旧库自动补列）
  - `register_entity_kind` 退化为**隐式同名标签**（旧包/旧测试零改动，全套既有测试未改一行）
  - 新增 `register_entity_tag` / `register_entity_type(kind, tags=)`；`add_tag_fields` 语义扩张
  - 能力并集（block_move 任一为真 / interactions 并集 / fields 顺序固定）+ 逐标签世界过滤 + 规格级缓存
  - 身份判定仍只看基底 kind；`EntityKindSpec.tick` 死字段已删（改名 `TagSpec`，保留旧别名）

### G22 地图编辑器增强（v0.5 候选）

- **触发**：v0.4.0 地图治理做完后，编辑器本身仍是"网格 + 侧栏 + 整块 JSON"
- **候选**：地块多选/框选复制粘贴、出口连线可视化、撤销重做；
  以及把 `engine.move_location`（原子移动地块 + 重写全图引用，**内核已有但没接 UI**）
  接到编辑器上
- **状态**：✅ **已实现**（v0.5.0；DESIGN **D24**）：地块多选/框选复制粘贴、出口方向箭头、
  `move_location` 接入、保存前 diff 预览都做了；**撤销/重做确认不做**（成本≈其余三项之和）

### G23 地图治理残留项（v0.4.0 发布后自查）

- **地块模板是"半成品死重"**：~~`templates` 表 + 管理端只能建/删，**没有任何"套用模板"的入口**~~
  → ✅ **已解决**（v0.5.0，D22）：`templates` 加 `scope` 统一地块/实体模板，
  地块模板补上"套用"（同图目标按相对偏移平移、跨图目标原样），编辑器有"存为模板"。
- **实体数据在管理端完全改不了**：~~只能改名字与删除~~ → ✅ **已解决**（v0.5.0，D23）：
  按声明字段渲染控件 + 未声明字段原始 JSON 兜底，attrs/state/tags/类型都可改
  （身份化实体的类型由身份服务锁定，D20）。
- **编辑器实体面板形态落后**：~~全图平铺一张表、无 kind 过滤、位置列冗余~~ →
  ✅ **已解决**（v0.5.0 精简列 + 显示合并能力；**v0.5.1 实体视图补齐类型筛选/标签筛选/
  排序/分页与地块锁定**，`EntityManager.vue`）。
- **跨世界总览的批量搬家不报进度**：→ ✅ **已解决**（X1：逐张报"已完成 k/N" + 失败清单）。
- **总览页不能新建地图**：→ ✅ **已解决**（X2）。
- **组织树只有拖拽排序**：→ ✅ **已解决**（X3：行内 ▲▼ + 聚焦行 Alt+↑/↓；多选/复制文件夹仍未做）。
- **`GET /admin/lint` 每次全量算所有地图**：→ ✅ **已解决**（X4：支持 `?world_id=`，未归属地图算在默认世界）。
- **升级后既有世界的"文件夹内地图顺序"会变成按名称**：一次性观感变化，保留说明。
- **状态**：📌 已记录（v0.5.0/v0.5.1 已做掉绝大部分；**仍留**：文件夹多选/复制、
  撤销重做（D24 明确不做，由 diff 预览兜底））

### G24 管理端连接编辑器会**静默损坏**地图数据（必修）

- **触发**：v0.4.0 发布后审查编辑器读写往返时发现（**非 v0.4.0 引入**，v0.1 起就存在）
- **现象**（`.uitools/probe_conn_roundtrip.py` 实测，逐字复现前端两段逻辑）：
  一条出口 = 分时段文案 + 主目标跨图（权重 3）+ 意外目标同图（权重 0.5），
  在编辑器里**只是打开并保存**（哪怕只动了另一个方向），结果：
  | 数据 | 原值 | 保存后 |
  |---|---|---|
  | 主目标 `map_id` | `"B"`（跨图出口） | **消失** → 变成本图 (0,0)，出口变原地打转 |
  | 目标 `weight` | 3.0 / 0.5 | **全变 1.0**（加权随机退化成等概率） |
  | 路径 `label` | `"往东走"` | **`"[object Object]"`**（TextSchedule dict 被绑进 `<input>`） |
- **根因**（`webui/src/pages/admin/MapEditorPage.vue`）：
  - `select()`：`targetsText = targets.map(t => `${t.row},${t.col}`)` —— **丢掉 map_id 与 weight**
  - `select()`：`label: p.label || ""` —— 服务端返回的 `label` 是 `TextSchedule.to_dict()`
    的**对象**，绑进 `<input v-model>` 被 `String()` 成 `"[object Object]"`
  - `saveConnections()`：payload 只发 `{row, col}`；**且循环 4 个方向全量重写**
    （`update_connection` 是整槽替换）→ 只改一个方向也会毁掉其余三个方向的数据
  - 分时段文案在 UI 里**完全没有表达方式**（无时段/权重编辑）
- **为什么危险**：静默、无提示、**lint 抓不到**（损坏后的目标地块存在，不算死引用）、
  且不可逆（除非用户自己备份过 world.db）
- **方案**：v0.5 编辑器重写时一并做——结构化出口表单（目标 = 地图 + 坐标 + 权重，
  文案 = 分时段条目），并给"保存前 diff 预览"（旧值→新值）作为兜底
- **状态**：🔴 必修 → ✅ **已修复**（v0.5.0，DESIGN D23）：出口改为结构化表单
  （目标 = 地图 + 坐标 + 权重，文案 = 结构化 JSON——当时还允许纯文本，见 G28
  已统一为唯一格式），**保存前弹差异预览**
  （旧值→新值，取消即不落盘）；E2E `verify_editor_v05.mjs` 专门守这条回归
  （跨图 map_id / 权重 / 文案在保存后逐一核对）
- **尾巴（v0.5.1 发布后自查发现，2026-09-24）**：同一族还剩两处静默丢数据——
  ①**单时段带时间窗的文案被"扁化"**（v0.5.2 已按"统一格式"修复，见 G28）：
  `periods` 只有一段且只有一条时前端按纯文本
  处理（不看 `start`/`end`/`weight`），存回去被服务端解析成 `00:00–24:00`，
  `08:00–18:00` 窗口消失；且 **diff 预览用同一套扁化规则 → 弹窗显示"无变化"**；
  ②`FieldForm` 的 `attrs`/`state` 原始 JSON 非法时 `|| {}` 把整袋数据清空。
  → 见 **G28 / G29**（v0.5.2 一并修）

---

## 待决策（CORE_AUDIT §4 收编，2026-09-24——原先"无主"）

### G25 世界包的内容更新语义

- **触发**：`docs/CORE_AUDIT.md` §4 记录但**只有该文档记着**（GAPS/DESIGN 无条目）
- **现状**：`worlditor_play_demo_world` 的 `setup()` 是"地图已存在则整体跳过"
  （`main.py:40-41`，不覆盖用户改动）；包升级新增了地块/实体也**不会**补进已有世界
- **方案**：世界包版本化 + 差异合并（新增子图 / 按 id 补地块 / 只补不改）；
  或显式"重新导入（覆盖）"高级操作 + 备份提示
- **成本**：中等（要定义合并规则与冲突策略）
- **状态**：待决策（等第一个"世界包要迭代内容"的真实需求）

### G26 管理端健壮性收尾项（CORE_AUDIT §4 未处置）

- **触发**：CORE_AUDIT §4 末尾"审查中发现但未处置的次要点"散落无人跟进
- **条目**：
  - 管理端多处裸 `int()` → 传非数字直接 **500**（不是 400）。点：
    `admin.py` 的 `page`/`page_size`/`row`/`col`/`to_row`/`to_col`/`spawn_row`/
    `spawn_col`/`count`（`_accounts`、`_location_upsert`、`_location_move`、
    `_connection_update`、`_map_create`、`_map_update`、`_entity_create`、
    `_template_apply`）。修法：统一 `_int_arg()` 助手 → `WorldError("行号必须是整数")`
  - `PUBLIC_PATHS` 用 `startswith` 前缀匹配（`http.py:95-97`）——将来新增
    `/auth/read-token-xxx` 之类路径会**误免认证**；应改为精确匹配 + 显式前缀白名单
  - `/plays/{play_id}/web` 前缀校验用字符串 `startswith`（`http.py:402`），
    建议 `Path.is_relative_to`
  - `?token=` 会进访问日志（SSE 的硬需求，不能删）——至少文档化 + 建议反代过滤
  - 停用玩法包不清理 `sys.modules` 残留（同名包换目录重载时可能拿到旧模块）
  - **局部更新语义不完整**（v0.5.2 审计补充）：
    - `PATCH /admin/maps/{id}` 只给 `spawn_row` 会把 `spawn_col` 重置为 0
      （与 docstring"未提供的字段不变"矛盾；前端总发两个值，直连 API 必踩）
    - `POST /admin/connections` 的 `enabled`/`paths` 实际都是必填（`admin.py` 恒传
      `data.get(...)`，缺省 None 被当"显式给值"）→ 只改一个方向不可行
    - `POST /admin/locations`（upsert）不带 `description` 会**清空**整段分时段描述
- **状态**：待决策（低危但成串，适合一次"收尾清理"批次；v0.5.2 未做）

### G27 玩法包管理页组件逃过前端守卫（原生 confirm + 样式守卫盲区）

- **触发**：v0.5.1 前端审计——`worlditor_play_items/web/admin-items.js:118` 用了
  **原生 `confirm()`**，违反 D17"管理端禁用原生 confirm/prompt/alert"（iframe/
  沙箱下被浏览器屏蔽 → 删除操作**静默失效**）
- **根因**：守卫 `tests/test_web_view_styles.py` 只扫 `webui/src`（`:166`），且
  `_view_component_files()` 显式排除 `admin-*.js`（`:67`）——管理页组件不在防线内
- **方案**：① 组件协议扩展——加载器把内核的 `askConfirm` 作为第三个注入参数
  （`new Function("Vue","UiBlock","askConfirm", code)`，DESIGN §4.6 修订）；
  ② 守卫扩到 `builtin_plays/*/web/*.js`（含 admin-*），样式类契约另行放宽；
  ③ 短期可让管理页组件自带行内确认（状态 + 两个按钮）
- **状态**：待决策（等下一次管理页组件改动一并做；当前只有一个删除入口）

---

## 已解决（v0.5.2 全仓库自查修复）

> 来源：v0.5.1 发布后的"项目 + 文档"全面审查（三路：后端 / 前端 / 文档）。
> 下面六条都是**静默**类缺陷（要么丢数据、要么功能空转），本轮全部修复并补了
> 能反向复现的回归测试（改回旧行为测试就红）。

### G28 文案格式双轨 → 时间窗静默丢失（G24 同族）

- **现象**：`periods` 只有一段且只有一条时，前端不看 `start`/`end`/`weight` 就当
  纯文本处理；存回去服务端解析成 `00:00–24:00` → `08:00–18:00` 的时间窗、
  权重 ≠ 1 的多条文案全部丢失。**差异预览用同一套扁化规则**，弹窗还显示"无变化"。
  根子在**同一份数据有两种写法**（纯字符串 = 全天单条 ‖ 结构化对象）。
- **修复（v0.5.2，用户裁定：不留冗余逻辑、不允许纯文本、格式强制统一）**：
  - **内核**：`parse_text_schedule` 只接受 `None` 与结构化对象；**纯字符串与非结构
    一律 `WorldError`**（消息带格式示例）；**非法条目不再静默丢弃**而是整段报错
    （静默丢字段正是 D23/G24 要根除的东西）。`WorldError` 抽到 `world/errors.py`
    供 model/engine 共用（仍然可以从 `world.engine` 导入）。
  - **前端**：`webui/src/textSchedule.js` 只剩两个函数——`scheduleToJson`（服务端值
    → 编辑框文本，历史纯文本只在**显示**时归一成标准结构）与 `parseScheduleText`
    （编辑框文本 → 提交值；空 = 清除；不是 JSON 对象就报错且**不提交**）。
    `ConnectionPanel` / `TilePanel` / `MapEditorPage` 全部改用它，**没有纯文本模式**。
  - **数据/文档**：内置世界包 `world.json`、测试夹具、PLAY_DEV / HTTP_API / DESIGN
    全部改成唯一格式（`tests/test_text_schedule.py` 里有一条守卫扫描 world.json）。
- **回归**：`tests/test_text_schedule.py`（18 条：字符串与非结构全被拒、坏时段/坏条目
  报错而非丢弃、`to_dict` 往返无损、引擎与管理端 400 不落盘）+ `tests/test_editor_integrity.py`
  （源码守卫：结构只在 textSchedule.js 里、组件不得自己解析、没有纯文本模式）+
  `tests/test_map_governance.py::test_admin_round_trip_keeps_windowed_text_schedule`
  + E2E「文案只有一个结构化编辑框 / 时间窗保存后仍在」。

### G29 实体数据 JSON 写坏 → 整袋 attrs/state 被清空

- **现象**：`FieldForm` 的 `attrs`/`state` 原始 JSON 非法时 `parseJson(...) || {}`
  把整个容器换成 `{}` 再提交；错误文案又渲染在默认折叠的 `<details>` 里，用户
  既看不到报错也看不到数据没了。
- **修复**：解析失败**不落盘**（`push()`/`pushRaw()` 提前返回，保留另一容器的
  旧值）；错误提示移出折叠区，并让折叠区在有错时自动展开。
- **回归**：`tests/test_editor_integrity.py::test_field_form_fails_closed_on_bad_json`
  + E2E「JSON 写坏时给出可见错误 / 非法 JSON 不清空 state、attrs」。

### G30 复制地图（带实体）静默丢 `tags`

- **现象**：`engine.copy_map(with_entities=True)` 构造副本实体时没传 `tags=`
  → 带 `spawner` 标签的实体复制后变裸实体（旧测试没设 tags，漏网）。
- **修复**：副本带上 `tags=list(e.tags)`。
- **回归**：`tests/test_map_governance.py::test_copy_map_preserves_entity_tags`。

### G31 停用/卸载 items 包 → 管理页建的物品定义被永久删除

- **现象**：`PlayLoader._teardown_one` 按 `item_defs_of_play` 无差别删库 + 删内存，
  而管理页创建走的也是 `register_item_def`（归属同一 play_id）→ 管理员手工维护的
  物品定义在"停一下包"之后消失，与 DESIGN §4.3"disable 保留数据"直接矛盾。
- **修复**：物品定义分两种生命周期——**代码声明**（`api.register_item_def`）
  随包停用清理、**用户数据**（新增 `api.save_item_def`，管理页走它）停用/整体
  卸载时保留，只有真卸载（删包目录，`purge=True`）才一起删。同时补上
  `delete_item_def` 的归属记账清理、管理页 update 的"先校验后改"。
- **回归**：`tests/test_admin_pages.py::test_disable_keeps_admin_item_defs`（内存 +
  直连 SQLite 查库双确认）。

### G32 `async def teardown(api)` 从不被 await

- **现象**：`_teardown_one` 直接 `teardown(info.api)`，不检查返回值是否 awaitable
  （`setup` 是支持的）→ G5 约定里"在 teardown 取消自管后台任务"**静默不生效**，
  卸载后任务还在跑。
- **修复**：`inspect.isawaitable(result)` 时 `await`。
- **回归**：由 G31 的生命周期测试覆盖（同一段代码路径）；日志不再出现
  `coroutine 'teardown' was never awaited`。

### G33 `/views` 的世界过滤对已登录玩家恒失效

- **现象**：`/views` 在免认证公共路径里，中间件遇到公共路径**直接放行且不解析
  token** → `_identity_of()` 恒为 None → 视图过滤退化成"匿名/默认世界"。
  默认世界通常"全部启用"，所以老测试（只在默认世界验）永远看不出问题。
- **修复**：公共路径 = **不要求**凭据，不等于"忽略凭据"——带了 token 照样解析
  身份（不存在/过期才按匿名处理）。`/views` 因此真正按调用者所在世界过滤。
- **回归**：`tests/test_world_activation.py::test_views_filter_uses_caller_world_not_default`
  （玩家站在**非默认世界**里验；另验匿名仍按默认世界算）。

### G34 编辑器删格/空图后"在此新建地块"抛异常

- **现象**：`primary` 为 null 时侧栏仍按 `primary || {row:0,col:0}` 渲染，但保存
  逻辑读 `primary.value.row` → 空图首次打开、或删掉选中地块后点该按钮，Vue 把
  异步异常吞进 console，界面毫无反馈（坐标还显示成 (0,0)）。
- **修复**：`primary` 在 `loadDetail` 后必有具体坐标（初次打开落出生点）；删格后
  **保留该格坐标**（面板原地变"在此新建地块"，可直接重建）；保存前再做一次
  空值兜底并给出可见错误。
- **回归**：`tests/test_editor_integrity.py::test_editor_keeps_a_concrete_coordinate`
  + E2E「删格后保留坐标 / 在原地重建」。

---

## 观察（v0.5.2 审查发现，本轮**未修**——已登记，按需排期）

### G35 内核 / 内置包的小口子（静默或低危）

- **交互动作注册静默覆盖**：`engine.py` 的 `self._interactions[action] = …` 无冲突
  检查（工具/视图/服务/管理页/原语都有 D2 式报错）→ 两个包注册同名 action 时
  后者**静默顶掉**前者（G19 同族）。
- **`demo_world` 的"续跑"分支不可达**：`main.py:40-41` 地图存在即 return，
  `62-66` 那段"已存在地块只更新名称/描述"永远不执行——"导入中断可续跑"是
  文档承诺但不成立；导入也没带 `tags=`（当前 `world.json` 无标签，属契约漏洞）。
- **商贩购买非原子**：`interaction/main.py` 先扣金再 `bag_add`，背包满时钱花了货
  没到（错误还被吞成"交互执行出错"）。修法：先 `bag_add` 成功再扣金，或失败回滚。
- **`_bag_take` 只从第一格扣**：同一物品跨多格（30+30）取 50 会误报"数量不足"。
- **`_ui_components` 是只写不读的死注册表**：`register_ui_component` 零调用者，
  但 DESIGN §4.1 / PLAY_DEV §4 仍列为 API（能力已被 `register_view` provider 取代）。
- **引擎命名/注释漂移**：`available_actions` 注释仍写"kind 声明 ∪ 全局注册表"、
  `model.py` 注释仍写"优先于 kind spec 的 block_move"（D18 后应说"标签"）。

### G36 编辑器 / 前端可用性清单（审计逐条给了 file:line）

- **网格按包围盒稠密渲染、无上限**（`MapGrid.vue` 双层循环）：坐标框允许输入任意
  值，建完 (0,0) 再输 (5000,5000) ⇒ 2500 万按钮，浏览器冻死。修法：加渲染上限
  （超出提示"缩放/平移查看"）或虚拟滚动。
- **玩法包管理页切换不重载组件**（`PlayPageHost.vue:87-91`）：标题换成新包、
  内容仍是上一个包的组件（`hashchange` 只同步 ref，不重新加载 `comp`）。
- **`addEventListener` 不清理**：`MapEditorPage.vue`、`PlayPageHost.vue`、
  `AdminPanel.vue` 在 `onMounted` 注册 `hashchange` 却无 `onUnmounted`
  （`MapGrid.vue` 是正确写法）→ 组件卸载后旧闭包常驻、重复注册。
- **`localStorage` 无兜底**（`api.js`、`AdminPanel.vue`、各视图 js）：隐私模式下
  `getItem` 直接抛 → 启动全白。
- **玩法包视图硬编码 `/world/mcp`**（`view.js`/`bag.js`/`log.js`/`profile.js`）与
  `VITE_WORLD_API` 独立域部署矛盾；`_sessionId` 只初始化一次，会话失效后只能整页刷新。
- **失败伪装成"正常"**：`AllMapsPage`/`WorldMapsPage` 的 lint 拉取失败
  `.catch(() => ({maps: []}))` → 统计条显示"0 处错误"；`WorldPlaysPage` 的
  `allSettled` 吞掉 4 个请求失败 → 详情页显示"该包没有注册工具/服务/视图"。
- **其余小项**：吊销凭据后详情面板请求 `/admin/accounts/undefined/tokens`；
  空白处平移后下次点击被吞（`suppressClick` 未复位）；模板坐标清空 →
  `Number("")===0` 静默套用到 (0,0)；`WorldEditModal` 空 id 可提交、无 Esc、
  点遮罩丢输入；`EntityManager` 行点击无键盘可达、`ConfirmHost`/`DiffModal`
  无 `role="dialog"`；`admin-items.js` 的 attrs 只校验"是合法 JSON"（放行数组/标量）。
- **零玩法包场景的界面审计已过期**：`.uitools/audit_no_plays_ui.mjs` 停在 v0.2.0，
  v0.5.x 编辑器重写后没在"停用全部玩法包"下再验过（后端有 `test_empty_state_*`，
  界面只有旧的本地脚本）。

### G37 工程/流程

- **CI 不校验已提交的 `webui/dist`**：`pytest.yml` 的 `webui-build` 只
  `npm run build`，不比对产物；而 `Dockerfile` 与 wheel 都吃**已提交的 dist**
  → 改了 `src` 忘了 build 就会发出旧界面。建议加 `git diff --exit-code webui/dist`。
- **浏览器 E2E 只存在本机**：`.uitools/*.mjs` 被 gitignore、CI 不跑——
  换机/换人就断了（本轮新增的 G28/G29/G34 回归线也在那里）。
- **解释器口径**：本机 `.venv` = Python 3.14，CI = 3.12，而 `requires-python >=3.10`
  / ruff `target-version = py310` —— 3.10/3.11 从未被跑过。
- **本地 `origin/main` 追踪引用陈旧**（显示 ahead 22）：远端其实已是最新，
  `git fetch origin` 即可；`push` 需 SSH（HTTPS 凭据失效）。

---

## 已落地（v0.6.0，D26–D30）

### G38 实体查询与调度（原"缺口"，已按 ECS 对照清单补齐 A–D）

- **背景**：一次架构自查（"我们算 ECS 吗"）列出五项差距，裁定**除 E 外全补**
  （A 查询 / B 调度 / C 删字段 / D 变更检测），E（组件独立存储、archetype、SoA、
  并行系统）明确不采纳——理由见 DESIGN §11（D30）。
- **已落地**：
  - **A 查询原语**（D26）：`engine.query_entities` / `api.query_entities`——
    标签 AND、排除、地图/世界/坐标、`viewer_id` 感知、变更游标、`where`、`limit`，
    稳定排序；标签匹配按 D21 激活语义（声明包未加载或世界未启用 → 不匹配），
    包含与排除共用同一份"活标签集"。老接口 `list_entities` 行为不变（宽松位置筛选），
    两者共用 G12 感知判定（**单一判定点**）。
  - **B 调度**（D27）：事件 `phase`（input/simulate/present）/ `order` / 注册序兜底，
    覆盖全部事件含 `on_tick`；未知名报错。
  - **C 删字段**（D29）：`remove_data`（进分派表）/ `remove_state`；幂等 + 事件
    `attrs_removed`/`state_removed`。
  - **D 变更检测**（D28）：实体 `revision`/`changed_tick`（`save_entities` 唯一盖章点）、
    全局号与业务写同事务落 `world_meta`、启动在任何写之前续号；`/state` + 实体 +
    SSE payload 都带上；`changed_since_revision`（精确）/`changed_since_tick`（窗口，
    宁可多报）。
- **残留（本轮未做，按需再排）**：
  1. **查询是内存线性扫描**：几千实体微秒级够用；上万实体要加 `标签 → 实体 id`
     倒排索引（挂在 store，接口不变）。索引一旦引入，就得覆盖
     `place/remove/update_entity(tags=)/copy_map/delete_map/模板套用` 全部变更点
     ——这正是目前**故意不做**的原因（漏一处就是静默错误）。
  2. **变更检测只到实体级**：字段级脏标记 / 事件溯源未做（与"实例可写任意未声明
     字段"的开放模型冲突，需要时按包约定加）。
  3. **`where` 是进程内逃生口**：不能用于 MCP 工具参数（不可序列化），
     工具场景只能用声明式筛选（tags/世界/坐标/游标）。
  4. **地图级可见性不进查询**：`query_entities` 只做实体级隐身过滤（G12）；
     `map_visible_to` 仍是表现层（`/state`）的地图闸门——G17 的其余出口
     （`/scene`、SSE、`interact`、`list_actions`）仍未接，属 G17 未闭合部分。
  5. **事件顺序无管理端可见性**：覆盖/过滤器状态管理页可见，但"谁挂在哪个阶段/
     序号"目前只能在代码里看（`list_*` 未暴露 event bindings）。


