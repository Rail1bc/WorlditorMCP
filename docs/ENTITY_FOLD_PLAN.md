# 能力面折叠（v2 第 2 期）施工计划与交接

> **给新会话 / 新 agent 看的**：读完这一份 + 它指向的权威章节，就能接着干。
> **权威顺序**：`DESIGN.md`（决策，唯一权威）> `GAPS.md`（缺口清单）> 本文件（施工计划）。
> 本文件**不定义任何规则**，只回答三件事：**做到哪了、接下来做什么、哪些坑已经踩过**。
> 规则一律以 `DESIGN` **D41–D44 + §12.6 + §12.0** 为准。

---

## 0. 30 秒状态（2026-10-14）

- **HEAD = `5ed79e2` = `origin/main`**，工作树**干净**，**338 测试全绿**，ruff / format / 中文 UTF-8 审计全过
- **已完成**：
  - `D41–D44` 决策入册（本轮讨论的产物，含 G47 结案、G48 记档）
  - **D42 身份概念移除**（代码 + 测试 + 文档）
  - **D43 组件命名空间即写入边界**（代码 + 测试 + 文档）
- **当前**：**第 2 期（D41–D44 + 前端）全部落地**（`b632373` / `38a0be9` / `8d152d5` + D44 提交；全量 349 绿、`npm run build` 通过）。**破坏性变更已就绪，部署侧需删 `world.db` 重来（D13）**；版本 bump 与 tag 由用户决定
- **铁律**（三次都写进了 DESIGN，别绕）：
  1. **DESIGN 是唯一权威**——改行为先改决策，别让代码与文档打架
  2. **一步做到位**：不设"能力仍存表列、只是键变全名"的中间态（§12.0 已明确放弃 2a/2b 切分）
  3. **D13 无迁移**：表结构变更 = 删数据目录下的 `world.db` 重来（不写迁移、不留兼容分支）

---

## 1. 目标终态（实现完长什么样）

```python
Entity(
    id="9f2c1a4b…",
    components={
        "core:info":                    {"name": "野狼"},          # 名字（内核文案）
        "core:position":                {"map_id": "default", "row": 0, "col": 0},
        "worlditor_play_bestiary:stat": {"hp": 30},                # 能力 + 数据在同一个组件里
        "local:随手写的":                {"随便": 1},                # 虚构组件：允许、不贡献能力
    },
    revision=1638, changed_tick=412,
)
```

| | 今天 | 终态 |
|---|---|---|
| 落库列 | 7 列（含 `kind` / `tags_json`） | **4 列**（`id` / `components_json` / `revision` / `changed_tick`），表 **v11** |
| `to_dict()` | 7 键 | **5 键**（去掉 `kind` / `tags`） |
| 能力 | 裸名 `kind` + `tags[]`（与组件是两个平行世界） | **就是组件键的存在** |
| 声明 API | `register_entity_kind` + `register_entity_tag` 两套 | **一套**"声明一个组件"（旧名留别名） |
| 字段清单 | 跨组件摊平 + 顺序覆盖 | **按组件分组**；**同一组件内同名字段声明两次 → 报错** |
| 字段的"家" | 前端 `homeOf` **猜** | 声明它的组件就是家（猜的逻辑删掉） |
| 分类字段 | `add_category_fields` | **删除**（`categories` 作为**选取分组**保留） |

**规则全文见 `DESIGN.md`**：D41（折叠）/ D42（身份移除，**已完成**）/ D43（写入边界，**已完成**）/
D44（卸载与清理语义）+ §12.6（折叠后的规则汇总）+ §12.0（分期表）。

---

## 2. 待做的四块（按顺序；每块结束都要"全绿 + 文档同步 + 提交推送"）

### D41-a 声明带 source + 裸名解析层

**做什么**：

1. `register_entity_kind` / `register_entity_tag` / `register_entity_type` → 合并为**一个**
   "声明一个组件"的 API（**旧名保留为别名**，旧调用点零改动）；注册时 **source 自动取调用者的
   `play_id`**（`WorlditorPlayAPI` 知道自己的 id；内核/测试直接调 engine 且 `play_id=""` →
   落 `local`）。于是 `register_entity_kind("merchant", …)` 注册出的是 `<play_id>:merchant`
2. 注册表改成**按组件键**索引（`_tag_specs` 的键从裸名 → `source:name`）；
   `TagSpec.tag` 建议改名 `key`，`source` 从键里派生（`key.split(":", 1)[0]`）
3. **裸名解析层**（A2 规则，见 DESIGN D41）：唯一声明者 → `<那个包>:<名>`；
   无人声明 → `local:<名>`；**多个声明者 → 报错**；解析不出来 → **报错**（**不静默落 `local:`**）
4. 解析插在**只有 3 处**的裸名承载点（实测确认）：
   - `_entity_specs()` —— 能力并集（`engine.py`，`_tag_specs.get(tag)`）
   - `_live_tags()` —— `query_entities` 的标签匹配（用 `_tag_owner`）
   - `capabilities()` —— 诊断（`active_tags` / `inactive_tags` / `unknown_tags`）
   - 另有 `list_kinds()`（名词表，给管理端）
5. **归属进名字**：`_tag_owner` 那张表可以删（归属变成键里的结构信息）——但注意
   `_live_tags` 目前靠它区分"有主但不活跃"，替换后语义见 D44 四象限
6. `kind` / `tags` 的值也要跟着改：实体上的能力要么是**全名**（过渡期），要么（D41-b 之后）
   直接就是组件键。**注意**：实体上的数据一旦变全名，`test_entity_tags.py` 里大量
   `assert e.tags == ["b", "a"]` 这类断言要跟着改

**预期影响面**（实测数字，见 §3）：内核 + 约 250 处测试断言。**这是本块的主要工作量。**

**做完的验收**：`place_entity(tags=["merchant"])` 在有唯一声明者时落 `<pkg>:merchant`；
两个包各声明 `merchant` 时裸名输入**报错**；`capabilities()` 与 `query_entities` 的判定一致。

### D41-b 能力搬进组件 + 删两列（表 v11）

> **状态：✅ 已落地**（代码 + 测试 + 文档）。实现时定下的口径见 `DESIGN.md` §12.6 的
> "落地补充"：`Entity` 去掉 `kind` / `tags`（判断能力用 `has_component`）、`place_entity`
> 的 `kind` / `tags` 降级为写入便利、`update_entity` 不再有这两个参数、
> `last_active_ts` 改为**只在内存**（表正好 4 列）、`/admin/kinds` 只剩一张组件清单。

1. **能力 = 组件的存在**：实体带某能力 = 带某组件键（纯能力组件 = 数据 `{}`）。
   `kind` / `tags` 两列**删除**，`to_dict()` 收成 5 键
2. `store.py`：DDL → 4 列；`SCHEMA_VERSION` → `"11"`；`_FORBIDDEN_COLUMNS` 扩到
   `kind` / `tags_json`（沿 v9/v10 的既有做法：**旧库拒绝启动**）
3. **删跨组件摊平**：`effective_fields_for(多个标签)` / `_merge_fields` 的去重与顺序覆盖
   → 改为**按组件分组**的字段清单；`capabilities()["fields"]` 语义同步
4. **删分类字段**：`add_category_fields` / `_category_fields`（`categories` 作为选取分组保留）
5. **同一组件内同名字段声明两次 → 报错**（新增的唯一规则）
6. `admin.py` / `mcp/http.py` 的实体投影、`/admin/kinds` 名词表的字段名都要跟着改
7. 前端（可单独一块做，见下）

### D44 / G48 四象限诊断 + 孤儿清理（顺带修 C8）

- **四象限**：`active` / `inactive`（世界没启用）/ **`orphan`**（source 那个包没加载或已卸载）
  / `fictional`（`local:` 或从未声明——**本来就没有行为，不是坏了**）
- **顺手修 C8**：今天停用包时 `clear_play_registrations(purge=False)` **把规格也删了** →
  `capabilities()` 报 `unknown_tags`（"未声明"）而 `_live_tags()` 仍认为"有主但不活跃"。
  修法：**停用不删规格**，改由 `capabilities()` 多看一条"该包是否已加载"
- **两个端点**：
  - `GET /admin/orphan-components`（或并入 `/admin/plays` 响应）：按 source 分组
    `{source, state, entities, keys, sample}`
  - `POST /admin/orphan-components/purge`：`{source, keys?, dry_run?}`
    - **服务端强制只接受 `state == "orphan"`**（停用 / 加载失败 → 400；**不能只靠界面藏按钮**）
    - **先 dry-run 再删**（受影响实体数 / 键 / 样例 id）
    - 粒度 = 按 source 全清或 `keys` 子集；**不支持按实体挑**
    - 事件复用 `on_world_edited`（`{op: "purge_components", …}`）——**不加第 8 个内核事件**
    - 落库走 `save_entities`（唯一盖章点，D28）
- **判定优先级**：**先看目录在不在**（`list_plays()` 只遍历磁盘上还在的包目录），
  再看 `status`；`_disabled` 是持久化的 play_id 集合，**包删了 id 还留着**，
  所以"在 `_disabled` 里"**不等于**"包还在"

### 前端

> **状态：✅ 已落地**（`8d152d5`）。类型 / 标签两区合成一张组件清单；`TagPicker` →
> `ComponentPicker`；`FieldForm` 删掉"猜字段落点"（`homeOf` / `fallbackName` / `extraOf`），
> 改成**每个组件一块、块内渲染该组件自己声明的字段**；`dist/` 已重建。
> 守卫同步：`tests/test_web_view_styles.py`（组件文件名与"两区合一"）+
> `tests/test_editor_integrity.py`（位置读法、全有或全无坐标、JSON 写坏不发）。
> **仍未做**：下面第 3 条（"玩法包"页的遗留组件栏）——那要等 **D44** 的孤儿诊断端点。

- `EntityManager` / `FieldForm` / `TemplateManager` / `MapEditorPage`：
  类型 / 标签两区 → **按组件分组**；`TagPicker` → 组件选择器
- **删** `FieldForm` 的 `homeOf` / `fallbackName` / `extraOf` 那套"猜字段落点"
- "玩法包"页：**停用的包在列表里**（每行显示"遗留组件 N 个"+ "启用即恢复，不可清理"）；
  **已卸载的包不在列表里** → 单开一栏"**已卸载包的遗留组件**"（两种情况天然分栏）
- 前端读法仍全部经 `webui/src/entity.js`（那是名字/位置/组件的唯一入口，守卫在
  `tests/test_editor_integrity.py`）

---

## 3. 实测影响面（别重新数一遍）

| 范围 | `kind` 命中 | `tags` 命中 |
|---|---|---|
| 内核（engine 63 / model 18 / store 12 / identity 11 / api 10 / admin 4 / 其它 4） | **122** | 90 |
| 测试 | **129** | 77 |
| 前端（EntityManager 24 / UiBlockRenderer 9 / MapEditorPage 7 / WorldPlaysPage 6 / FieldForm 5 / …） | **65** | 29 |

**但核心改动面小得多**：裸名承载点**只有 3 处**；写入边界只有 **1 个函数**
（`api.py:_guard_component`，7 个调用点共用）；字段摊平家族很小
（`add_category_fields` 内核 3 / 测试 3；`_category_fields` 内核 8 / 测试 3）。
多数命中是 `kind=` 参数与 `e.kind` 读点这类机械改写。

---

## 4. 已经踩过的坑（**务必看**，每条都是实测过的）

| # | 坑 | 教训 |
|---|---|---|
| 1 | **位置读点漏数**（1d 期）：`_event_payload` 的 `on_entity_move` 在实体"从世界外移回来"时对 `None` 调 `list()` → `TypeError`。事前分类数出 3 个读点，实际 4 个 | 改"默认值/缺失语义"时，**调用点要全量 grep 一遍**，别信"我记得就这几处" |
| 2 | **默认值改了、调用点没跟着改**：`list_entities()` 从 1d 起默认只返回"在世界上"的实体，而 `identity._find_entity_of_account` 还在用它按账户找实体 → **下线玩家登录会被克隆出第二个 player 实体** | 改默认值 = 改**所有**调用点的语义。这条已有守卫：`test_offline_player_keeps_the_same_entity` |
| 3 | **"卸载即恢复"是假的**：`_tag_specs[tag] = …` 是**单槽覆盖**、没有栈，最后声明者卸载即规格消失，前一个不回来（实测：A 注册 `duel`→B 同名→B 停用后 `duel` 无任何能力）。对比：`add_tag_fields` 追加的字段是**多贡献者列表**，各撤各的 | 文档里的保证要去代码里验一遍。**折叠后这条自动消失**（键稳定 → 重装即恢复是真的） |
| 4 | **停用 ≠ 卸载 ≠ 清理**（三件事的语义在 D44；措辞写错过一次） | 卸载**不删数据**；数据只在**手动清理**那一步被删；清理是**双重不可逆**（数据没了 + 该实体的能力也没了，因为能力 = 组件的存在） |
| 5 | 判定"停用 vs 已卸载"时**先看目录在不在** | `_disabled` 是持久化 play_id 集合，包目录删了 id 还在 → 只看它会判错 |
| 6 | 事件 handler 里**别 `await` 长耗时 IO** | `_emit` 全程持 `AsyncRLock`、串行 await handler → 一个包的网络抖动会卡住整个世界。红线是"**handler 不得 await 那个子任务**"，不是"子任务不能碰引擎 API"（handler 返回、锁释放后它自己抢锁是安全的）。结果落回世界：后续 handler 落地，或子任务自己抢锁写 |
| 7 | **顺序与原子性已经有人管**：事件顺序 = D27 的 `(phase, order, 注册序)`；读改写原子 = `AsyncRLock` | 别为"两个包都改 hp"新造机制——那是玩法语义（推荐玩法层"modifier 收集 + 单点结算"）。内核**不加**结算点 |
| 8 | **`update_entity(kind="player")` 的反向升格洞**（已随 D42 修掉） | 老洞会让实体在编辑器里"删不掉"。凡是"锁定某类实体"的检查，都要问一句"反方向呢？" |

---

## 5. 验证流程（照抄）

```powershell
# 全量测试（约 2 分钟）——长跑用后台 job
.venv\Scripts\python.exe -m pytest -q --tb=line

# 静态检查
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .     # 不合格就 `ruff format .`

# 中文文件编码审计（必须在写完中文文件后跑）
.venv\Scripts\python.exe .uitools\utf8_audit.py        # 期望 BAD FILES: 0

# 组件语义冒烟（不入库的脚本，58 条断言）
.venv\Scripts\python.exe .uitools\smoke_v2_components.py

# 前端
cd webui; npm run build        # 期望 "✓ built"，dist/ 是**入库的**，改完必须重新构建
```

**提交与推送惯例**：`git add -A` → 提交信息写进 `.git\COMMIT_*.txt` → `git commit -F` →
`git push origin main`（`main` 一直是直推）。提交信息用中文，风格看 `git log`：
`refactor!:` / `fix:` / `docs:` + 一句话结论 + 正文讲"为什么"。

---

## 6. 环境与工具注意事项（Windows）

- **中文只在文件里是好的**：控制台输出会乱码（`锟斤拷` 那种），**别据此判断文件坏了**——
  要确认就看文件（`read` / `utf8_audit.py`）
- **不要用 PowerShell 改中文文本文件**：会动行尾/编码。用 `edit` 工具；
  万一用了，跑 `ruff format .` 并看 `git diff --stat` 确认没把整个文件重写
- **PowerShell 没有 heredoc**：`<<'EOF'` 会报 `Missing file specification`。
  多行提交信息写文件再 `git commit -F`
- `-Path dir\**\*.vue` 只匹配一层，要递归就用 `Get-ChildItem -Recurse | Select-String`
- **`.uitools/` 不入库**（探针/冒烟脚本放那儿）；本轮用过的探针：
  `_override_probe.py`（覆盖/卸载语义）、`_precedence_demo.py`（顺序演示）、
  `_probe_kind.py`（升格洞）
- 长跑命令用后台 job（`run_in_background` + `job_output`），别阻塞

---

## 7. 验收清单（全部勾上才算第 2 期做完）

- [x] 表 **v11 / 4 列**；`SCHEMA_VERSION == "11"`；`kind` / `tags_json` 进**禁列名单**
- [x] `to_dict()` **5 键**；`Entity.from_dict` 折顶层三键的便利保留（`name` / `desc` / `user_id`）
- [x] **能力 = 组件的存在**：带 `pkg:duel` 组件即具备该能力；虚构组件允许且不贡献能力
- [x] **没有"同名"**：两个包各声明 `merchant` → 两个组件共存，无覆盖
- [x] **裸名解析**：唯一 → 加前缀；无人 → `local:`；多个 → **报错**；解析失败 → **报错**
- [x] **`_tag_owner` 已删**；归属从键里读（D44）
- [x] **不跨组件摊平**；`add_category_fields` 已删；同一组件内同名字段重复声明 → **报错**
- [x] **四象限**：`active` / `inactive` / `orphan` / `fictional` 都测得出来（含 C8 那条）（D44）
- [x] **孤儿清理**：只接受 `orphan`（服务端强制）、dry-run、按 source / keys 两种粒度（D44）
- [x] 前端按组件分组渲染，`homeOf` 那套已删；"已卸载包的遗留组件"单开一栏
- [x] `PLAY_DEV` / `HTTP_API` / `CHANGELOG` / `DESIGN` §12.0 全部同步；**版本 bump 与 tag 由用户决定**
- [x] `pytest`（349 绿）/ `ruff` / `format` / `utf8_audit`（0 坏文件）/ 冒烟（58/58）/ `npm run build` 全绿

> **提醒**：实施完成后是**又一次破坏性变更**，部署侧需要**删掉数据目录下的 `world.db`
> 并重新注册管理员**（D13 无迁移）。这句话要写进 `CHANGELOG` 与部署说明。
