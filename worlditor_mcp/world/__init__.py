"""worlditor 世界内核包。

协议无关的核心动作（MCP 工具 / WebUI / 管理端点共用）。v3 引擎已于 M2
删除（DESIGN.md §7.2 复用清单），v3model/store 保留（v4 事实层复用）。
"""

from .store import DEFAULT_MAP_ID
from .v3model import (
    DIR_OFFSETS,
    DIRECTIONS,
    OPPOSITE_DIR,
    Location,
    SceneView,
    Target,
    TextSchedule,
    WorldMap,
    WorldTemplate,
)
from .v4engine import WorldError

__all__ = [
    "DEFAULT_MAP_ID",
    "DIR_OFFSETS",
    "DIRECTIONS",
    "Location",
    "OPPOSITE_DIR",
    "SceneView",
    "Target",
    "TextSchedule",
    "WorldError",
    "WorldMap",
    "WorldTemplate",
]
