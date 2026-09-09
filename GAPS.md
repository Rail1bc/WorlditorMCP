# worlditor 平台缺口清单

> 来源：M2 后玩法评估（朝向移动/快捷栏/养成/空战/自有世界拜访），逐玩法验证
> 基础结构是否优雅支持。每个条目记录：触发玩法、影响、建议方案、成本、状态。
> 状态约定：**待决策**（建议在 M3 前后处理）｜**增强候选**（等真实需求再定）｜
> **文档补充**（PLAY_DEV.md 规范）｜**观察**（暂不动）。

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
- **状态**：✅ 已解决（地图 visible 字段 + /state 在场过滤，admin 全见）

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

### G7 跨包编辑权限约定
- **触发**：自有世界玩法——玩法包 B 的编辑调用不自动过家的 ACL
- **方案**：PLAY_DEV.md 约定"编辑任何地图前先查其 ACL"；家玩法包提供
  "地图权限查询"API（读 home 记录）
- **说明**：符合 D14"内容治理责任归玩法包"，不做内核级强制（让内核认识
  "家"概念会违背纯平台定位）

---

## 观察（暂不动）

### G8 内核持有原语与 D8 的关系
- **现状**：v4 的 inventories 表 + give/take/count 原语仍在（D8 定稿
  "无 inventories 表"，M2 未清理）
- **影响**：玩法包自管背包时不可混用内核 give/take（双轨数据）；当前
  give/take 对"简单持有"场景可用
- **状态**：M3 后清理（按 D8）或保留为通用持有原语——届时决策

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
- **状态**：✅ 已解决（list_entities(viewer_id) 过滤 invisible/see_invisible，/scene 同步）

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
- **状态**：⏸ 暂缓（记录于 2026-09 审查，见审查报告 P0-2）

### G17 G1 可见性只实现了一端（/scene + SSE + 交互缺口）
- **触发**：全面审查——`/state` 按 `map_visible_to` 过滤（G1 已解决），但
  `/scene`（http.py:210-245）不检查——read 档持任意 entity_id 可读 private
  地图场景与动作菜单；SSE `_event_payload`（engine.py:1141-1179）对
  private 地图事件全量下发实体位置（play 档订阅可跟踪）；`interact` /
  `list_actions` 亦不做地图可见性检查
- **方案**：`/scene` 补 `map_visible_to` 过滤（~5 行）；SSE 订阅对象带
  订阅者身份按可见性过滤（~30 行接口变更，admin 全见）；interact 前置
  检查；各补 HTTP 级测试
- **状态**：⏸ 暂缓（记录于 2026-09 审查，见审查报告 P0-3）

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
- **状态**：观察（低危；改 3 个 js 文件，等视图组件整体清理时一并做）

---

## 观察（追加）

### G15 多世界激活未覆盖 MCP 工具与原语分派
- **触发**：多世界玩法评估（D15）——世界激活集合按实体所在世界过滤，
  但只落地于事件分发与交互通道；MCP 工具（register_tool）与原语
  override/过滤器（move 等）为全局生效：未激活包的工具在"其他世界"仍可调用
- **现状**：`engine._world_play_active` 仅被 `_emit`（事件）与
  `_interact_default`（交互）使用；`build_dynamic_tool` 与
  `_dispatch_primitive` 不做世界检查
- **影响**：每世界不同规则的多世界玩法下，工具面与行为规则无法按世界区分
  （单世界默认场景无影响）
- **方案**：MCP 工具 wrapper 在 handler 前按调用者实体所在世界检查激活
  （~10 行 + 测试）；原语分派按（世界, 原语）过滤语义需讨论——过滤器是
  "玩法包声明的规则"，跨世界是"不生效"还是"拒绝调用"待定
- **成本**：内核 10–30 行 + 测试；需先明确 `list_tools` 是否按调用者过滤
- **状态**：观察（等真实多世界需求再定）
