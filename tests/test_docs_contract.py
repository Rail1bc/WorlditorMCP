"""文档契约守卫（v0.7.3）。

动机：`docs/PLAY_DEV.md` 是玩法包作者的**唯一权威说明**，但它只能靠人肉同步——
实体模型 v2（D41–D44）落地后，文档里留了三个世代的旧形态（`{id, map_id, row,
col, kind, components, tags, …}`、`capabilities()["unknown_components"]`、
"实体表 10 列 / 表结构 v9"），而 `include_absent` 这种"文档承诺、API 没有"的
缺口同样没人拦。实测代价是：照文档写包会直接 TypeError / AttributeError。

这里把三类事实钉成守卫（与 `test_version_consistency.py` 同一风格）：
1. 文档提到的 `api.<方法>(` 必须真的存在于 `WorlditorPlayAPI`（防改名/删除漂移）；
2. 公开方法必须都在文档里出现过（防新增能力不写文档）；
3. 旧实体形态 / 旧能力键 / 旧表结构版本不得作为"现状"出现在任何面向作者的文档里。
"""

from __future__ import annotations

import re
from pathlib import Path

from worlditor_mcp.world.model import Entity
from worlditor_mcp.world.play.api import WorlditorPlayAPI

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = {
    name: (_ROOT / name).read_text(encoding="utf-8")
    for name in ("docs/PLAY_DEV.md", "docs/HTTP_API.md", "README.md", "DESIGN.md")
}
_PLAY_DEV = _DOCS["docs/PLAY_DEV.md"]

# 旧世代的实体投影（第 1 期 / 第 1d 期形态）——作为"现状"出现即为漂移
_STALE_ENTITY_SHAPES = (
    "map_id, row, col, kind, components, tags",
    "id, map_id, row, col, kind",
)


def _public_methods() -> set[str]:
    return {
        name
        for name, value in vars(WorlditorPlayAPI).items()
        if not name.startswith("_") and callable(value)
    }


def test_documented_api_calls_exist():
    """文档里 `api.xxx(` 的每一次调用都必须能在 WorlditorPlayAPI 上找到。"""

    methods = _public_methods()
    referenced = set(re.findall(r"\bapi\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", _PLAY_DEV))
    assert referenced, "没在 PLAY_DEV.md 里扫到任何 api.<方法>( 调用"
    unknown = sorted(referenced - methods)
    assert not unknown, f"文档调用了不存在的 API：{unknown}"


def test_public_api_is_documented():
    """每个公开方法都要在 PLAY_DEV.md 里出现（新增能力不许漏文档）。"""

    missing = sorted(m for m in _public_methods() if m not in _PLAY_DEV)
    assert not missing, f"这些 API 没有出现在 PLAY_DEV.md：{missing}"


def test_docs_use_current_entity_projection():
    """实体投影是 5 键；旧形态不得作为现状出现。"""

    keys = set(Entity(id="x").to_dict())
    assert keys == {"id", "components", "last_active_ts", "revision", "changed_tick"}
    for name, text in _DOCS.items():
        if name == "README.md":
            continue  # README 不描述投影
        for stale in _STALE_ENTITY_SHAPES:
            assert stale not in text, f"{name} 仍把旧实体形态当现状：{stale}"
        for key in keys:
            assert key in text, f"{name} 没提到实体投影字段 {key}"


def test_docs_drop_removed_capability_key():
    """`unknown_components` 已被四象限取代（D44），不得再出现在文档里。"""

    for name, text in _DOCS.items():
        assert "unknown_components" not in text, f"{name} 仍在用旧能力键"


def test_docs_state_current_schema_version():
    """面向作者的文档必须说对表结构版本（v11 / 4 列）。"""

    from worlditor_mcp.world.store import SCHEMA_VERSION

    for name in ("docs/PLAY_DEV.md", "docs/HTTP_API.md"):
        text = _DOCS[name]
        assert f"v{SCHEMA_VERSION}" in text, (
            f"{name} 没写当前表结构版本 v{SCHEMA_VERSION}"
        )
        assert "表结构版本 **v9**" not in text, f"{name} 仍写 v9"
        assert "实体表 **10 列**" not in text, f"{name} 仍写旧的列数"
    # DESIGN 里有历代迁移记录（v8 → v9 → v10 → v11 的历史叙述属正常），只查它
    # 至少提到过当前版本，不禁止历史数字
    assert f"v{SCHEMA_VERSION}" in _DOCS["DESIGN.md"]
