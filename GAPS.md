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
- **状态**：待决策（对该玩法几乎必需）

### G2 delete_map 缺失
- **触发**：自有世界玩法——家地图生命周期需要删除，但 engine 只有
  create_map/update_map/assign_map，无 delete_map
- **方案**：补 `delete_map(map_id)`：级联删地块+实体+世界归属，身份化实体
  在场保护（同 delete_location 语义）；进玩法包 API（D14 范围"地图"本含删除）
- **成本**：~20 行 + 测试
- **状态**：待决策

### G11 工具参数缺少数组类型
- **触发**：多玩家互动玩法——子集选取（`targets: [eid1, eid2]`）和 AOE 类
  多目标操作需要数组参数，当前 register_tool 参数类型仅
  string/integer/number/boolean（G2 定稿）
- **方案**：`_TYPE_MAP` 加 "array" → `list[str]` 映射 + 校验放行（FastMCP
  原生生成 array schema，pydantic List[str] 支持）；玩法包侧参数为列表
- **成本**：~5 行 + 测试
- **状态**：待决策（多玩家是核心场景，数组参数几乎必然用到）

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
- **状态**：UiBlock 路径先行（世界视图 = UiBlock + ui_hook 注入）；表达力
  不足时再上插槽机制
- **当前绕道**：世界视图用 UiBlock 构建；或各包独立视图 + goto_view 跳转

### G5 玩法包后台任务生命周期约定
- **触发**：空战等高频玩法——玩法包自管 asyncio task 无官方注册/清理约定
- **方案**：PLAY_DEV.md 规范：自管 task 必须在 teardown(api) 中取消；
  可选内核提供 `api.spawn_task(coro)` 托管（生命周期随包卸载自动取消）
- **成本**：文档 0 行；spawn_task ~15 行
- **状态**：文档先，spawn_task 等需求

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
