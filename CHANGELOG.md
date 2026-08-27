# Changelog

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
