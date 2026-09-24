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
