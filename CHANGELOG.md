# Changelog

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
