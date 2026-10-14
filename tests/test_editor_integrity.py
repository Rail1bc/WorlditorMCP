"""编辑器数据完整性防回归（v0.5.2/v0.5.2）——源码级守卫。

背景（都是"静默丢数据/静默失效"这一类，用户看不出来）：

1. **分时段文案格式不统一**：曾经"纯文本"与"结构化 JSON"两种写法并存，
   单时段带时间窗（`08:00–18:00`）或权重 ≠ 1 的文案被当纯文本读进来又存回去
   → 窗口丢失；差异预览用同一套扁化规则，连"改了什么"都显示不出来
   （G24 同族）。**v0.5.2 起只有结构化一种格式**，纯文本被内核明确拒绝。
2. **JSON 写坏清空整袋数据**：`attrs`/`state` 的原始 JSON 非法时，
   `parseJson(...) || {}` 把整个容器替换成 `{}` 再提交。
3. **选中格为 null**：空图/删格后地块面板仍按 `{row:0,col:0}` 渲染，
   但保存逻辑读 `primary.value.row` → 抛在控制台里，界面毫无反馈。

JS 没有单元测试跑道，所以这里做**源码守卫**：格式规则集中在共享模块里、
组件既不得自己解析结构、也不得给纯文本留第二条路。改这些文件时若守卫红了，
先想清楚是不是把上面的坑又挖回来了。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_WEBUI = _ROOT / "webui" / "src"
_EDITOR = _WEBUI / "components" / "editor"
_ADMIN = _WEBUI / "pages" / "admin"

_EDITOR_FILES = (
    ("ConnectionPanel", _EDITOR / "ConnectionPanel.vue"),
    ("TilePanel", _EDITOR / "TilePanel.vue"),
    ("MapEditorPage", _ADMIN / "MapEditorPage.vue"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_text_schedule_format_lives_in_one_module():
    """`periods` 结构只允许 `textSchedule.js` 知道；组件一律走它的两个函数。"""
    helper = _read(_WEBUI / "textSchedule.js")
    assert "scheduleToJson" in helper and "parseScheduleText" in helper
    assert "SCHEDULE_HINT" in helper

    for name, path in _EDITOR_FILES:
        text = _read(path)
        assert "textSchedule.js" in text, f"{name} 必须复用共享的 textSchedule 规则"
        assert "periods" not in text, f"{name} 不应自己拼/解文案结构"


def test_no_plain_text_schedule_path():
    """纯文本没有第二条路：写入路径不许把字符串当文案提交。"""
    helper = _read(_WEBUI / "textSchedule.js")
    # parseScheduleText 只接受 JSON 对象（旧的 `|| raw` 纯文本兜底已删）
    assert "return { ok: true, value: raw }" not in helper
    assert "value: null" in helper  # 空 = 清除
    # 显示侧允许把历史纯文本归一成结构（仅一处，且有注释说明）
    assert helper.count('typeof value === "string"') == 1

    for name, path in _EDITOR_FILES:
        text = _read(path)
        assert "parseScheduleText" in text or "scheduleToJson" in text, name
        assert "isPlainSchedule" not in text, f"{name} 不得自带「纯文本判定」"


def test_connection_editor_has_single_label_mode():
    """出口文案只有一个编辑框（JSON），不再有"纯文本 / 分时段"开关。"""
    conn = _read(_EDITOR / "ConnectionPanel.vue")
    assert 'v-model="p.labelJson"' in conn
    assert "labelText" not in conn  # 旧的纯文本输入框
    assert "p.complex" not in conn


def test_editor_does_not_flatten_connection_label_for_diff():
    """差异预览不能把分时段文案压成"共 N 段"之类的摘要（否则改动看不出来）。"""
    text = _read(_ADMIN / "MapEditorPage.vue")
    assert "periods.length" not in text
    assert "periods[0]" not in text


def test_field_form_fails_closed_on_bad_json():
    """JSON 写坏时不许"改一个字段把另一袋数据清空"，且错误必须露在折叠区外。"""
    text = _read(_EDITOR / "FieldForm.vue")
    assert "parseJson(stateJson.value) || {}" not in text
    assert "buildAttrs() || {}" not in text
    # 错误提示出现在 <details> 之前（否则默认折叠 → 用户看不见）
    assert 'v-if="jsonError"' in text
    assert text.index('v-if="jsonError"') < text.index("<details")


def test_editor_keeps_a_concrete_coordinate():
    """地块面板始终有具体坐标：初次打开落到出生点，删格后保留该格坐标。"""
    text = _read(_ADMIN / "MapEditorPage.vue")
    # 保存路径用局部 pos（不是 primary.value.row——null 时会抛）
    assert "const pos = primary.value;" in text
    assert "请先在地图上选择一个坐标" in text
    # 删除地块后保留坐标（而不是置 null 让面板回落到 (0,0)）
    assert "primary.value = { row: tile.row, col: tile.col };" in text


# --------------------------------------------------------------------------
# 实体模型 v2（DESIGN §12）：实体的位置是组件 `core:position`，不是顶层字段。
#
# 坑：顶层 `e.row` 读到的是 `undefined`——不报错、不抛异常，`undefined !== 0`
# 让所有"按格过滤"静默返回空列表，`undefined - undefined` 让排序静默退化成
# NaN 比较（顺序随机）。地图网格则会把这些实体画到 (0,0)。全是静默失效。
# --------------------------------------------------------------------------

_ENTITY_POSITION_CONSUMERS = {
    # 文件 → 必须 import 的位置助手
    _EDITOR / "MapGrid.vue": "entityPosition",
    _EDITOR / "EntityManager.vue": "entityPosition",
    _ADMIN / "MapEditorPage.vue": "entityPosition",
    _ADMIN / "AccountsPage.vue": "positionLabel",
}


def test_entity_js_is_the_only_place_that_knows_component_keys():
    """名字 / 位置 / 账户的读法只允许 `entity.js` 知道（与 textSchedule 同规矩）。"""
    helper = _read(_WEBUI / "entity.js")
    for fn in (
        "entityName",
        "entityDesc",
        "entityUserId",
        "hasComponent",
        # v2 位置（D36）：缺失不是错误，而是"不在世界上"
        "entityPosition",
        "hasPosition",
        "positionLabel",
        "positionSortKey",
    ):
        assert f"export function {fn}" in helper, f"entity.js 应导出 {fn}"
    assert 'CORE_POSITION = "core:position"' in helper


def test_entity_position_reads_go_through_the_helper():
    """位置一律走 `entityPosition()`；顶层 `e.row` / `e.col` / `e.map_id` 已不存在。"""
    for path, helper_name in _ENTITY_POSITION_CONSUMERS.items():
        name = path.stem
        text = _read(path)
        assert helper_name in text, f"{name} 必须经 entity.js 的 {helper_name}() 读位置"

    # 这些是迁移前的老写法，出现在这里说明有地方还在读实体顶层位置
    forbidden = {
        _EDITOR / "MapGrid.vue": ["`${e.row}:${e.col}`"],
        _EDITOR / "EntityManager.vue": ["({{ e.row }}, {{ e.col }})", "a.row - b.row"],
        _ADMIN / "AccountsPage.vue": [
            "a.entity.row",
            "a.entity.map_id",
            "a.entity.col",
        ],
        _ADMIN / "MapEditorPage.vue": [
            "e.row === primary.value.row",
            "primary.value = { row: entity.row",
        ],
    }
    for path, snippets in forbidden.items():
        text = _read(path)
        for snippet in snippets:
            assert snippet not in text, f"{path.stem} 还在直接读实体顶层位置：{snippet}"


def test_entity_create_payload_obeys_all_or_nothing_position():
    """新建实体**要么发全坐标、要么一个都不发**（D36 的"全有或全无"）。

    半截坐标会被后端兜底成 `""` / `0`——"忘给一个"就变成实体静默出现在 (0,0)
    且看起来完全正常。前端这边要守三件事：

    1. 坐标只在「放进世界」勾上时才发（不勾 = 造一个不在世界上的实体）；
    2. **不许发 `map_id`**——实体不带图，图由 `core:position` 决定；
    3. "不放进世界"分支要**剔掉组件里的位置键**，否则从带位置的组件/模板抄来时
       勾选形同虚设（实体照样被放进去）。
    """
    text = _read(_EDITOR / "EntityManager.vue")
    assert "row: Number(draft.row)" in text
    assert "col: Number(draft.col)" in text
    assert "draft.place ? { row:" in text, "坐标必须由「放进世界」开关把关"
    assert "withoutPosition(draft.components)" in text, "不放进世界时要剔掉位置组件"
    assert "map_id:" not in text, "实体不带 map_id——图由 core:position 决定"

    # 地图编辑器里的创建：带坐标才发 map_id（不带坐标时发 map_id 会被判成"半截位置"）
    page = _read(_ADMIN / "MapEditorPage.vue")
    assert (
        "const pos = payload.row === undefined ? {} : { map_id: mapId.value };" in page
    )

    # 模板不带位置：模板是"这东西是什么"，不是"它在哪"
    for path in (_ADMIN / "MapEditorPage.vue", _ADMIN / "AllEntitiesPage.vue"):
        assert "components: withoutPosition(entity.components)" in _read(path), (
            path.stem
        )
