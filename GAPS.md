# worlditor 平台缺口清单

> 说明：本文件只记**未结**项与**设计存档**；已结项压缩为 §9 的一行索引
> （明细看 `CHANGELOG.md` 与 `git log -- GAPS.md`）。
> 状态约定：**待决策**｜**增强候选**｜**观察**｜**暂缓**｜**设计存档**
> 状态含义：待决策 = 方向未定；增强候选 = 等真实需求；观察 = 暂不动；
> 暂缓 = 等触发条件；设计存档 = 方案已记录、不排期。
>
> 来源：M2 后玩法评估（朝向移动 / 快捷栏 / 养成 / 空战 / 自有世界拜访），逐玩法验证
> 基础结构是否优雅支持；历史全文见 `git log -- GAPS.md`。
> 每个条目记录：触发玩法 / 影响 / 建议方案 / 成本 / 状态；本版对已结项只留结论。
>
> 编号提醒：本文的 `G1–G39` 是**本仓库缺口号**；`DESIGN.md` 正文里的 `（G2）`
> `（G3）`… 是**旧插件期**的另一套编号，同号不同义（见 DESIGN §9 编号说明）。

**目录**

- §0 当前未结（先看表）
- §1 待做
- §2 观察 / 增强候选
- §3 设计存档（不排期）
- §9 已结项索引

---

## 0. 当前未结（先看这张表）

> 本表只列仍在跟进的事项；完整正文见 §1–§3，已结项见 §9。查“当时怎么想的”
> 用 `git log -- GAPS.md` 或 `CHANGELOG.md`。设计存档（不排期）：G41、G44、G45，见 §3。
> 图例：✅ 已结（正文在 §9）；⏸ 暂缓；📌 已记录；🔴 必修（历史）。
>
> **索引行里标注的未闭合边界**（不单列条目，详见 §9）：
> - G12：`/state` 全量快照仍未走隐身过滤（修法：传 `viewer_id`）。
> - G42：地块索引的公开自检命令未补。
> - G53：`install_zip` 仍无体积 / 条目数 / 解压比上限。
> - G55：`setup()` 仍无超时（同步阻塞无法打断）。

| # | 事项 | 状态 | 详见 |
|---|---|---|---|
| **G64** | 内置玩家包：已内置（v0.9.4）；剩余界面层 + 新设计 | 迁移已结，新工作见包内 `DESIGN.md` | §1 + `worlditor_mcp/builtin_plays/worlditor_play_player/DESIGN.md` |
| K-10 | 视图 `landing` 默认落地 | 未做；Q-11 已定为「进场流程」（归玩家包设计） | 包内 `DESIGN.md` §5 / §11 |
| G62 | `call_service` 没有世界过滤 | **要处理**（语义变更，等第二个包） | §1 |
| G63 | `/state` 把所有人的 `core:account.user_id` 发出去 | 待决策 | §1 |
| **G65** | 跨包组件写被拦死（D43 第 3 条）：互操作只能退到无主的 `local:` | 待决策（方向倾向"写开放、声明收紧"） | §1 |
| G36 | 编辑器 / 前端可用性清单 | 部分已修（`PlayPageHost` 两项）；其余抽查仍成立（监听清理、localStorage、`/world/mcp` 硬编码、lint 失败伪装） | §1 |
| G37 | 工程 / 流程：CI 比对已提交的 `dist`、浏览器 E2E 入库、Python 3.10 真跑 | 未做 | §1 |
| G26 | 管理端健壮性收尾 | 部分已修 | §1 |
| G52 / G61 | 实体模板按世界激活过滤 | 待做 / 暂缓 | §1 |
| G23 | 文件夹多选 / 复制 | 唯一残留（撤销重做已明确不做，D24） | §1 |
| G16 / G58 | 认证端点抗滥用（退避 / 限流 / 等成本校验） | ⏸ 暂缓（同一件事的两条记录） | §2 |
| G59 | 玩法包间名字级契约（`provides` / `consumes`） | ⏸ 暂缓 | §2 |
| G60 | 不可信玩法包隔离 | ⏸ 暂缓 | §2 |
| G25 / G27 | 世界包更新语义 / 管理页守卫 | 待决策 | §1 |
| G3 / G5 / G9 / G10 | tick 粒度 / `spawn_task` / instructions 片段 / resources·prompts | 观察 / 增强候选，等真实需求 | §2 |

---

## 1. 待做

> 本节 12 条：G64 已完成内置（剩余界面层 / 新设计）；G62 / G63 / G65 属语义与写权限边界；
> G36 / G37 / G26 属可用性与工程收尾；G52 / G61、G23、G27、G25 属模板 / 治理待决策。

**已内置：玩家包（D48）**

### G64 内置玩家包：迁移已结，剩余界面层与新设计

- **状态**：✅ **v0.9.4 已内置**——包本体在 `worlditor_mcp/builtin_plays/worlditor_play_player/`
  （`play.yaml` / `main.py` / `data/` / `web/` + 包内 `README.md` 契约 + `DESIGN.md` 设计 +
  `tests/test_player.py`）。**内容、测试、文档都归包目录**，框架侧只留指针。
- **已完成的迁移**（原先登记的"迁移时必须一起做"，现已逐条落地）：
  1. 源码只剩一份：夹具副本与 `install_player_play()` 已删除。
  2. 两条守卫已改扫内置目录：`test_web_view_styles` / `test_version_consistency`。
  3. 文档口径：`DESIGN` §0/§1/§6/§9 与 `README` 改为"内置 2 个包"；`PLAY_DEV` §12 更新描述、
     §14 只留指针（契约搬进包内 `README.md`）。
  4. `uninstall` 语义不变（内置包只可停用）；`clientInfo.version` 随内核版本对齐。
  5. `.gitignore` 的 `/data/` 收紧后，包内 `data/spawn.json` 确认入库。
- **剩余（不属迁移，另记在包内 `DESIGN.md`）**：
  - **界面层**：抽屉入口 / `layout="fullscreen"`「我」/ 底栏 / 属性页 / 返回 / 改名。
  - **新设计**：1 主体 1 化身、幂等 create、离线上线（`_dynamic` 打点 + `on_tick` 扫描 +
    `move` 过滤器）、出生点 / 上次位置、删除多化身面。
  - **K-10**（视图 `landing`）见 §0 与包内 `DESIGN.md` §5 / §11。
- **顺带（不在本条范围）**：G62 / G63——玩家包内置后更容易被别的包硬依赖，影响面变大。

**语义 / 安全待处理**

### G62 跨包服务调用没有世界过滤（D45 之后从"观察"升级为"要处理"）
- **范围**：`call_service` 只查"服务存在 + 提供方已加载"（`engine.py:call_service`），**不看调用方所在世界**。
  而**激活是世界级**的（D15）：某世界没启用提供方，调用方照样调得到它的服务。
- **为什么现在要紧**：D45 之后"玩家包"天然是**中心件**（roster / 化身管理），
  而 `requires.plays` 是**全局包级**的（依赖未启用 → 依赖者加载失败；disable/uninstall 被依赖者挡住）。
  两个机制叠起来 = 玩家包成了单点故障，且跨世界串味。
- **当前缓解**（已写进内置玩家包的 `README.md`）：**默认零依赖**（只读 `api.caller()`）；
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

### G65 跨包组件写被拦死（D43 第 3 条）：互操作只能退到无主的 `local:`
- **范围**：`_guard_component`（`world/play/api.py`）对 `source not in (local, 自己的 play_id)`
  一律报错，**8 个写入入口共用**：组件三原语（`add/set/remove_component`）、字段三原语、
  `place_entity(components=…)`、`import_bundle(entities[].components)`。
- **为什么现在要紧**：内容包需要**预置别的包声明的组件**——例：世界内容里的「出生点」实体
  带 `worlditor_play_player:spawn`，现在写不进；于是**唯一能写的公共命名空间是 `local:`**，
  而它没有主人、没有卸载语义、在四象限里被归为"虚构组件"。
  **现行规则等于逼所有跨包对接放弃归属去换写权限**，与 D44"归属的唯一事实来源就是键"相悖。
- **为什么不是"开个条件口子"**：`requires.plays` 是**硬依赖**（加载拓扑 / 启用自动带依赖 /
  卸载被依赖者挡住），把写权限挂在它上面 = 内容包为一个组件硬依赖行为包，且卸载行为包会被
  内容包挡住——比直接允许更重。
- **提议方案（2026-10-18 讨论，未拍板）——写开放、声明收紧**：
  - `core:` 照旧按 K-7 表拦（位置 / 账户 / 感知是协议不变量，不是耦合问题）；
  - `declare_component` 仍限自己的 `play_id:` 或 `local:`（"谁声明，谁回答这个组件是什么意思"）；
  - `add_tag_fields` 保留（解决"字段要可见"，不是"数据能不能写"）；
  - 拼错不再当场报错 → 写"非 `local:` 且当前无包声明"的键时记一次 warning（每个
    `(包, 键)` 一次），其余交给已有的四象限诊断（orphan / fictional 本来就会显示）。
    **观测，不判定**（同 K-5 口径）。
- **代价（如实记）**：①拼错从"立即报错"变成"诊断可见"，晚一步发现；②跨包耦合"代码看得见、
  契约上看不见"——文档要求跨包写留一行注释说明依赖；③整块 `set_component` 可覆盖对方的键
  （代码评审问题，不是机制问题）。
- **成本**：`_guard_component` 一处 + `tests/test_v2_components.py` 那条反转 + `DESIGN` D57 +
  `PLAY_DEV` 三处口径，约 30 行。**若落地，包内 `DESIGN.md` §11.3 ② 的"内容包预置出生点"
  随之解锁**（玩家包没装时该组件显示为 orphan，可观测的失败）。
- **状态**：**待决策**（2026-10-18 讨论，方向倾向"放开"；未落地）

**可用性与工程收尾**

### G36 编辑器 / 前端可用性清单（审计逐条给了 file:line）

- **网格按包围盒稠密渲染、无上限**（`MapGrid.vue` 双层循环）：坐标框允许输入任意
  值，建完 (0,0) 再输 (5000,5000) ⇒ 2500 万按钮，浏览器冻死。修法：加渲染上限
  （超出提示"缩放/平移查看"）或虚拟滚动。
- ✅ **已修**：~~玩法包管理页切换不重载组件~~——`PlayPageHost.vue` 现在
  `watch([playId, pageKey], load)` 并在加载前清空上一个 `comp`，用 `loadSeq` 丢弃过期结果。
- **`addEventListener` 不清理**：`MapEditorPage.vue`、`AdminPanel.vue` 仍无
  `onUnmounted`（`PlayPageHost.vue` / `MapGrid.vue` 已正确清理）→ 组件卸载后旧闭包常驻。
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
  无 `role="dialog"`；~~`admin-items.js` 的 attrs 只校验"是合法 JSON"~~
  （该文件已随 D31 删除，样本改为 `admin-shop.js`——**它自己用 `window.prompt`**，见 G27）。
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

### G26 管理端健壮性收尾项（`docs/archive/CORE_AUDIT.md` §4 未处置）

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
  - `PUBLIC_PATHS` 用带 `/` 边界的 `startswith` 匹配（`http.py:124`）：`/auth/login/xxx`
    这类子路径会**免认证**——将来新增同名子路径有误放行风险；是否收紧（精确匹配 +
    显式子路径白名单）待定
  - ✅ **已修（v0.7.0）**：`/plays/{play_id}/web` 前缀校验用字符串 `startswith` 时，
    `<pkg>/web-evil/x.js` 会被判为"在 web/ 之内"。改为 `Path.is_relative_to`
    （与 PlayLoader 的路径安全检查同语义）；回归测试 `test_play_web_rejects_web_prefix_sibling`
  - `?token=` 会进访问日志（SSE 的硬需求，不能删）——**已在 `HTTP_API.md` §4 文档化**
    并建议反代过滤（不再作为缺陷）
  - ✅ **已修（v0.7.3）**：停用玩法包不清理 `sys.modules` 残留——`PlayLoader._forget_modules`
    现在连同子模块一起清（`play/__init__.py`），"改代码 → 停用 → 启用"能拿到新代码
  - **局部更新语义不完整**（v0.5.2 审计补充）：
    - ~~`PATCH /admin/maps/{id}` 只给 `spawn_row` 会把 `spawn_col` 重置为 0~~
      → **✅ 随 D45 消失**（v0.8.0：出生点两个字段整体删除，不再有这对参数）
    - `POST /admin/connections` 的 `enabled`/`paths` 实际都是必填（`admin.py` 恒传
      `data.get(...)`，缺省 None 被当"显式给值"）→ 只改一个方向不可行
    - `POST /admin/locations`（upsert）不带 `description` 会**清空**整段分时段描述
- **状态**：大部分已修（v0.7.0 修掉 `int()` → 400、`HTTPException` 统一 JSON、
  `/plays/*/web` 路径校验；v0.7.3 修掉 `sys.modules` 残留；`?token=` 已文档化）。
  **仍留**：`PUBLIC_PATHS` 的边界面收不收窄、以及"局部更新语义"两条（现在是
  **已文档化的契约**，不是静默行为——`HTTP_API.md` 写明了 connections 两字段必填、
  locations 缺 `description` 即清空）
- **另（v0.7.0 审查补充）**：JSON-RPC **批处理请求**原先整段不注入身份
  （`http.py:_inject_identity` 的 `isinstance(obj, dict)` 判定），持合法 play
  凭据发批量 `tools/call` 会被判"未认证"且**静默失败**——已修，
  回归测试 `test_inject_identity_handles_batch_requests`

**模板 / 治理 / 待决策**

### G52 实体模板未按世界激活过滤——待做（文档已纠正）
- **现象**：`engine.list_templates(scope)` 只有 scope 参数；`PLAY_DEV` §3 的"世界激活"
  表里曾写"实体模板不出现在管理端模板列表"（未实现）。只有**整包停用/卸载**才消失。
- **方案**：`list_templates` 加调用者世界 + 激活集合过滤（与 `/views` 同口径），或把
  文档口径改成"模板不分世界"。

> 另见 G61 暂缓记录（同一件事的暂缓版本；模板是否属于世界能力面尚未定稿）。

### G61 世界模板激活过滤：暂缓（既有 G52）
- **范围**：实体模板列表目前不按调用者所在世界的激活玩法包过滤，只有全局包停用/卸载才改变可见性。
- **原因**：模板是管理/内容治理资源，是否属于世界能力面尚未定稿；直接过滤可能影响跨世界复用与管理端编辑。
- **触发条件**：真实玩法包需要按世界隔离模板，或管理端出现错误模板可见性问题时处理。
- **建议方案**：明确模板是全局资源还是世界资源；若按世界过滤，为 API 和管理端增加 caller/world 上下文并补回归测试。

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

### G27 玩法包管理页组件逃过前端守卫（原生 confirm + 样式守卫盲区）

- **触发**：v0.5.1 前端审计——`worlditor_play_items/web/admin-items.js:118` 用了
  **原生 `confirm()`**（该文件已随 D31 删除），违反 D17"管理端禁用原生
  confirm/prompt/alert"（iframe/沙箱下被浏览器屏蔽 → 删除操作**静默失效**）
- **现在仍在犯**：参考实现 `tests/fixtures/plays/worlditor_play_demo/web/admin-shop.js:56`
  用 `window.prompt("新价格", …)` 改价——而它是 `PLAY_DEV` §12 让人照抄的样本
- **根因**：守卫 `tests/test_web_view_styles.py::test_admin_pages_use_no_native_dialogs`
  只扫 `webui/src`，且 `_view_component_files()` 显式排除 `admin-*.js`
  （`test_web_view_styles.py:66-72`）——管理页组件不在防线内
- **方案**：① 组件协议扩展——加载器把内核的 `askConfirm` 作为第三个注入参数
  （`new Function("Vue","UiBlock","askConfirm", code)`，DESIGN §4.6 修订）；
  ② 守卫扩到玩法包组件目录（v0.7.0 起为 `tests/fixtures/plays/*/web/*.js`，
  含 admin-*），样式类契约另行放宽；
  ③ 短期可让管理页组件自带行内确认（状态 + 两个按钮）
- **状态**：待决策（等下一次管理页组件改动一并做；**参考实现自己还踩着这条**，
  所以不是"将来可能出现"，是"照抄就会错"）

### G25 世界包的内容更新语义

- **触发**：`docs/archive/CORE_AUDIT.md` §4 记录但**只有该文档记着**（GAPS/DESIGN 无条目）
- **现状**：`worlditor_play_demo_world` 的 `setup()` 是"地图已存在则整体跳过"
  （`main.py:40-41`，不覆盖用户改动）；包升级新增了地块/实体也**不会**补进已有世界
- **方案**：世界包版本化 + 差异合并（新增子图 / 按 id 补地块 / 只补不改）；
  或显式"重新导入（覆盖）"高级操作 + 备份提示
- **成本**：中等（要定义合并规则与冲突策略）
- **状态**：待决策（等第一个"世界包要迭代内容"的真实需求）

---

## 2. 观察 / 增强候选

> 本节 8 条：G3 / G5 为增强候选，G9 / G10 为观察，G16 / G58、G59、G60 为暂缓；
> 均等触发条件再排期。

**增强候选**

### G3 tick 粒度 1s 硬编码
- **触发**：空战玩法——需要亚秒级状态推进（0.1s 帧），当前
  `TICK_GRANULARITY_SECONDS = 1.0` 硬编码，on_tick 最细 1s
- **方案**：粒度参数化（如 `WORLDITOR_TICK_GRANULARITY`，interval 语义不变，
  各 handler 各自间隔，仅调度检查更细）
- **成本**：~10 行，零语义破坏
- **状态**：等第二个需要高频的玩法出现再定（KISS：一个玩法不轻易动内核）
- **当前绕道**：玩法包自管 asyncio task 循环（见 G5）

### G5 玩法包后台任务生命周期约定
- **触发**：空战等高频玩法——玩法包自管 asyncio task 无官方注册/清理约定
- **方案**：PLAY_DEV.md 规范：自管 task 必须在 teardown(api) 中取消；
  可选内核提供 `api.spawn_task(coro)` 托管（生命周期随包卸载自动取消）
- **成本**：文档 0 行；spawn_task ~15 行
- **状态**：文档已落地（DESIGN §2.4 并发模型 + PLAY_DEV §11——handler
  锁内执行、任务级重入、子任务禁止调引擎 API）；spawn_task 等真实需求

**观察**

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

**暂缓（等触发条件）**

> G16 / G58 是同一件事的两条记录（原始审查正文 + 暂缓摘要），保留原文。

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

---

## 3. 设计存档（不排期）

> 本节 3 条：G41 多格占位、G44 阻挡组件、G45 物品堆叠；均不排期。三条都保留了
> 原始方案与取舍，重启时先看状态行，再核对 DESIGN 对应决策是否仍有效。

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

---

## 9. 已结项索引

> 已结项不再保留正文；下表按编号排序，一行一条。明细见 `CHANGELOG.md` 与
> `git log -- GAPS.md`；索引行只保留结论、关键 API / 版本号，不再重复 `file:line`。
>
> **未编号的本轮核心修复**（旧版“已解决（本轮核心审查修复）”压缩）：
> - 复合地图移动、复制、删除及创建时归属收束到单事务提交；
> - 复制事务失败回滚已有回归测试；私有场景授权、玩法查询快照与邀请码原子消费已落地；
> - 人类与 agent 注册的实体、账户、token、邀请码消费支持单事务 bundle。
> - v0.9.3：K-5 钩子命中可观测（`list_ui_hooks` / `/admin/ui-hooks`）、
>   P7 视图资源 `ETag` + 304、原生弹窗守卫扩到玩法包。

| 编号 | 事项 | 结论与落点 |
|---|---|---|
| G1 | 地图可见性 | ✅ `/state` 按 `map_visible_to` 过滤；G17 补齐 `/scene`、SSE、交互 |
| G2 | `delete_map` 缺失 | ✅ `engine.delete_map` + play API + admin DELETE 端点 |
| G4 | 自定义组件视图的跨包 UI 注入 | ✅ UiBlock 路径闭环（G18）；`<slot>` 注入否决（D52） |
| G6 | 跨包字段 / 事件命名契约 | ✅ `PLAY_DEV` §11 命名表；v0.7.0/D31 载体包废弃 |
| G7 | 跨包编辑权限约定 | ✅ `PLAY_DEV` §11：编辑前先查 ACL，内核不强制 |
| G8 | 内核持有原语与 D8 | ✅ M2 删除 inventories 与 give/take/count |
| G11 | 工具参数缺少数组类型 | ✅ `_TYPE_MAP` 加 array → `list[str]`（FastMCP schema） |
| G12 | 可见性过滤（隐身） | ✅ `list_entities(viewer_id)` 过滤隐身；尾巴：`/state` 未接 |
| G13 | 效果协调模式 | ✅ 由 G14 通用过滤器链取代，已关闭 |
| G14 | 通用原语过滤器链 | ✅ 5 个可覆盖原语支持过滤器链（否决 / 改写 / 短路） |
| G15 | 多世界激活未覆盖工具与原语 | ✅ v0.3.0：工具 / 原语 / kind / 视图 / ui_hook / 事件按世界过滤 |
| G17 | G1 可见性另一端（/scene + SSE + 交互） | ✅ `/scene` 走 `can_observe_entity`；SSE 按订阅者；菜单带 viewer |
| G18 | ui_hook 未接线 | ✅ `engine._interact_default` 接线 + 端到端测试 |
| G19 | 包裹覆（play_id 覆盖）机制 | 已失效（v0.7.0/D31）；机制仍在，重引入时再正式化 |
| G20 | 内置包视图内联浅色样式 | ✅ 改用 `wt-*` 类 / CSS 变量；守卫 `test_web_view_styles.py` |
| G21 | 实体声明体系：类型 / 模板 / 标签 | ✅ v0.5.0：`tags[]` + 隐式同名标签 + 能力并集（D18–D21） |
| G22 | 地图编辑器增强 | ✅ v0.5.0：多选 / 复制、`move_location`、diff 预览；撤销不做（D24） |
| G24 | 连接编辑器静默损坏地图 | ✅ v0.5.0 `MapEditorPage` 结构化出口 + diff 预览（D23）；尾巴见 G28/G29 |
| G28 | 文案格式双轨 | ✅ v0.5.2 只收结构化对象；非法 / 纯文本报错（`test_text_schedule.py`） |
| G29 | 实体数据 JSON 写坏清空 | ✅ v0.5.2 `FieldForm` 解析失败不落盘，错误移出折叠区 |
| G30 | 复制地图丢 `tags` | ✅ `copy_map` 副本带 `tags=list(e.tags)` |
| G31 | 物品定义生命周期 | ✅ v0.5.2 `save_item_def` 保留用户数据；物品已随 D37 移除 |
| G32 | `async def teardown` 不被 await | ✅ v0.5.2 `inspect.isawaitable` 时 await |
| G33 | `/views` 世界过滤失效 | ✅ v0.5.2 `http.py` 公共路径仍解析 token，`/views` 按世界过滤 |
| G34 | 编辑器删格 / 空图异常 | ✅ v0.5.2 `MapEditorPage` 保留具体坐标、删格后原地重建 |
| G35 | 内核 / 内置包的小口子 | ✅ 交互同名报错；`demo_world` 幂等；items 包废弃；`_ui_components` 删除 |
| G38 | 实体查询与调度 | ✅ v0.6.0：`query_entities`、事件 phase、revision（D26–D30） |
| G39 | 内置行为玩法包废弃 | ✅ v0.7.0/D31 删 6 个内置包；名字级契约仍缺 → G59 |
| G40 | 实体模型 v2（总条目） | ✅ v0.7.1：D32–D40 落地；D41–D44 见 G47/G48 |
| G42 | 地块 → 实体 id 索引 | ✅ `store.entities_at` 内存索引；公开自检命令未补 |
| G43 | 渲染 / 观察方式 | ✅ D40：内核不做通用渲染 / 组件端点；观察归玩法 |
| G46 | 通用实体管理页 | ✅ v0.7.1：`GET /admin/entities` + 全部实体页 |
| G47 | 能力组件命名（kind / tags 折叠） | ✅ D41–D43：能力带 source、kind 删除、`local:` 共享 |
| G48 | 组件四象限诊断与孤儿清理 | ✅ D44：`diagnose_components` / `purge_components`；前端两栏 |
| G49 | 卸载不删 `play_data` | ✅ 文档改为“卸载只删包目录”；KV / 组件保留；清库待需求 |
| G50 | 玩法包只能单文件 | ✅ v0.7.3：`play/__init__.py` 用 `spec_from_file_location` |
| G51 | 只读接口是浅只读 | ✅ v0.7.3：API 只读出口 `copy.deepcopy`；`list_actions` 透传 viewer |
| G53 | 安装一致性三连洞 | ✅ v0.7.3：校验 play_id / 目录名 / 前缀 / 同名；zip 上限仍缺 |
| G54 | MCP 工具 handler 异常静默 | ✅ v0.7.3：`mcp/__init__.py` 兜底 `logger.exception` |
| G55 | 加载失败只回滚注册表 | ✅ v0.7.3：`import_bundle` 单事务回滚；`SystemExit` 隔离；`setup` 无超时 |
| G56 | MCP 工具清单变化不通知 | ✅ v0.7.3：`tools.listChanged` + `list_changed` 广播 |
| G57 | 重构遗留的死代码 | ✅ v0.7.3：清 `_package_states`、`next_revision`、`TOKEN_TIERS` 等 |

> 共 42 条索引；22 条未结 / 存档正文见 §1–§3。想找某个版本：搜版本号（如 `v0.7.3`）；
> 想看完整推理与 `file:line`：用 `git log -p -- GAPS.md` 找旧版对应段落。
