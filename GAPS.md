# worlditor 平台缺口清单

> 来源：M2 后玩法评估（朝向移动/快捷栏/养成/空战/自有世界拜访），逐玩法验证
> 基础结构是否优雅支持。每个条目记录：触发玩法、影响、建议方案、成本、状态。
> 状态约定：**待决策**（建议在 M3 前后处理）｜**增强候选**（等真实需求再定）｜
> **文档补充**（PLAY_DEV.md 规范）｜**观察**（暂不动）｜**已解决**（✅，附版本）｜
> **暂缓**（⏸，2026-09 安全审查记录，等排期；审查报告未入库）｜**已记录**（📌）。
>
> 编号提醒：本文的 `G1–G39` 是**本仓库缺口号**；`DESIGN.md` 正文里的 `（G2）`
> `（G3）`… 是**旧插件期**的另一套编号，同号不同义（见 DESIGN §9 编号说明）。

---

## 已解决（本轮核心审查修复）

- 复合地图移动、复制、删除及创建时归属已收束到单事务提交，避免失败留下半成品；
  实体 revision/changed_tick 只在事务成功后写回内存。
- 复制事务失败回滚已有回归测试；私有场景授权、玩法查询快照与邀请码原子消费已落地。
- 人类与 agent 注册的实体、账户、token、邀请码消费已支持单事务 bundle；失败不会污染内存。

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
  `/scene`、SSE 已补目标地图授权；HTTP 交互入口仍需继续收束 viewer 上下文，`list_actions` 仍未过滤 → 真实尾巴记在 **G17**

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
  服务端展开；v0.9 / K-2 起注入的块也会继续展开 → 跨包嵌套任意层）；
  **组件视图注入（`<slot>` 式）已否决**——成本比"壳层挂载点"（DESIGN D52）高一个
  数量级、解决的是同一个问题，且要求一个**没有归属的跨包命名约定**，还会让宿主包
  成为自己扩展性的守门人。**不是"表达力不足时再实现"**（DESIGN.md §4.4 与
  `docs/PLAY_DEV.md` 已同步改口径）
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
  表里的通用命名契约目前只覆盖事件名与少量字段，新增跨包约定请 PR 更新该表。
  **v0.7.0 补充（D31）**：表里那些名字的**载体包已全部废弃**——它们现在只是
  社区包之间的**建议名**，内核与内置目录都不再提供或校验它们。**根本问题仍在**：
  契约的表示形式是"文档 + 自觉"，系统里没有名字级声明（详见 **G39**）

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
- **v0.7.0 审查补充（已修）**：instructions 的**运行期刷新**原先是死代码——
  `engine._refresh_instructions` 写 `mcp.settings.instructions`，而 SDK 的
  `Settings` 没有该字段（赋值抛 ValueError 被宽 `except` 吞成 debug 日志）；
  真正的存储位是 lowlevel server（`FastMCP.instructions` 是只读 property 读它）。
  表现是**工具在、说明书不在**：装/启用玩法包后 `tools/list` 更新了、instructions
  不变。改为写 `_mcp_server.instructions`，并把零工具时的文案改准（原来说
  "未加载任何玩法包"，而世界内容包其实加载着，只是不注册工具）。
  回归测试 `tests/test_review_fixes.py` 两条。**本条的"玩法包注册片段"仍未做。**

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
- **触发**：全面审查——`/auth/login` / `register` / `agent-register`
  全公开（http.py 公共路径白名单）且无失败计数/退避/锁定；register 报
  「用户名已存在」+ login 对不存在账户跳过 PBKDF2（计时侧信道）→ 用户名
  可枚举；~~open 模式 `read-token` 无限签发且 token 无 TTL（只查 revoked）~~
  （**v0.9 已随 `read` 围观档删除 `GET /auth/read-token`**，这一半作废；其余仍成立）
- **影响**：6288 公网端口可无限制爆破/枚举/膨胀 tokens 表；单次 login 为
  200k 次 PBKDF2（身份/identity.py:31），并发请求即 CPU 放大 DoS
- **方案**：按用户名+IP 失败计数指数退避（内存级即可，默认单 worker）；
  统一 401/403 文案 + 不存在账户跑假 PBKDF2（~~read-token 配额或 TTL~~——端点已删）；
  启动防呆 WARNING（open + 0.0.0.0 + 空 ADMIN_KEY 三连）
- **状态**：⏸ 暂缓（记录于 2026-09 安全审查——**报告未入库**，本条即 P0-2 正文；
  2026-09-24 复核：无失败计数/退避/锁定、`identity.py` 里 login 对不存在账户
  短路跳过 PBKDF2——**仍成立**；read-token 那一半已于 v0.9 随档位删除而消失）

### G17 G1 可见性只实现了一端（/scene + SSE + 交互缺口）
- **触发**：全面审查——`/state` 按 `map_visible_to` 过滤（G1 部分解决，见 G1 尾巴），
  但 `/scene`（http.py:210-245）不检查——**任何持 `play` 档的凭据**拿任意 entity_id 可读 private
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
- **状态**：**已失效（v0.7.0 / D31）**——内置行为玩法包已全部废弃，没有"内置包"
  可被社区包覆盖了（内置目录只剩世界内容包）。**机制本身仍然存在**（`load_all`
  以 play_id 为键、社区目录优先），若将来重新引入随服务分发的内容包，此条要
  按原方案正式化（覆盖提示 + 告警 + 覆盖测试）

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
  `admin-*.js`，玩法包管理页组件不在防线内——见新条目 G27）。
  **v0.7.0 补充（D31）**：内置包与其视图组件已废弃，该守卫的扫描对象改为
  **提交在案的参考组件** `tests/fixtures/plays/*/web/*.js`（夹具包装进 tmp 玩法包
  目录）；守卫仍然有效，但覆盖面从"4 个内置视图"缩到"1 份参考实现"

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
  - `world_list` / `world_travel` 跨世界传送未实现（设计见 DESIGN §3.0；⚠ D45 起
    "传到目标世界出生点"这句作废——出生点已不存在，改成"传送到指定地图/地块"）
  - ~~出生点不区分世界（`_spawn_pos` 取首张地图）~~ → **✅ 随 D45 整体消失**：
    内核不再有出生点、不再诞生角色（v0.8.0），"人从哪来"归玩法包
  - 世界间的**数据可见性**：`/state` 仍返回全部可见地图（可见性 G1 过滤），
    未按世界做数据边界
  - 跨包服务仍全局（服务是包与包之间的约定，不是世界内能力面）→ **另记 G62**

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
  - ✅ **已修（v0.7.0）**：管理端多处裸 `int()` → 传非数字直接 **500**（不是 400）。
    点：`admin.py` 的 `page`/`page_size`/`row`/`col`/`to_row`/`to_col`/`count`
    （`_accounts`、`_location_upsert`、`_location_move`、`_connection_update`、
    `_map_create`、`_map_update`、`_entity_create`、`_template_apply`）。
    ⚠ 原列表里还有 `spawn_row` / `spawn_col` 两处——**已随 D45 删除**（v0.8.0）。
    **改法**：新增 `admin.py:_as_int(value, name, default)` 助手，
    20 处 `int(x or 0)` 全部改走它 → `HTTPException(400, "…必须是整数：…")`；
    回归测试 `tests/test_review_fixes.py::test_admin_bad_int_returns_400_not_500`。
  - ✅ **已修（v0.7.0）**：`HTTPException` 在本版本 Starlette 下渲染成**纯文本**，
    与"失败 400 `{"error": …}`"的约定以及中间件那头的 JSON 401 不一致（客户端
    统一 `.json()` 会崩）。**改法**：两个 app 都注册
    `exception_handlers={HTTPException: _http_error}` → 统一 `{"error": detail}`；
    回归测试 `test_http_errors_are_json`。
  - `PUBLIC_PATHS` 用 `startswith` 前缀匹配（`http.py:95-97`）——将来新增
    `/auth/read-token-xxx` 之类路径会**误免认证**；应改为精确匹配 + 显式前缀白名单
  - ✅ **已修（v0.7.0）**：`/plays/{play_id}/web` 前缀校验用字符串 `startswith`
    （原 `http.py:407`）——`<pkg>/web-evil/x.js` 会被判为"在 web/ 之内"。
    改为 `Path.is_relative_to`（与 PlayLoader 的路径安全检查同语义）；
    回归测试 `test_play_web_rejects_web_prefix_sibling`
  - `?token=` 会进访问日志（SSE 的硬需求，不能删）——至少文档化 + 建议反代过滤
  - 停用玩法包不清理 `sys.modules` 残留（同名包换目录重载时可能拿到旧模块）
  - **局部更新语义不完整**（v0.5.2 审计补充）：
    - ~~`PATCH /admin/maps/{id}` 只给 `spawn_row` 会把 `spawn_col` 重置为 0~~
      → **✅ 随 D45 消失**（v0.8.0：出生点两个字段整体删除，不再有这对参数）
    - `POST /admin/connections` 的 `enabled`/`paths` 实际都是必填（`admin.py` 恒传
      `data.get(...)`，缺省 None 被当"显式给值"）→ 只改一个方向不可行
    - `POST /admin/locations`（upsert）不带 `description` 会**清空**整段分时段描述
- **状态**：部分已修（v0.7.0 修掉 `int()` → 400、`HTTPException` 统一 JSON、
  `/plays/*/web` 路径校验三项）；其余（`PUBLIC_PATHS` 前缀匹配、`sys.modules`
  残留、局部更新语义三条）仍待决策——低危但成串，适合一次"收尾清理"批次
- **另（v0.7.0 审查补充）**：JSON-RPC **批处理请求**原先整段不注入身份
  （`http.py:_inject_identity` 的 `isinstance(obj, dict)` 判定），持合法 play
  凭据发批量 `tools/call` 会被判"未认证"且**静默失败**——已修，
  回归测试 `test_inject_identity_handles_batch_requests`

### G27 玩法包管理页组件逃过前端守卫（原生 confirm + 样式守卫盲区）

- **触发**：v0.5.1 前端审计——`worlditor_play_items/web/admin-items.js:118` 用了
  **原生 `confirm()`**，违反 D17"管理端禁用原生 confirm/prompt/alert"（iframe/
  沙箱下被浏览器屏蔽 → 删除操作**静默失效**）
- **根因**：守卫 `tests/test_web_view_styles.py` 只扫 `webui/src`（`:166`），且
  `_view_component_files()` 显式排除 `admin-*.js`（`:67`）——管理页组件不在防线内
- **方案**：① 组件协议扩展——加载器把内核的 `askConfirm` 作为第三个注入参数
  （`new Function("Vue","UiBlock","askConfirm", code)`，DESIGN §4.6 修订）；
  ② 守卫扩到玩法包组件目录（v0.7.0 起为 `tests/fixtures/plays/*/web/*.js`，
  含 admin-*），样式类契约另行放宽；
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
- **回归**：`tests/test_admin_pages.py::test_disable_keeps_admin_entity_templates`
  （内存 + 直连 SQLite 查库双确认；测试原名 `…_item_defs`，物品移除后改名）。

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
- **修复**：`primary` 在 `loadDetail` 后必有具体坐标（**D45 前是"落出生点"，现在落
  "该图坐标序最小的地块"**——出生点已从内核删除，编辑器只需要一个确定存在的格子）；
  删格后**保留该格坐标**（面板原地变"在此新建地块"，可直接重建）；保存前再做一次
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
- **`_ui_components` 是只写不读的死注册表**：旧 API 将 `"<play_id>.<name>" → url` 存入注册表，
  但没有读取者、HTTP 出口或渲染消费方；`UiBlock(kind="custom")` 前端只显示
  `fallback_text`。**处置（本轮）**：已删除 `WorlditorPlayAPI.register_ui_component`、
  引擎对应注册方法/状态及卸载清理分支，公开文档只保留 `register_view` 与 `register_ui_hook`。
  `custom` UiBlock 的 fallback 数据结构仍保留，作为协议输入的降级表示；若未来需要在 UiBlock
  树内联自定义 Vue 组件，再以完整的注册、读取、传输和渲染链路重新设计。
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

---

## 已落地（v0.7.0，D31）

### G39 内置行为玩法包废弃 + 包间契约仍无系统表示
- **触发**：内置玩法包维护失控评估——包数量不多（6 个 / 1139 行 Python + 1013 行
  JS），但"改一处会影响谁"无法回答；审计发现**四类跨包共享面没有任何归属机制**：
  实体 attrs 键（`gold`/`starter_granted`/`energy`）、`play_data` key（`bag:<eid>`）、
  UiBlock kind（`character`）、以及代码/文案里的**名字引用**（工具名 `world_bag`、
  物品 id `apple`/`bread`/`megaphone`）。
- **诊断（这是本条要记住的部分）**：内核治理是两极分化的——**"注册型"命名空间都有闸**
  （工具名冲突报错 D2、视图 key 报错、服务名同包报错、原语 override/disable 与过滤器
  互斥），而**"运行时共享面"一个闸都没有**。原因很具体：这些共享面**从不以注册的
  形式出现**（它们是 handler 里的字面量），注册期检查看不见它们。
  再往下一层：**依赖被声明在"包"这一级（`requires.plays`），耦合却发生在"名字"这一级**，
  且**只登记提供方、从不登记消费方**——所以"谁在消费 X"在系统里没有答案，
  影响面不可计算。这是"控制感流失"的机制，也是当初设计缺的那个建模维度
  （通用解法曾以 `register_player_part：声明 / 冲突仲裁 / 管理页挂载清单` 的形式
  出现在 DESIGN §4.5 阶段 3，但被限定在"玩家部件"这一个场景且从未实现）。
- **本轮已落地（D31）**：删除 6 个内置行为玩法包及其包自身测试（344 → 300 个测试）；
  内置目录只留世界内容包 `worlditor_play_demo_world`。**覆盖没有被删掉**：机制覆盖本来
  就在外壳测试里（`test_engine` 的 ui_hook 四种位置 / `test_filters` 的过滤器链 /
  `test_services` 的跨包服务 / `test_play_runtime` 的视图注册 / `test_admin_pages`
  前四个用夹具包的管理页协议），行为集成覆盖移交**夹具包**：
  `tests/play_fixtures.py` + 提交在案的参考组件
  `tests/fixtures/plays/worlditor_play_demo/web/{view,admin-shop}.js`；
  两处"会因为目标消失而静默空转"的守卫改指参考组件
  （`test_web_view_styles` / `test_version_consistency`）；E2E 把夹具包装进烟雾环境。
- **残留（下一步可做，按需）**：
  1. **包间契约仍无系统表示**（本条的根因，未解）：建议方向——`play.yaml` 增加
     `provides` / `consumes`（名字级声明），加载期校验：双声明冲突报错、悬空消费告警、
     **声明与 `setup()` 实际注册漂移=报错**（否则清单三个月就烂）、无人生产的块告警、
     越权写 attrs 告警；管理端加一页「归属地图」（谁提供什么 / 谁在消费什么）。
     这条做完，"重新切分包边界"才会从大改变成改声明。
  2. **仓库不再有内置"官方玩法"示例**：`docs/PLAY_DEV.md` 的示例与参考实现全部指向
     夹具包；对社区作者而言少了一份随版本分发的现成模板（可用脚手架/模板包补）。
  3. **`_ATTR_LABELS` 那类"猜测性消费表"的教训未被机制化**：中文标签表曾硬编码别的包
     的属性键（`gold`/`starter_granted` 猜对、`energy` 漏掉、`level`/`exp`/`hp`/`stamina`
     四个没人写）。若将来做 `provides.attrs` 声明，标签应由提供方声明、渲染方读声明。
  4. **世界内容仍只有一个内置包**：全新安装有世界可站（`demo_world`），但玩家端**没有
     任何视图 tab**（视图原本来自已废弃的包）——开箱体验是"空界面 + 世界数据"，
     需要时用示例包或脚手架补一个最小视图。

---

## 已落地（实体模型 v2，2026-10-14 立项；G41/G44/G45 为存档项）

> 决策依据：`DESIGN.md` **§12** 与 **D32–D44**。本节记落地结果与存档设计。
> 一句话：**实体 = id + 组件；内核只有实体**。
> ⚠ 本节标题原为"待实施"——G40 / G42 / G46 / G47 / G48 **均已落地**（v0.7.1），
> 只剩 G41（多格实体，搁置）/ G44（阻挡重建）/ G45（堆叠约定）未做。

### G40 实体模型 v2：D32–D40 已落地（总条目）
- **触发**：一次"取消字段、全部用组件"的重构推演，收敛为完整数据模型（九轮，2026-10-14）
- **决策摘要**（详见 §12 / D32–D39）：
  - D32 实体 = `id` + 组件字典，**无必填组件**；D33 信封 `source:name` + `core:` 保留命名空间且写入不经分派
  - D34 `state` 退役 + **阻挡机制整体移除**；D35 `kind` / `tags` 折叠为组件（能力即组件）
  - D36 `core:position` 可选（"不在任何地方"是合法状态）；D37 **内核移除物品**（取代 D8）
  - D38 `revision` / `changed_tick` 留表列；D39 索引只内存（G42 已实施）
  - D40 **观察方式归玩法**：内核不做通用实体渲染 / 组件声明端点 / 组件渲染器（见 G43）
- **影响面（实测命中数）**：内核 `engine.py` 105 / `api.py` 33 / `model.py` 19 / `mcp/http.py` 18 /
  `admin.py` 16 / `identity.py` 10；前端 `EntityManager.vue` 74 / `MapEditorPage.vue` 17 /
  `FieldForm.vue` 15；**测试约 263 处 / 17 个文件**；落库 `entities` **14 列 → 4 列**
  （实际分三步落地：v8 → **13 列**、**v9 → 10 列**、**v10 → 7 列**；4 列是第 2 期目标）
- **连带文档**：`DESIGN` §2.1 / §3.1 / §3.2 / §4.1 / §4.2 / §11 与 D8（被取代）/ D9（被取代）/
  D18 / D19 / D20 / D21 / D23 / D28 / D30 均需修订
- **分期**：① 数据面组件化 → ② `state` 退役 + 阻挡移除 + 能力折叠 → ③ 物品移除 → ④ 索引（G42 已实施）
- **实施顺序建议**：第 1 期是确定的；第 2 期牵动能力面与身份红线（D20）；第 3 期独立可验证
- **状态**：✅ **D32–D40 已落地**（2026-10-14；D41–D44 为后续扩展）
  - ✅ **第 1 期已落地**：数据面组件化——`Entity.components` 取代 `attrs` / `state`
    两个容器；组件名 = `source:name` 信封（`model.split_component_key` 校验）；
    **`core:` 内核保留命名空间**（`WorlditorPlayAPI` 拒绝玩法包写入，D33）；
    组件原语 `add_component` / `set_component` / `remove_component`（走分派表）
    + `get_component` / `list_components`（只读，不进分派表）；
    字段原语 `set_data` / `get_data` / `remove_data` 加必填 `component` 参数；
    `core:perception` 承载 G1/G12 的 `invisible` / `see_invisible`
  - ✅ **第 1b 期已落地（原排第 2 期）**：**阻挡机制整体移除**——`TagSpec.block_move`、
    `register_entity_kind(block_move=…)`、`_is_blocking` / `_blocker_at`、
    `move()` 的阻挡检查、`core:state` 全部删除（详见 D34 / G44）。
    **为什么提前**：D33 让玩法包写不了 `core:`，于是"开门解除阻挡"这条**唯一**的
    动态阻挡通道断掉——两步存在硬依赖，分开做会留下一个"门永远关着"的中间态
  - ✅ **落库与启动策略（第 1 期）**：`entities` 13 列（`attrs_json` + `state_json` →
    **`components_json`**）、删掉死的 `idx_entities_pos`；表结构版本 **v8**（1c 起 **v9**、
    1d 起 **v10 / 7 列**）+
    **版本闸**（`_check_schema`：`world_meta.schema_version` 值不符 /
    **后加列清单**缺列——兜住"没有版本记录的极老库"，否则会撞裸 `IndexError`；
    **不该存在的列**——见下条；缺列**一次报全**）。消息指名 `world.db`，
    **`ALTER TABLE` 补列逻辑整个删除**——补出来的 `components_json` 是空默认值，
    会把旧实体数据**静默清空**
  - ✅ **1c 期已落地（原属第 2 期）：名字 / 描述 / 账户绑定进组件**——`core:info`
    （`name` / `desc`）+ `core:account`（`user_id`）；`entities` **13 列 → 10 列**
    （三列删除，数据搬进 `components_json`），表结构 **v8 → v9**；
    `Entity.name` / `desc` / `user_id` 变成**只读 property**（派生视图，缺失 →
    `id` 前 8 位 / `""` / `None`），`to_dict()` **不再给顶层三键**，
    `from_dict` / `place_entity(name=…)` / 实体模板负载保留顶层三键作**输入便利**
    （折进对应组件，内部只有组件一种形态）
    - **版本闸加第二半「不该存在的列」**：库里还带着 `entities.name` / `desc` /
      `user_id` → **拒绝启动**并列出这些列。理由：只查"需要的列在不在"查不出
      多出来的旧列，而那种库会**载入成功但名字 / 描述 / 账户绑定被静默丢掉**
      （载入只读 `components_json`，那三列再没人看）
  - ✅ **1d 期已落地（原属第 2 期）：位置进组件**——`core:position`
    （`map_id` / `row` / `col`）；`entities` **10 列 → 7 列**（三列删除，数据搬进
    `components_json`），表结构 **v9 → v10**
    - **D36 的"不在任何地方"从此可表示**：`Entity.map_id` / `row` / `col` 变**只读
      property**，缺失返回 **`None`（不是 `""` / `0`）**——空值兜底会把"缺失"变成静默
      错误（实体静默出现在 (0,0)、静默参与按位置筛选）；新增 `has_position()` /
      `pos_key()`（无位置 → `None`）/ `require_position()`（"必须在场"的路径显式调用）
    - **读点分两类**：`list_entities` / `query_entities` 默认 `include_absent=False`
      **跳过无位置实体**（`True` 时才带上）；按位置的筛选条件对无位置实体**不匹配**；
      `move()` 对无位置实体**报错**"实体不在任何地块"；`_build_scene` 用
      `require_position()`；`query_entities` 的排序键改用**哨兵值**（否则 `None` 会与
      `str` 比较而炸）；`lint_map` 的悬挂检查先跳过无位置实体
    - **版本闸扩到六列**：`map_id` / `row` / `col` 进「不该存在的列」名单。理由比 1c 更硬——
      放行一个 v9 的库会得到"**每个实体都不在世界**"，那是 D36 合法状态的**最坏误用**
      （迁移事故被合法语义掩盖）
    - **前端同规矩**：位置读点收进 `webui/src/entity.js`（`entityPosition()` /
      `hasPosition()` / `positionLabel()` / `positionSortKey()`），组件不许直接读
      `e.row` / `e.col` / `e.map_id`——那些键**已不存在**，读到 `undefined` 不报错：
      过滤静默返回空、排序静默退化、网格静默画到 (0,0)。守卫在
      `tests/test_editor_integrity.py`
    - **落地时漏数了一个读点（如实记录）**：`_event_payload` 的 `on_entity_move`
      在实体"从世界外移回来"时对 `None` 调 `list()` → `TypeError`。事前分类数出 3 个
      位置读点，实际是 4 个；两侧已加空值守卫，事件负载里 `from` / `to` 可以是 `null`
  - ✅ **第 2 期（能力面折叠）已落地**：**D41–D44 + §12.6**（2026-10-14 拍板，
    v0.7.1 实施完成）。**施工计划与交接见 `docs/ENTITY_FOLD_PLAN.md`**（已完成，留作记录）。
    终态 = 表 **v11** / **4 列**、`to_dict()` **5 键**、能力 = 组件的存在、身份概念删除、
    组件命名空间即写入边界、卸载不删数据（四象限诊断 + 管理员手动清理）。
    **一步做到位**（不设"2a 不改表"的中间态——那不是设计要的形态，且 D13 本就删库重来）
    - 原分叉（能力名要不要带 source）**已答**：带（`<play_id>:<name>`），
      于是"同名标签后注册覆盖"整条作废、两个包各声明 `merchant` 是**两个组件共存**
    - **`core:player` 取消**：身份概念整个删除（D42），红线改判 "**绑定了账户的实体不可删**"
  - ✅ **第 3 期已落地**：**内核移除物品**（D37 取代 D8）。实测删除面：
    `model.py`（`ItemDef` / `item_db_row` / `item_from_row` / `WORLD_EVENTS` 里的
    `on_item_used` / `InteractionRequest.item_id`）、`store.py`（`items` 表 DDL /
    `self.items` / `save_item` / `_insert_item` / `delete_item`）、`engine.py`
    （`_item_def_play` / `_item_def_user` / `_item_fields` 三个注册表 +
    `register_item_def` / `item_defs_of_play` / `flush_item_defs` / `delete_item_def` /
    `add_item_fields`、`clear_play_registrations(keep_user_items=…)` 参数）、
    `play/api.py`（7 个 API + `interact` 的 `item_id`）、`play/__init__.py`
    （`load_all` 的落库调用 + `_teardown_one` 的"幽灵物品"清理）、`world/__init__.py` 导出。
    **替换关系**：类型 → 组件声明（`register_entity_tag`）；实例 → 实体 + 组件；
    `use_action` → interaction 名；管理员手工物品 → **实体模板**；
    `item_id` 槽位 → `args`；`on_item_used` → 玩法包自定义事件
  - **落地偏差（如实记录）**：第 1 期原计划含 `core:position` / `core:info`，
    实际收窄为"只做数据面容器 + 感知组件"——位置与名字保持表列可把改动面小一个数量级，
    且不影响"数据按组件分组"这一核心收益；搬进组件归第 2 期。
    **补记（1c）**：名字 / 描述 / 账户绑定（`core:info` / `core:account`）已按原计划补做。
    **补记（1d）**：位置（`core:position`）也已按原计划补做。**至此"取消字段、全部用组件"
    这一诉求在数据面上已经完整**——名字 / 描述 / 账户 / 位置 / 感知**全部**是组件，
    表上当时只剩 `id` / `kind` / `tags` / 存储元数据；**当时只差能力面（`kind` / `tags`）
    与 `core:player`，那一步卡在 G47 的命名分叉上**——**后续已被第 2 期（D41–D44）
    取代：`kind` / `tags` 两列已删（表 v11 / 4 列），`core:player` 决定不引入（D42）**

### G41 占位（footprint，多格实体）——搁置，设计存档
- **触发**："实体存一个位置的同时，地块也存该格的实体 id"，并考虑"一个实体 id 出现在多个地块"
- **裁定**：⏸ **搁置**（用户 2026-10-14 裁定"后面有需要再做"）。要让"一 id 多格"可表示，前提是先有占位语义
- **存档设计**（需要时照此实现）：
  - **形状**：`core:position` 增 `w` / `h`（矩形简写，**`1×1` 时省略** → 纯增量，省略即现状）或
    `cells`（不规则偏移，与 `w` / `h` **互斥**，同时出现报错）
  - **单一真相 = anchor**（`row` / `col`）；占格 = anchor + 偏移（**派生**）；地块 id 索引 = 再派生一层
  - **占格 ≠ 阻挡**（正交分解）：占位只回答"占据哪些格子"，"能不能过去"是另一件正交的事
    （v2 已移除阻挡，见 G44）
  - **总原则**：**事件与感知一律以 anchor 为准，只有"占据关系"用占格**——`on_entity_enter` 只触发
    一次、`on_entity_move` 的 from/to 用 anchor、隐身/感知与格无关；`/scene`、`_blocker_at`、
    地块实体列表用占格。没有这条原则，footprint 会渗透进事件/感知/查询/SSE 每一层
  - **移动两个坑**：① **自排除**（2×2 右移一格，新占格与旧占格重叠 2 格——不排除自己就永远动不了）；
    ② `move_entity` 是**传送语义**（不做阻挡检查）→ 占位化后只做结构性校验
  - **新规则**：重叠**允许**（现状本就允许，`place_entity` 无重叠校验）→ `lint` 提示；**任何占格悬空禁止**；
    `delete_location` 拒绝（提示"被「巨石」(2×2，主格在 x,y) 覆盖"）；`move_location` **只移 anchor 在源格的实体**，
    占格覆盖但 anchor 不在 → **拒绝**（否则搬完悬空）
  - **编辑器**：多格整体绘制 + anchor 角标 + 点任一格选中 + 框选整体复制 + `w/h` 表单
  - **替代方案（更省）**：只是摆装饰可用 N 个 1×1 实体拼（引擎与编辑器**零改动**）；
    只有需要"作为整体被引用"（可搬走、任务目标、巨人玩家）才值得做占位
- **状态**：⏸ 搁置（设计存档，不排期）

### G42 地块 → 实体 id 索引（已落地）
- **触发**：同上；且实测发现 `idx_entities_pos` **是 v4 遗留死重**——实体相关 SQL 只有
  `SELECT *` 与 `DELETE WHERE id = ?`，**没有任何查询用它**；`list_entities(row,col)` /
  `query_entities(row,col)` / `/scene` **全部是内存线性扫描**
  （⚠ 原条目把 `_blocker_at` 也列在这里，它已随 v2 第 1b 期**整体移除**——阻挡机制没了）
- **策略（D39）**：**只存内存**（`store.entities_at`），不落库——纯派生数据，落库只增加跨表
  不一致风险、零收益（启动本就全量载入）；维护点收敛到 `save_entities` +
  **反查表 `entity_id → pos_key`**（因为 `save_entities` 拿到的实体**位置已被就地改过**，
  看不出旧格）+ `delete_entity`；配自检"**索引 id 总数 == 实体总数**"（占位搁置后不变式
  简化为"每个实体恰好出现一次"，一个 count 即可发现漏摘/漏登）
  - ⚠ **自检不变式已被 D36 改写**（v2 第 1d 期起，**实施时按新口径写**）：
    "不在世界上"的实体（没有 `core:position`）**本来就不该出现在索引里**，所以不变式是
    "**每个在世界上的实体**（`has_position()` 为真）**恰好出现一次**"，count 一侧要拿
    `has_position()` 过滤后的数量去比——照抄原文的"== 实体总数"会**永远差着那几个离线实体**，
    自检当场误报（而一个会误报的自检等于没有自检）
- **成本**：约 10 个位置写入点（place / move / move_entity / move_location / copy_map /
  delete_location / delete_map / 账户注销 / 模板套用 / 启动重建）
- **注意**：这是"**漏一处就是静默错误**"的那类东西（与 G38 残留 1 的标签倒排索引同族）——
  所以自检不是可选项
- **状态**：✅ 已落地（只存内存，启动重建；数据库结构不变）。当前查询已使用完整坐标索引；后续可再补公开自检命令。

### G43 渲染 / 观察方式：内核不做（已决策，D40）
- **触发**：实体组件化引出一个问题——玩家端要不要"通用实体渲染"（内核按 `core:info` +
  声明 schema 画出实体，零包可用）、要不要补组件声明端点 `GET /components`、
  要不要做"组件渲染器"（每个组件可挂自定义 Vue 外观，即 G35 预留位的语义扩展）
- **裁定**：❌ **内核都不做**（用户 2026-10-14）——**观察世界的方式也是玩法的一部分**
- **依据（不是新增约束，是执行已有原则）**：`DESIGN §0` 内核定位原文即"不知道玩家怎么移动、
  **视野多大**、怎么说话、**页面长什么样**"；§2.3 红线同理
- **内核保留的边界（通道与宿主，不是内容）**：数据出口（`/state` / `/scene` / `/events`
  的原始数据）、视图路由与加载（`register_view` provider + IIFE 组件协议）、
  UiBlock 渲染协议（`UiBlockRenderer.vue`）与 `ui_hook` 注入通道
- **⚠ 代价（如实记录）**：**全新安装玩家端仍然是空界面**——G39 残留 4（"开箱体验 =
  空界面 + 世界数据"）**不由此解决**，要有视图必须装玩法包；**组件化不改变这一点**
- **连带**：`core:info` 保留，但理由从"供渲染"变为"**内核自己的文案**"（`lint_map` 的
  「实体「{name}」…」、`delete_location` 的「有玩家「{name}」位于该地块」、日志）；
  客户端要不要用它兜底显示 id，是玩法包的自由
- **仍然观察到的既成事实（不重新讨论，仅记录）**：内核里已存在的"观察相关"设施——
  `/state` 的地图 `visible` 过滤与实体 `invisible` / `see_invisible` 感知过滤（G1/G12）、
  UiBlock 渲染器、`ui_hook`——都属"通道"侧；若将来要按 D40 的口径把**可见性规则**也
  下沉，那是另一次决策（不在本次范围）
- **状态**：✅ 已决策（D40）／❌ 不做

### G44 阻挡能力内核组件（移除后待重建）
- **触发**：v2 整体移除 `block_move`（标签声明 + `state` 动态覆盖）——**所有实体不阻挡**
- **待定**：将来若需要，**另立一个"描述阻挡能力"的内核组件**（名字、语义、是否支持动态覆盖均未定）
- **现状替代**：门的开关 / 机关 / 墙 / NPC 挡路 → 玩法包 `override_primitive("move")` 或过滤器链（D11 已支持）
- **对现部署零影响**：内置世界包 `demo_world` **不注册任何 kind**（无 `block_move` 声明），
  木门的 `state:{"open":false}` 里 `open` 内核从不读 → 当前部署本就没有任何东西在挡路
- **状态**：⏸ 后续再考虑

### G45 物品堆叠的表示（三档模型，拟转 PLAY_DEV 约定）
- **触发**：物品下沉到玩法包（D37）后，"一堆苹果里给其中一个下毒、混在其中不认真看不会区别"
  需要一种堆叠表示；且"每实例一个 id"在规模上不可行
- **实测依据**：单个实体对象 **1505–2252 B**（10 万 = 143–215 MB，100 万 = 1.4–2.1 GB），
  而"数量"表示 **344 B 且与数量无关**——差 600 万倍；且**背包比世界大得多**
  （30 格 × 100/格 × 10 玩家 = 30,000，而世界上限目标是"几百到几千实体"，§11）
- **存档设计**（拟写成 `PLAY_DEV` 约定 + 参考实现，**不属内核协议**）：
  - **一个概念**：`lot = {n, state?, id?}`；一堆 = 一串 `lot`；**总数 = `sum(lot.n)`**
  - 三档自然掉出：**匿名数量**（1 个无状态无 id 的 lot）/ **批次**（多个有状态 lot，
    用于"先后腐败"——成本只随**批次数**增长，与数量无关）/ **具名个体**（带 `id` 的 lot）
  - **"混在其中"的硬性要求**：具名个体**计入总数**；默认出口**只显示总数**，`lot` 结构必须折叠
    （否则"99 个普通 + 1 个特殊"一眼暴露）；这是**协议层义务**，不只是 UI 细节
  - **独立实体（在地上）** = 携带同一组件的实体——**一堆苹果丢在地上是一个实体，不是 N 个**
  - **切分（`split`）** 是"给一个个体加身份"的统一动作（下毒 / 挂保险 / 标记任务道具都是它）
  - **取出禁止确定性顺序**（否则"拿一个放回去"重复 100 次必得毒苹果）——随机或检视后精确取出
  - **拿出/放回无损**（状态原样搬运）；**并回匿名数量会丢状态 → 必须确认或拒绝**（D23 口径）
- **状态**：⏸ 归档（转 `PLAY_DEV` 时启用）

### G46 通用实体管理页（✅ 已落地，随 v2 第 1d 期）
- **触发**：实体模型 v2 需要管理端能编辑**任意组件**（含虚构组件）；同时"**无位置实体**"
  （下线玩家）必须能被找到，否则**下线即失联**（谁也没法让他上线）
- **方案**：做**一张通用实体管理页**（列出全部实体，含无位置者并标注"无位置"）——
  **不专门为无位置实体另做视图**（用户 2026-10-14 裁定：通用页天然覆盖它）
- **状态**：✅ **已落地**（2026-10-14，随 v2 第 1d 期——D36 落地后这个缺口从"将来会有"
  变成"现在就有"：位置可选了，而**地图视角按坐标裁，不在世界上的实体一个都看不见**）
  - **后端**：新增 `GET /admin/entities`（`?absent=0|1`、`?world_id=`；带 `total` /
    `absent` 计数，`entities[].capabilities` 同地图详情）。不在世界上的实体按**默认世界**
    算激活（`_world_for_activation`：没有归属 ≠ 没有规则）
  - **前端**：新增管理台「全部实体」页（全局导航，`#/admin/entities`）——**复用
    `EntityManager`**，加 `allow-absent` 开关：勾"放进世界"才发坐标，不勾就造一个不在
    世界上的实体；「定位」跳到地图编辑器并选中该格（`#/admin/maps/{map}/{tab}/{row}/{col}`，
    编辑器为此支持地址栏带格）
  - **创建路径**：`place_entity` 的位置三参数变可选，**全有或全无**（半截报错）；
    `POST /admin/entities` 与玩法包 `api.place_entity` 同步放开
  - **顺带修掉**：实体模板不再带 `core:position`（模板是"这东西是什么"，不是"它在哪"——
    带上位置会让套用**静默把实体搬回老地方**）；`EntityManager` 的"不放进世界"分支
    还会从组件里剔掉位置键，否则勾选形同虚设
  - **测试**：`test_admin_pages.py::test_entity_endpoints_cover_absent_entities`（HTTP 全链）、
    `test_v2_components.py` 的 `place_entity` 不给坐标 / 半截坐标 / 重启后仍在；
    `test_editor_integrity.py` 守前端（不许直接读 `e.row`）

### G47 能力组件的命名：`kind` / `tags` 折叠的分叉（**✅ 已落地**，见 D41–D44）
- **触发**：v2 第 2 期要把 `kind` / `tags` 折叠成组件（D35："实体带某组件 = 具备该能力"）。
  于是**能力名也必须满足 `source:name` 信封**（D33 规定信封无例外），而今天它们是裸名。
- **后果（这是它必须先定、不能边做边定的原因）**：
  1. `place_entity(kind="merchant")` / `entity.kind` / `entity.tags` 都要变成"裸名 → 组件键"的解析
     （内核 42 处 `kind` 读写 + 约 20 处测试断言）
  2. **D19"同名标签后注册覆盖"的语义会变**：命名空间化后两个包的同名标签是**两个组件共存**，
     而不是后者覆盖前者；"卸载即恢复前一个"也随之改变
  3. 玩法包写 `register_entity_kind("merchant", …)` 时是否要显式给 source（还是内核自动补自己的 play_id）
- **两种自洽答案**：
  - **(i) 能力组件也带 source**：注册者 play_id 作 source（`worlditor_play_trade:merchant`），
    未注册的实例标签落 `local:`，身份落 `core:player`。**彻底统一**，但吃下上面 1/2/3 三项代价，
    并且"裸名解析"要新增一层索引（多包同名时后注册者胜）。
  - **(ii) 能力名保持独立命名空间（**不折叠**，D35 撤销或改写）**：`kind` / `tags` 继续是
    "能力面的名字"，`components` 只管数据。代价是"能力面与数据面"仍有两个命名空间——
    但这正是 v2 想消灭的那个不一致。
   - **不再需要新造机制**（原担心的"优先级 / 合并顺序 / 冲突裁定"**整个消失**）：
     两个包各声明 `hp` 就是 `fps:stat.hp` 与 `moba:stat.hp` 两个不同地址。
     保留的唯一规则：**同一组件内同名字段声明两次 → 报错**
- **状态**：✅ **已拍板（2026-10-14）——选 (i) 的加强版，见 D41–D44**
  - **最终答案**：**能力组件也带 source**（`<play_id>:<name>`，注册时由内核自动补调用者的
    `play_id`，所以 `register_entity_kind("merchant", …)` 的调用点**零改动**）；
    无人声明的裸名落 `local:`；**多个声明者 → 报错**；解析不出来 → **报错**（不静默落 `local:`）。
    **解析发生在写入时**（落库键即最终键）
  - **比原 (i) 方案多走了一步**：`kind` **整个删除**（不是留着当"基底类型"）——
    因为身份改由 `core:account` 承担（D42），而"类型 = 一组组件的预设"这个角色
    本来就与**实体模板**重复
  - **原方案里的 `core:player` 取消**：用户裁定"身份彻底移除，也不要 `core:player`
    这个组件，直接做减法精简掉"（D42）
  - **`local:` 暂不收紧**（D43）：玩法包仍可写 `local:`——夹具与文档例子一行不改，
    本次只拦"**别人的 `<play_id>:`**"
  - **附带问题（字段属于哪个组件）的答案**：折叠后**声明它的组件就是字段的家**；
    并且**删掉跨组件摊平与分类字段**（D41）——`FieldForm` 的 `homeOf` / `fallbackName`
    整套"猜落点"逻辑随之删除，改成按组件分组渲染
  - **为什么值得先想清楚（历史记录）**：这是语义级分叉——选 (i) 会改掉 D19 的
    "同名标签后注册覆盖"，选 (ii) 则让 v2 想消灭的"能力面与数据面两个命名空间"留下来；
    两条路各自自洽，但**组件键一旦落库，改命名 = 又一次全量数据作废**
  - **一轮反复（如实记录）**：同日先裁定「先别动能力面，保持现状」（暂缓），
    随后在讨论中把模型想透（"两个 `hp` 根本是两个东西"、"`local:中毒` 与
    `bestiary:中毒` 不是一回事"、"卸载 = 数据留下、行为消失"），**改判为"设计已定、待实施"**。
    本次讨论同时纠正了我（助手）两处判断失误：① 误以为折叠必然把"顺序"变成 dict 键序
    （实际是"顺序来源消失"，且被"两个东西"这一洞察**消解**掉）；② 误说"卸载会丢数据"
    （实际卸载一个字节不动，数据只在**手动清理**那一步被删）
  - **落地结果（D41 / D42 / D43 已实施，表 v11 / 4 列）**：`Entity.kind` / `Entity.tags` 删除
    （判能力用 `has_component`）；`declare_component` 为唯一声明入口（旧名为等价别名）；
    `register_entity_kind(tags=…)` 作废（预设归实体模板）；字段按组件分组、分类字段删除；
    `capabilities()` 报 `components` / `active_components` / `inactive_components` /
    `unknown_components` / `interactions` / 分组 `fields`；`list_kinds()` 只剩一张组件清单。
    **实现时补的一条（原设计没写）**：`local:` 是**内容与跨包协作的公共命名空间**——
    世界内容用 `local:` 写实体组件，行为包**声明 `local:<同键>`** 即可对接
    （否则"世界包 + 行为包"这对软依赖会**依赖加载顺序**：内容先导入就落 `local:`、
    行为包先声明就落 `<play_id>:`，同一份内容两种键）。见 DESIGN §12.6 落地补充
  - **仍未做（D44 / G48）**：四象限诊断（`orphan` 与 `fictional` 分开报）、
    孤儿组件清理端点、删 `_tag_owner`

### G48 组件四象限诊断与孤儿清理（**✅ 已落地**，D44）
- **触发**：折叠后**不存在"同名标签"**，卸载一个玩法包 = 组件留在实体上、行为消失
  （键稳定 → 重装即恢复）。于是要能回答"这个组件为什么没效果"，并且给"永久孤儿"一条出口
- **设计（D44）**：
  - **四象限**：`active` / `inactive`（世界没启用）/ **`orphan`**（source 那个包没加载或已卸载）
    / `fictional`（`local:` 或从未声明——**本来就没有行为，不是坏了**）
  - 判定 = `source = key.split(":")[0]`；**归属从"另存一张表"变成"读名字"**（`_tag_owner` 删除）
  - **顺手修 C8**：今天停用包时 `clear_play_registrations(purge=False)` **把规格也删了**，
    于是 `capabilities()` 报 `unknown_tags`（"未声明"）而 `_live_tags()`（query）仍认为
    "有主但不活跃"——两边结论一致但**解释不一致**，`inactive_tags` 那个桶**永远装不到
    "包被停用"**（而停用是最常发生、最该被解释的情况）
    - ✅ **已修（D41-a 落地）**：`clear_play_registrations(purge=False)` **不再删规格**，
      只有 `purge=True`（真卸载）才连同归属记忆一起清——停用现在正确地落进
      `capabilities()["inactive_components"]`，不再误报"未声明"（D41-b 已随之改名）
- **清理规则（用户 2026-10-14 定）**：
  - **只有"已卸载"可清**：`disabled`（停用）与 `load_failed`（加载失败）**都不可清**——
    包还在，启用 / 修好即恢复
  - **必须管理员手动执行**，且**服务端强制**只接受 `orphan` 的 source
    （不能只靠界面把按钮藏起来）
  - **先 dry-run 再删**（受影响实体数 / 键 / 样例实体 id）
  - 粒度 = 按 source 全清或 `keys` 子集；**不支持按实体挑**
  - ⚠ **判定优先级：先看目录在不在**——`_disabled` 是**持久化的 play_id 集合**，
    包目录删掉后 id 仍留着，"在 `_disabled` 里"**不等于**"包还在"
  - ⚠ **清理是双重不可逆**：能力 = 组件的存在 → 删掉 `pkg_b:duel` = **数据没了、
    该实体的这项能力也没了**；重装只对**还带着该组件的实体**恢复行为
- **接口落点**：只读 `GET /admin/orphan-components`（或并入 `/admin/plays` 响应）；
  执行 `POST /admin/orphan-components/purge`；事件复用 `on_world_edited`
  （`{op: "purge_components", …}`，**不加第 8 个内核事件**）；落库走 `save_entities`（D28）
- **界面落点**："玩法包"页——**停用的包在列表里**（每行显示"遗留组件 N 个"+ "启用即恢复，不可清理"）；
  **已卸载的包不在列表里** → 单开一栏"**已卸载包的遗留组件**"（两种情况天然分栏）
- **状态**：✅ **已落地（D44）**——`capabilities()` 四象限（`active_components` /
  `inactive_components` / `orphan_components` / `fictional_components`）、
  `engine.diagnose_components(package_state=…)` 按 source 聚合、
  `engine.purge_components(source, keys?, dry_run=True)`；
  管理端 `GET /admin/orphan-components` + `POST /admin/orphan-components/purge`
  （服务端只接受"包真的不在了"，默认 dry-run）；`_tag_owner` 已删（归属读键 + `spec.play_id`）。
  前端"玩法包"页两栏：**包还在**（停用 / 加载失败 → 不可清理）/ **包已卸载**（可手动清理）。
  ⚠ **落地时补的一条**：`local:` 一律算 `fictional` 且**永不可清**（键里读不出归属，
  可能是人手写的数据）；非 `local:` 且查无声明才算 `orphan`。另外真卸载清理规格时
  按 **`spec.play_id`** 而不是键里的 source——共享命名空间 `local:` 的声明者也是某个包，
  按 source 清会漏掉它们（实测：包卸载后规格还在，query 就再也不匹配了）

---

## 玩法包可用性审查（v0.7.3，2026-10-16）

> 触发：三路审查（文档一致性 / 安装卸载生命周期 / 重构遗留）+ 一手实测，问的是
> "现在能不能让第三方照 PLAY_DEV.md 写包"。结论：**机制够、交付面不够**。
> 本节记这一轮发现与处置；已修项标注落地位置，未修项保留设计口径。

### G49 卸载不删 `play_data`（文档说删）——已修文档，语义保持"保留"
- **现象**：`store.py` 全库**没有 `DELETE FROM play_data`**；`uninstall(purge=True)`
  只清"组件归属记忆"（`_tag_specs`）。但 `uninstall` docstring 与 `PLAY_DEV.md` 都写
  "删目录含其数据，不可逆"，管理端确认框也这么提示。
- **影响**：作者按"卸载即清空"设计（例如把存档放 KV），实际同名重装数据**静默复活**；
  反过来管理员以为删干净了，磁盘（SQLite）里还留着。
- **处置**：✅ 文档说真话（`PLAY_DEV` §2、`uninstall` docstring）——**KV 与实体组件
  一律保留**，"卸载只删包目录"。是否要给一个显式的"连数据一起删"开关，等真实需求。

### G50 玩法包只能单文件——✅ 已修（v0.7.3，方案 B：包语义加载）
- **现象（修复前）**：`main.py` 被当**顶层模块** exec（`play/__init__.py:_load_module`），
  包目录不在 `sys.path`、也不是 Python 包 → `import helper` / `from . import helper`
  全部 `ModuleNotFoundError`（实测）。
- **为什么不用"把包目录塞进 sys.path"**（曾评估的方案 A）：`sys.modules` 按**裸模块名**
  缓存、`sys.path` 是全局扁平列表——两个包各有一个 `helper.py` 时，先导入者永久占名，
  后一个**静默拿到别人的模块**（本地实测：B 包跑出了 A 包的 helper）；且包目录排在
  `sys.path` 前面会遮蔽标准库同名模块（放个 `json.py` 就中招）。
- **✅ 落地（方案 B）**：`_load_module` 用 `spec_from_file_location(..., submodule_search_locations=[包目录])`
  ——`main.py` 成为包 `<play_id>` 的入口，包内 `from . import helper` 解析成
  `<play_id>.helper`。模块全名带唯一 play_id，天然隔离，不碰 `sys.path`；
  绝对导入 `import helper` 会**响亮失败**（不再是静默拿到别人的模块）。
  **卸载/停用清缓存**：`_forget_modules(play_id)` 按 `play_id` 与前缀清 `sys.modules`
  （teardown 之后调用），顺带修掉 CORE_AUDIT §4 记的"sys.modules 卸载残留"——
  "改代码 → 停用 → 启用"现在能拿到新代码。
- **测试**：`test_play_manage.py` 5 条（相对导入可用 / 两包同名 helper 互不串味 +
  不污染裸名空间 / 绝对导入响亮失败且不留缓存 / 停用清缓存后拿到新代码 / `sys.exit`
  隔离）。⚠ 文档提醒：改文件要**改到字节数不同**，否则 CPython 的 `__pycache__`
  判据（mtime 同秒 + 大小相同）会继续用旧 `.pyc`。
- **仍不做**：两个包依赖**同一个 pip 包的不同版本**仍无解（同进程同一 site-packages），
  真要隔离得上子进程 / 独立 venv。

### G51 只读接口是"浅只读"——✅ 已修（v0.7.3）
- **现象（修复前，实测）**：`api.get_component()` 返回**浅拷贝**（`dict(data)`）——改嵌套的
  dict/list 会**改到内核内存里的实体数据**；`api.get_map()` / `get_location()` /
  `get_world()` / `list_worlds()` / `list_folders()` / `list_templates()` /
  `capabilities()`（`fields` 是**声明对象**）/ `kv_get()`（KV 缓存里的同一对象）直接返回
  内核**活对象**（改 `loc.name` 真的改名）。只有 `get_entity` / `list_entities` /
  `query_entities` 是深拷贝。
- **影响**：不落库、不发事件、不盖 `revision`，但运行中的世界快照会漂移，重启才"自愈"。
- **✅ 落地**：`WorlditorPlayAPI` 的只读出口一律 `copy.deepcopy`（**只动 API 层**——
  引擎内部的 `get_map` 等保持原样，热路径不受影响）；`list_actions` 补
  `viewer_id` / `tier` 透传（看不见的目标返回空菜单，玩法包自建界面也能按感知过滤）。
  回归测试 `tests/test_play_readonly_snapshots.py` 3 条：地图名 / 地块名 / 世界名 /
  模板 data / KV / 组件嵌套值 / 能力声明逐条验"改了不影响内核"。

### G52 实体模板未按世界激活过滤——待做（文档已纠正）
- **现象**：`engine.list_templates(scope)` 只有 scope 参数；`PLAY_DEV` §3 的"世界激活"
  表里曾写"实体模板不出现在管理端模板列表"（未实现）。只有**整包停用/卸载**才消失。
- **方案**：`list_templates` 加调用者世界 + 激活集合过滤（与 `/views` 同口径），或把
  文档口径改成"模板不分世界"。

### G53 安装一致性三连洞——✅ 已修（v0.7.3）
- **现象与修法**：
  1. **顶层目录名 ≠ `play.yaml` 的 name**：安装返回错的 play_id、包以 yaml 名加载，
     `uninstall` 按目录名定位 → **两个名字都卸不掉**，目录永久残留（实测）→
     现在解压后校验 `spec.play_id == 目录名`，不符即回滚报错。
  2. **目录缺 `worlditor_play_` 前缀**：装得上、`list_plays` 看不到（discover 只认前缀）、
     重启后静默消失 → 现在安装即拒绝。
  3. **与内置包同 id**：顶掉内置、重启后两个都不加载、社区目录删不掉 → 现在安装前
     检查 `_find_candidate`；`load_all` 同名冲突改为**先扫到的胜出（内置优先）**并在
     `list_plays().note` 里说"同名目录被忽略"；`uninstall` 只删**社区那份**，
     已加载实例不属于被删目录时不动它。
- **落地**：`play/__init__.py`（`install_zip` / `load_all` / `list_plays` / `uninstall` /
  `_find_candidates`），回归测试 `tests/test_play_manage.py` 6 条。
- ⚠ **`install_zip` 仍无测试覆盖之外的保护**：管理端上传前用 `request.body()` 读完整
  body 才判体积（admin.py），没有中间件级上限；条目数/解压比也没限。

### G54 MCP 工具 handler 异常静默——✅ 已修（v0.7.3）
- **现象**（实测）：工具 handler 抛非 `WorldError` 异常 → 客户端只拿
  "工具执行出错，请稍后再试"，**服务端零日志**（`mcp/__init__.py` 连 logger 都没有）。
  其余 7 条玩法包回调路径（交互 / 事件 / on_tick / 服务 / 管理页 / override / ui_hook）
  全都 `logger.exception`——只有工具这条静默，而这恰是作者最常用的入口。
- **修法**：`_dynamic` 的兜底 except 补 `logger.exception`；测试
  `test_play_runtime.py::test_dynamic_tool_error_is_logged`（断言有 ERROR 记录 + 带栈）。

### G55 加载失败只回滚注册表、不回滚世界写入——✅ 已修（v0.7.3，超时项另记）
- **现象**（实测）：世界包 `setup` 里 `create_map` + 2 个地块后抛错 → 地图与地块**留在库里**；
  重启重跑直接卡在"地图已存在"。更糟的是**按官方幂等写法（"地图存在即跳过"）的包
  会假装加载成功**，留下一张半成品世界。
- **同族**：`load_one` 只捕 `Exception` → 包顶层或 setup 里 `sys.exit(3)` 会穿透让**整个
  服务启动失败**；`setup` 无超时（`time.sleep(30)` 让启动挂住）。
- **✅ 已落地（v0.7.3）**：
  - **`api.import_bundle(map, locations=…, entities=…, world_id=…, folder_id=…)`**：
    地图 + 地块 + 实体 + 归属**一次 SQLite 提交**（复用 `store.save_map_bundle`），
    校验先于写入（报错消息带"第几行"），地图已存在即拒绝；失败路径显式
    `store.rollback()`（新增）——否则长连接上一条失败语句会留给**下一个 `_commit`
    一起提交**，"零落盘"就只是句口号
  - 引擎侧抽了 `_compose_entity`：`place_entity` 与 `import_bundle` 共用同一套
    "裸名解析 / `core:info` / `core:position` 折叠"规则（分散写早晚不一致）
  - **`SystemExit` 隔离**：`load_one` 单捕它 → 记"包内调用了 sys.exit(3)——已隔离为
    加载失败，服务继续"，其余包照常加载
  - 内置世界包 `worlditor_play_demo_world` 改为用它（41 地块 + 3 实体一次导入，
    连接与文案逐字不变，实测）；参考实现即文档
  - 测试：`tests/test_play_content_import.py` 8 条（全量落地 / 失败零落盘 / 已存在拒绝 /
    地块不存在 / 半截坐标 / 不在世界上 / 文案结构 / core: 守卫 / 单条事件）
- **仍缺（明确的边界）**：`setup` **没有超时**。同步 `setup` 里的 `time.sleep(30)`
  会**阻塞事件循环**，`asyncio.wait_for` 也打断不了——真要治得上线程/子进程执行
  `setup`，代价远超收益，故只记录不实现（文档已提示别在 setup 里做长阻塞的事）。

### G56 MCP 工具清单变化不通知客户端——✅ 已修（v0.7.3）
- **现象（修复前）**：SDK 报 `tools.listChanged: false`，且 `FastMCP.add_tool` 不发
  `notifications/tools/list_changed`——运行期装/启用玩法包后，**已连接的客户端看不到
  新工具**（`tools/list` 服务端已更新），要重连。`engine._sync_tool_add` 只刷新
  instructions（那份也只在新的 `initialize` 里下发）。
- **难点**：SDK 没有"按会话广播"的口子——`ServerSession` 是 `Server.run()` 里的**局部
  变量**，传输层只存 transport、不存 session。
- **✅ 落地**（两处**只补在本实例**上的包装，不动 SDK 类、不影响别的 FastMCP）：
  1. `create_initialization_options`：置 `tools_changed=True` → initialize 结果声明
     `tools.listChanged: true`（客户端认这条才会理我们的通知）；
  2. `run`：每次会话记下它的**出站流**；`engine._sync_tool_add` / `_sync_tool_remove`
     后广播 `notifications/tools/list_changed`（与 `ServerSession.send_notification`
     同一条路径，只是省了 session 对象）。
  广播是 **best-effort**：没有活跃会话 / 客户端没开 SSE 流时静默跳过（记 debug）。
  回归测试 `tests/test_mcp_tool_notifications.py` 3 条（进程内真会话：声明 +
  注册后收到通知 + 移除后收到通知 + 无会话空操作）。

### G57 重构遗留的死代码——✅ 已清（v0.7.3；本轮复核）
- `engine._package_states`（D44 换解析器后的孤儿）、`store.next_revision`（D28 单事务
  改造残留）、`identity.TOKEN_TIERS`（0 引用）、`engine.effective_fields_for`
  （"跨组件摊平"的最后一块，D41 就该删；用到它的那条断言改成 `fields_by_component`
  的分组断言）已于 v0.7.3 清理。
- 本轮继续删除 `WorlditorPlayAPI.register_ui_component`、`WorldEngine.register_ui_component`、
  `_ui_components` 及其卸载清理代码（原 G35 只写不读注册表）。
- 全仓库仍无 TODO/FIXME/HACK 标记；AST + grep 双证未发现其它可无损删除的运行时符号。

### G17 私有地图可见性：**已修**（本节更正 2026-09-24 的复核）
- `/scene` 现在走 `engine.can_observe_entity()`（`mcp/http.py:289`，不可观察 → 404），
  动作菜单带 `viewer_id` / `tier`；SSE 按订阅者过滤（`engine._push_to_subscribers`
  逐个 `map_visible_to`）；`/state` 仍只挡私有地图、**不挡隐身实体**（G12 尾巴，见 G12）。
- 因此 G17 正文里"四处缺口全部仍成立"与"`map_visible_to` 全仓唯一调用点仍是 `_state`"
  **已过期**（现为 3 个调用点：`/state`、SSE 推送、`can_observe_entity`）。

### G35 交互动作静默覆盖：**已修**（首条更正）
- `engine.register_interaction` 现在同名**报错拒绝**（`engine.py:1736`，
  "交互动作冲突：x（已由 pkg 注册）"，实测）。G35 首条"无冲突检查 → 后者静默顶掉前者"
  已过期；该条其余小项（`demo_world` 续跑分支、`_ui_components` 死注册表、
  注释里的 kind 口径）中，注释口径已在本轮统一，其余见 G35 原文与 G50/G51。

---

## 本轮审查新增暂缓项（无行为整改）

### G58 认证端点抗滥用：暂缓
- **范围**：登录、注册、agent 注册目前没有失败退避、速率限制、
  账户锁定（~~read-token 配额或 TTL~~：v0.9 已删除该端点）；不存在账户的登录路径也未做等成本密码校验。
- **原因**：这是公网安全策略与部署模型决策，不是无副作用修复；内存限流、代理限流、
  多 worker 共享状态和错误文案都需要先定口径。
- **触发条件**：准备公网长期运行、开放注册或接入不受信任用户时处理。建议方案：按用户名/IP
  失败计数与指数退避，统一认证错误文案，并补启动配置防呆。
- **当前缓解**：生产建议 `auth_mode=invite`，管理端口保持本机监听，并在反向代理增加限流。

### G59 玩法包间名字级契约：暂缓
- **范围**：组件键已有 namespace，但事件名、共享字段、KV key、UiBlock kind、工具名和服务
  参数仍主要依靠文档/约定，加载器只理解包级 `requires.plays`。
- **原因**：`provides/consumes` 会改变包元数据、加载校验、冲突与兼容策略，必须先选定声明
  粒度、版本规则和“悬空消费”是错误还是警告；当前首个玩法包可按 PLAY_DEV 约定开发。
- **触发条件**：出现多个真实包需要共享契约、或需要第三方生态兼容检查时处理。
- **建议方案**：在 `play.yaml` 声明 `provides` / `consumes`，加载期校验并在管理端展示归属与消费关系。

### G60 不可信玩法包隔离：暂缓
- **范围**：玩法包 Python 代码在服务进程内导入执行；同步 `setup()` 无可中断超时，包可影响进程
  资源与启动过程。
- **原因**：线程/子进程/独立 venv 或容器隔离都会改变部署模型和 API 语义，不能作为无副作用修复。
- **触发条件**：允许非管理员上传包、面向公共市场分发包、或需要不同依赖版本共存时处理。
- **当前口径**：玩法包安装等同于授予管理员代码执行权限；`setup()` 应避免阻塞，内容导入使用
  `import_bundle`；不同包依赖的 pip 版本必须由宿主环境统一管理。

### G61 世界模板激活过滤：暂缓（既有 G52）
- **范围**：实体模板列表目前不按调用者所在世界的激活玩法包过滤，只有全局包停用/卸载才改变可见性。
- **原因**：模板是管理/内容治理资源，是否属于世界能力面尚未定稿；直接过滤可能影响跨世界复用与管理端编辑。
- **触发条件**：真实玩法包需要按世界隔离模板，或管理端出现错误模板可见性问题时处理。
- **建议方案**：明确模板是全局资源还是世界资源；若按世界过滤，为 API 和管理端增加 caller/world 上下文并补回归测试。

### G62 跨包服务调用没有世界过滤（D45 之后从"观察"升级为"要处理"）
- **范围**：`call_service` 只查"服务存在 + 提供方已加载"（`engine.py:call_service`），**不看调用方所在世界**。
  而**激活是世界级**的（D15）：某世界没启用提供方，调用方照样调得到它的服务。
- **为什么现在要紧**：D45 之后"玩家包"天然是**中心件**（roster / 化身管理），
  而 `requires.plays` 是**全局包级**的（依赖未启用 → 依赖者加载失败；disable/uninstall 被依赖者挡住）。
  两个机制叠起来 = 玩家包成了单点故障，且跨世界串味。
- **当前缓解**（已写进 `docs/PLAY_DEV.md` §14）：**默认零依赖**（只读 `api.caller()`）；
  要"我的全部化身"才用 `list_services()` 探测 + `call_service` 软依赖；硬依赖只留给
  "没有玩家包就没有意义"的包。
- **建议方案**：`call_service` 补一道世界判定（提供方在该世界未启用 → 报错/回落），
  与工具面/原语面/视图面的口径统一。**属语义变更，需与包作者约定**（会打断"跨世界复用同一个包实例"的用法）。

### G63 `/state` 把所有人的 `core:account` 一起发出去
- **范围**：`/state` 的实体投影含全部组件，其中 `core:account.user_id` 是**账户 id**；
  任何能读 `/state` 的凭据都能看到**每个在场实体的账户 id**（v0.9 删除了 `read` 围观档，
  所以范围收窄到 `play` / `admin`，但"玩家能互相看到账户 id"这一点没变）；`/scene` 的 `peers` 同理。
- **为什么是问题**：账户 id 是管理端 `PATCH/DELETE /admin/accounts/{id}` 的路径参数——
  虽然那些端点另有 admin 校验（拿到 id 也不能越权），但它把"谁是谁"暴露给了所有人，
  而玩家端根本不需要这个字段（要判断"是不是人"只需布尔）。
- **建议方案**：`/state` / `/scene` 输出前把 `core:account` 投影成 `{"bound": true}`
  （或直接摘掉），管理端端点仍返回完整值。**属输出契约变更**，需前端与文档同步。
- **状态**：待决策（v0.8.0 审查发现，本轮未改——不在玩家模型方案范围内）

### G64 第一个玩法包（内置玩家包）落地清单：守卫迁移 / 夹具合一 / 文档表述

- **状态**：方向已定（DESIGN **D48**：玩家包内置、"玩家在地图上行动"留给第二个包），
  **内置化未开工**。⚠ 但**包本体已经存在**——`tests/fixtures/plays/worlditor_play_player/`
  （413 行 `main.py` + 165 行 `web/view.js`：五个工具 / 三个服务锚点 / `local:avatar` /
  kv 续玩 / `on_principal_deleted` / 落点策略 / 一个 `register_view("player")`）。
  所以这一步是**改造 + 迁移**，不是从零写；**要补的界面层清单**（抽屉入口 / `layout="fullscreen"` /
  底栏 / 属性页 / 返回按钮 / 改名）与**发布前必须冻结的四个名字**见
  `docs/PLAYER_PAGE_PLAN.md` §4。本条只登记"迁移时必须一起做"的东西——不做的话会出现
  "文档与守卫盯着另一个副本"，而且**不报错**。
- **迁移清单**：
  1. **源码只能有一份**：`tests/fixtures/plays/worlditor_play_player/` →
     `worlditor_mcp/builtin_plays/worlditor_play_player/`。夹具侧不再留副本：
     `tests/play_fixtures.py:471` 的 `install_player_play()` 现在是从夹具目录**复制**
     （`shutil.copytree`，`_REFERENCE_PLAYER` = 夹具路径）——改成复制内置目录即可，
     但**两份目录不能并存**（并存的结局是改了一份、跑的是另一份）。
  2. **两条守卫的扫描目标**（最容易漏的静默失守点）：
     `tests/test_web_view_styles.py:23` 与 `tests/test_version_consistency.py:50`
     都硬编码扫 `tests/fixtures/plays/*/web/*.js`——内置包的 `web/view.js` 必须进扫描集，
     否则"视图样式约定"与"版本串一致"两处**同时**不再覆盖玩家包。
  3. **文档表述**：`DESIGN.md` §0 一句话定位 / §1 架构图旁注 / §6 标题与正文 / §9 的 D31 行，
     加上 `README.md:8` 与 `README.md:144`——从"内置只剩世界内容包 ×1"改成
     "1 世界内容包 + 1 玩家包（D48）"；`docs/PLAY_DEV.md` §12"参考实现"一节要写清
     "内置玩家包"与"夹具参考包"的新关系（口径变化：仓库重新有了一个内置行为包，
     但它**是按玩法切的**，不是 D31 废弃的那种"一个内核机制一个包"）。
  4. **`uninstall` 语义**：内置包只可停用（`PlayLoader.uninstall` 已拒），
     管理端文案与 `PLAY_DEV` 要说清"内置包升级 = 随内核发版，不提供 zip 热更"。
  5. **版本串**：内置包的 `clientInfo.version` 与 `play.yaml` 的 `version` 随内核 bump
     （`test_version_consistency` 的口径是"扫到的组件版本必须等于 `worlditor_mcp.__version__`"）。
  6. **空安装体验**：内置玩家包上线后，全新安装的玩家端**终于有一个 tab**（G39 残留 #4 收敛）；
     顺带确认 G39 残留 #2 那句"仓库不再有内置官方玩法示例"要改口径。
  7. **`.gitignore` 的 `data/`（已修，v0.8.0）**：裸 `data/` 会**连带忽略包内的 `data/` 目录**，
     而 `data/` 正是 `PLAY_DEV` §2 约定的包内数据文件位置——参考玩家包的
     `data/spawn.json` 就这么被静默漏掉（`git add` 不报错，只是文件永远不在库里）。
     已把规则收紧为 `/data/`（只锚定根目录的运行时数据目录）；内置化时要再确认一遍
     `builtin_plays/<包>/data/*` 真的进了库。
- **前置（都属"开发之前"）**：
  - **惰性接管** —— ✅ 已随 v0.8.0 落地（`PLAY_DEV` §14.4 第 5 点 + 参考实现 `_resume()` +
    回归 `test_player_package.py::test_relogin_resumes_avatar_lazily`）。
  - **视图组件 `callTool` 样板** —— ❌ 未做：每个视图手抄 ~60 行会话管理、硬编码 `/world/mcp`
    （与 `VITE_WORLD_API` 独立域部署矛盾）、`_sessionId` 永不过期（会话失效只能整页刷新）——
    见 G36"玩法包视图硬编码 `/world/mcp`"那条。玩家包是第一个"真要用"的视图，建议同批处理。
- **顺带（不在本条范围）**：G62（`call_service` 无世界过滤 + `requires.plays` 全局）与
  G63（`/state` 泄露 `core:account.user_id`）——玩家包内置后更容易被别的包硬依赖，
  这两条的影响面会跟着变大（D48 的"默认零依赖"口径正是为了拖住这件事）。
- **界面层残留（登记在 `docs/PLAYER_PAGE_PLAN.md` §5，不在这里重复）**：
  **K-5** 未命中的 `ui_hook` 静默不触发、**K-10** 默认落地视图（Q-11 已明确 =
  进场流程，见 `PLAYER_PAGE_PLAN` §11）、**P7** 视图资源没有 `Cache-Control` / `ETag`。
  **前两条建议排在玩家包发布之前。**
- **已还的一笔（K-11）**：昵称字符校验（`core:info.name` 的长度 / 控制字符 / 双向文本）
  ✅ 已实现——`CoreComponent.validate` + 六个写入出入口，回归 `tests/test_display_name.py`。
  它之前是"文档说已定、代码里没有"，现已对齐。


