"""worlditor 世界内核包（玩法包 SDK 的稳定出口）。

协议无关的核心：WorldEngine（事实/原语/注册表/事件总线）+ WorldStore（持久化）
+ 数据模型 + 身份服务。玩法包 import 统一走本包（worlditor_mcp.world），
不依赖内核内部模块路径（engine/store/model 可自由重构）。

v2 / D37：``ItemDef`` 与 ``item_db_row`` / ``item_from_row`` **已移除**——物品不在
内核（定义 → 组件声明，实例 → 实体 + 组件）。见 DESIGN §12.8。
"""

from .engine import WorldEngine, WorldError
from .model import (
    DEFAULT_EVENT_PHASE,
    DIR_OFFSETS,
    DIRECTIONS,
    EVENT_PHASES,
    OPPOSITE_DIR,
    Entity,
    InteractionRequest,
    InteractionResult,
    Location,
    MenuButton,
    ScenePath,
    SceneView,
    ShortCircuit,
    TagSpec,
    Target,
    TextSchedule,
    UiBlock,
    World,
    WorldFolder,
    WorldMap,
    WorldTemplate,
    entity_db_row,
    entity_from_row,
    parse_names,
)
from .store import DEFAULT_MAP_ID, WorldStore

__all__ = [
    "DEFAULT_EVENT_PHASE",
    "DEFAULT_MAP_ID",
    "DIR_OFFSETS",
    "DIRECTIONS",
    "EVENT_PHASES",
    "Entity",
    "InteractionRequest",
    "InteractionResult",
    "Location",
    "MenuButton",
    "OPPOSITE_DIR",
    "ScenePath",
    "SceneView",
    "ShortCircuit",
    "TagSpec",
    "Target",
    "TextSchedule",
    "UiBlock",
    "World",
    "WorldEngine",
    "WorldError",
    "WorldFolder",
    "WorldMap",
    "WorldStore",
    "WorldTemplate",
    "entity_db_row",
    "entity_from_row",
    "parse_names",
]
