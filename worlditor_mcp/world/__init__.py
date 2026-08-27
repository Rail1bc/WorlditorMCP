"""worlditor 世界内核包（玩法包 SDK 的稳定出口）。

协议无关的核心：WorldEngine（事实/原语/注册表/事件总线）+ WorldStore（持久化）
+ 数据模型 + 身份服务。玩法包 import 统一走本包（worlditor_mcp.world），
不依赖内核内部模块路径（engine/store/model 可自由重构）。
"""

from .engine import WorldEngine, WorldError
from .model import (
    DIR_OFFSETS,
    DIRECTIONS,
    OPPOSITE_DIR,
    Entity,
    EntityKindSpec,
    InteractionRequest,
    InteractionResult,
    ItemDef,
    Location,
    MenuButton,
    ScenePath,
    SceneView,
    ShortCircuit,
    Target,
    TextSchedule,
    UiBlock,
    World,
    WorldFolder,
    WorldMap,
    WorldTemplate,
    entity_db_row,
    entity_from_row,
    item_db_row,
    item_from_row,
)
from .store import DEFAULT_MAP_ID, WorldStore

__all__ = [
    "DEFAULT_MAP_ID",
    "DIR_OFFSETS",
    "DIRECTIONS",
    "Entity",
    "EntityKindSpec",
    "InteractionRequest",
    "InteractionResult",
    "ItemDef",
    "Location",
    "MenuButton",
    "OPPOSITE_DIR",
    "ScenePath",
    "SceneView",
    "ShortCircuit",
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
    "item_db_row",
    "item_from_row",
]
