# Changelog

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
