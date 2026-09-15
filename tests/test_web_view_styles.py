"""视图样式防回归（v0.1.17）：玩家端布局类 + 玩法包视图组件的暗色约定。

背景：v0.1.17 之前玩家端 header / tab / 内容区样式类**完全缺失**
（`.app-header` / `.view-tabs` / `.view-host` 无定义）——视图导航竖排、
两个悬浮按钮重叠、内容区 `overflow: hidden` 不可滚动；玩法包视图组件又
硬编码白底 + 裸 `<button>`（浏览器系统浅色样式）→ 暗色主题下"整片发白、
白底白字看不清"。本测试守住两条线：

1. 内核 `styles.css` 必须定义玩家端布局类与 `wt-*` 组件样式基石；
2. 玩法包**视图组件**不得硬编码浅色，按钮必须带样式类（管理页组件
   `admin-*.js` 走管理端表格密度、用 CSS 变量自管理，不在此列）。
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_WEBUI = _ROOT / "webui" / "src"
_BUILTIN = _ROOT / "worlditor_mcp" / "builtin_plays"

# 玩家端布局/组件样式类（styles.css 缺失即布局崩坏——v0.1.17 回归点）
_REQUIRED_CSS = (
    ".app-header",
    ".brand",
    ".view-tabs",
    ".tab",
    ".header-btn",
    ".app-main",
    ".view-host",
    ".empty-hint",
    ".wt-head",
    ".wt-title",
    ".wt-dim",
    ".wt-btn",
    ".wt-err",
    ".wt-grid",
    ".wt-cols-4",
    ".wt-cell",
    ".wt-list",
    ".wt-li",
)

# 组件内禁止硬编码的浅色/中性色（暗色主题：必须用 --bg/--text/--accent 变量或 wt-* 类）
_FORBIDDEN_COLORS = (
    "#ffffff",
    "#f7f7f7",
    "#f4f4f4",
    "#fff7d6",
    "#eee",
    "#ddd",
    "#bbb",
    "#888",
    "#555",
    "#b00020",
    "#2f6f2f",
)

# 按钮必须带的样式类（玩家端视图统一 wt-btn；内核 UiBlock 按钮用 btn*）
_BUTTON_CLASSES = ("wt-btn", "btn")


def _view_component_files() -> list[Path]:
    """玩法包视图组件（排除管理页组件 admin-*.js）。"""
    return sorted(
        p for p in _BUILTIN.glob("*/web/*.js") if not p.name.startswith("admin-")
    )


def test_styles_define_view_layout_classes():
    """styles.css 必须定义玩家端布局类与 wt-* 样式基石。"""
    css = (_WEBUI / "styles.css").read_text(encoding="utf-8")
    missing = [name for name in _REQUIRED_CSS if name not in css]
    assert not missing, f"styles.css 缺少样式类：{missing}"


def test_app_shell_uses_view_host_and_header_buttons():
    """App.vue：视图包 .view-host；头部用 .header-btn（旧悬浮 .logout-btn 已废弃）。"""
    app = (_WEBUI / "App.vue").read_text(encoding="utf-8")
    assert 'class="view-host"' in app
    assert 'class="header-btn"' in app
    assert "logout-btn" not in app


def test_view_components_use_no_hardcoded_light_colors():
    """视图组件不得硬编码浅色（否则暗色主题下白底/白底白字）。"""
    files = _view_component_files()
    assert files, "未找到内置玩法包视图组件"
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        hits = [color for color in _FORBIDDEN_COLORS if color in text]
        assert not hits, f"{path.name} 硬编码浅色 {hits}（应改用 wt-* 类或 CSS 变量）"


def test_view_components_buttons_are_styled():
    """视图组件的 <button> 必须带样式类（裸 button = 系统浅色样式）。"""
    for path in _view_component_files():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'h\(\s*"button",\s*\{(.{0,200})', text, re.S):
            blob = match.group(1)
            assert any(cls in blob for cls in _BUTTON_CLASSES), (
                f'{path.name} 存在无样式按钮（补 class: "wt-btn"）：{blob[:90]!r}'
            )
