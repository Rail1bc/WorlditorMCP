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


def test_admin_sidebar_hosts_play_pages_group():
    """管理端侧栏承载「玩法包管理页」分组（v0.2.1）。

    入口不再挂在玩法包详情页：侧栏分组可收起展开（状态本地记忆），
    并在注册表变化（装/卸/启/停）时经事件重新拉取清单。
    """
    panel = (_WEBUI / "components" / "AdminPanel.vue").read_text(encoding="utf-8")
    assert "玩法包管理页" in panel
    assert "worlditor_admin_pages_open" in panel  # 收起状态记忆
    assert "worlditor:plays-changed" in panel  # 注册表变化实时刷新
    assert "visiblePages" in panel  # 按当前世界的激活集合过滤


def test_admin_sidebar_is_world_scoped():
    """管理端侧栏 = 通用管理 + 世界下拉 + 该世界的玩法包/地图（v0.3.0）。

    多世界治理：选中世界决定下面看什么；侧栏世界来自 localStorage，
    路由带世界（#/admin/world/{id}/plays|maps）。
    """
    panel = (_WEBUI / "components" / "AdminPanel.vue").read_text(encoding="utf-8")
    assert "通用管理" in panel
    assert "worlditor_admin_world" in panel  # 选中世界本地记忆
    assert "#/admin/world/" in panel  # 世界上下文路由
    assert "worlditor:select-world" in panel  # 地图编辑器回填世界上下文
    assert "WorldPlaysPage" in panel and "WorldMapsPage" in panel
    # 旧的世界列表页 / 全局玩法包页已并入世界上下文
    assert not (_WEBUI / "pages" / "admin" / "WorldsPage.vue").exists()
    assert not (_WEBUI / "pages" / "admin" / "PlaysPage.vue").exists()


def test_world_pages_toggle_activation_and_own_maps():
    """世界玩法包页：全部/自定义二态 + 本世界开关；世界地图页：建图即归属。"""
    plays = (_WEBUI / "pages" / "admin" / "WorldPlaysPage.vue").read_text(
        encoding="utf-8"
    )
    assert "play_ids" in plays  # 世界激活集合
    assert "全部启用" in plays and "自定义" in plays
    assert "本世界" in plays
    assert "play-pages" not in plays  # 不再拉管理页清单（入口在侧栏）
    maps = (_WEBUI / "pages" / "admin" / "WorldMapsPage.vue").read_text(
        encoding="utf-8"
    )
    assert "assign-map" in maps  # 建图/归属
    assert "未归属世界" in maps  # 孤儿地图提示 + 一键归属
    host = (_WEBUI / "pages" / "admin" / "PlayPageHost.vue").read_text(encoding="utf-8")
    assert "返回玩法包" not in host


def test_map_governance_pages_shape():
    """地图治理页（v0.4.0）：组织树递归/拖拽/排序 + 跨世界总览 + 体检 + 复制。

    回归背景：v0.3.0 的组织树页只渲染两层（第三层在 UI 里根本看不见）、二级
    文件夹里的地图没有移动入口（放进去就出不来）、`sort` 从建表起没被写过。
    """
    maps = (_WEBUI / "pages" / "admin" / "WorldMapsPage.vue").read_text(
        encoding="utf-8"
    )
    assert "draggable" in maps  # 拖拽移动/排序
    assert "reorder" in maps  # 批量序号落位
    assert "InlineEdit" in maps  # 内联重命名（替代 prompt）
    assert "askConfirm" in maps  # 统一确认层（替代 confirm）
    assert "lint" in maps  # 体检徽章与明细
    assert "/admin/maps/" in maps and "/copy" in maps  # 复制另存

    allmaps = (_WEBUI / "pages" / "admin" / "AllMapsPage.vue").read_text(
        encoding="utf-8"
    )
    assert "跨世界" in allmaps
    assert "/move" in allmaps  # 批量归属/转移走统一搬家端点
    assert "selected" in allmaps  # 多选批量

    panel = (_WEBUI / "components" / "AdminPanel.vue").read_text(encoding="utf-8")
    assert "全部地图" in panel  # 通用管理组入口
    assert "AllMapsPage" in panel
    assert "allmaps" in panel  # #/admin/maps = 跨世界总览


def test_admin_pages_use_no_native_dialogs():
    """管理端不用原生 confirm/prompt/alert（iframe/沙箱下会被浏览器屏蔽）。"""
    offenders = []
    for path in sorted((_WEBUI).rglob("*.vue")) + sorted((_WEBUI).rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for pattern in (
            r"(?<![\w.$])confirm\(",
            r"(?<![\w.$])prompt\(",
            r"(?<![\w.$])alert\(",
        ):
            for match in re.finditer(pattern, text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line} {match.group(0)}")
    assert not offenders, f"原生弹窗应改用 askConfirm()：{offenders}"


def test_confirm_host_is_mounted_globally():
    """确认层宿主挂在 App.vue（所有页面共用一个 Promise API）。"""
    app = (_WEBUI / "App.vue").read_text(encoding="utf-8")
    assert "ConfirmHost" in app
    confirm = (_WEBUI / "confirm.js").read_text(encoding="utf-8")
    assert "askConfirm" in confirm and "settleConfirm" in confirm


def test_editor_is_split_into_panels():
    """编辑器拆成多视图 + 多面板（D24）；出口编辑是独立组件（G24 的修复落点）。"""
    editor_dir = _WEBUI / "components" / "editor"
    for name in (
        "MapGrid.vue",
        "TilePanel.vue",
        "TileEntities.vue",
        "ConnectionPanel.vue",
        "EntityManager.vue",
        "TemplateManager.vue",
        "TagPicker.vue",
        "FieldForm.vue",
    ):
        assert (editor_dir / name).exists(), f"缺少编辑器组件 {name}"
    page = (_WEBUI / "pages" / "admin" / "MapEditorPage.vue").read_text(
        encoding="utf-8"
    )
    for comp in (
        "MapGrid",
        "TilePanel",
        "TileEntities",
        "ConnectionPanel",
        "EntityManager",
        "TemplateManager",
    ):
        assert comp in page, f"编辑器没有用上 {comp}"
    assert "askDiff" in page  # 整对象替换前必须过差异预览（D23）


def test_editor_has_three_switchable_views():
    """三个可切换视图（地图编辑 / 实体 / 模板）——一次只专注一件事。"""
    page = (_WEBUI / "pages" / "admin" / "MapEditorPage.vue").read_text(
        encoding="utf-8"
    )
    assert "地图编辑" in page and "TABS" in page and "gotoTab" in page
    assert "100vh" in page  # 壳高 = 视口内 → 地图视图不纵向滚动
    grid = (_WEBUI / "components" / "editor" / "MapGrid.vue").read_text(
        encoding="utf-8"
    )
    assert "onWheel" in grid and "fit" in grid  # 滚轮缩放 + 适应窗口
    assert "beginPan" in grid  # 拖拽平移


def test_entity_manager_scales_and_is_tile_scoped():
    """实体视图按"上千实体"设计：筛选/排序/分页 + 只看某地块 + 从地块进实体管理。"""
    manager = (_WEBUI / "components" / "editor" / "EntityManager.vue").read_text(
        encoding="utf-8"
    )
    assert "pageSize" in manager and "pager" in manager  # 分页
    assert "tileOnly" in manager and "tileFilter" in manager  # 只看某地块
    assert "kindFilter" in manager and "tagFilter" in manager and "sort" in manager
    tile_ents = (_WEBUI / "components" / "editor" / "TileEntities.vue").read_text(
        encoding="utf-8"
    )
    assert "本格实体" in tile_ents
    page = (_WEBUI / "pages" / "admin" / "MapEditorPage.vue").read_text(
        encoding="utf-8"
    )
    assert "primaryEntities" in page and "manageTileEntities" in page
    assert "locateEntity" in page  # 实体列表 → 回地图定位


def test_diff_preview_layer_is_wired():
    """保存前差异预览（D23 / G24 防线）：diff.js + DiffModal + App.vue 挂载。"""
    assert (_WEBUI / "diff.js").exists()
    assert (_WEBUI / "components" / "DiffModal.vue").exists()
    diff = (_WEBUI / "diff.js").read_text(encoding="utf-8")
    assert "askDiff" in diff and "diffFields" in diff
    assert "DiffModal" in (_WEBUI / "App.vue").read_text(encoding="utf-8")


def test_connection_editor_is_structured():
    """出口编辑不得回到"目标 row,col 文本框"（那正是 G24 丢 map_id/权重的根因）。"""
    conn = (_WEBUI / "components" / "editor" / "ConnectionPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "targetsText" not in conn  # 旧的纯文本目标框已废弃
    assert "weight" in conn and "map_id" in conn  # 目标带地图与权重
    assert "complex" in conn  # 分时段文案有 JSON 模式，不再被 String(dict) 毁掉


def test_entity_panel_renders_schema_and_tags():
    """实体管理：按声明渲染字段（FieldForm）+ 标签组合（TagPicker）+ 合并能力展示。"""
    panel = (_WEBUI / "components" / "editor" / "EntityManager.vue").read_text(
        encoding="utf-8"
    )
    assert "FieldForm" in panel and "TagPicker" in panel
    assert "合并后的能力" in panel  # A4：让管理员看见并集结果
    fields = (_WEBUI / "components" / "editor" / "FieldForm.vue").read_text(
        encoding="utf-8"
    )
    assert "未声明字段" in fields  # 未声明字段走原始 JSON 兜底（A2/D23）
    assert "attrs" in fields and "state" in fields  # 两个数据袋分开标注


def test_map_grid_supports_multi_select_and_arrows():
    """网格：多选 / 框选 / 出口方向箭头（D24 的 E1/E2）。"""
    grid = (_WEBUI / "components" / "editor" / "MapGrid.vue").read_text(
        encoding="utf-8"
    )
    assert "rect" in grid  # 框选
    assert "dirArrow" in grid  # 出口方向箭头
    assert "ctrlKey" in grid  # Ctrl 多选


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
