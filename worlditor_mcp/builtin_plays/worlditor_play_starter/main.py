"""worlditor_play_starter：出生礼包（玩家部件模式，DESIGN §4.5）。

职责：
- **出生礼包**：新玩家/agent 实体出生 → 初始金币（attrs 玩法数据）+
  初始物品（items 包 bag_add 服务，跨包真实用例）；只发一次（attrs 标记）。

依赖：worlditor_play_items（play.yaml requires.plays，加载器拓扑保证先加载）。

设计（阶段 1 拆分自 worlditor_play_player）：
- 玩家 = 内核身份实体 + 可追加部件；出生礼包是第一个独立部件包。
- 停用本包 = 世界无出生礼包；社区自定义礼包 = 同 play_id 覆盖（加载器以
  play_id 为键，社区目录优先——见 GAPS 观察「包裹覆」，机制待正式化）。
"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI

ITEMS_PLAY = "worlditor_play_items"
_GOLD_ATTR = "gold"
_STARTER_ATTR = "starter_granted"

# 出生礼包：金币 + 苹果×3 + 面包×2
STARTER_GOLD = 100
STARTER_ITEMS = {"apple": 3, "bread": 2}


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_world_event("on_world_edited", _on_edited)


async def _on_edited(api: WorlditorPlayAPI, what) -> None:
    """新玩家/agent 出生 → 发礼包（幂等：attrs 标记只发一次）。"""
    if not isinstance(what, dict) or what.get("op") != "place_entity":
        return
    entity = api.get_entity(what.get("entity_id", ""))
    if entity is None or entity.kind not in ("player", "agent"):
        return
    if entity.attrs.get(_STARTER_ATTR):
        return
    # 初始金币（attrs 玩法数据）
    await api.set_attrs(entity.id, {_GOLD_ATTR: STARTER_GOLD, _STARTER_ATTR: True})
    # 初始物品（items 包背包服务；依赖缺失时服务调用报错由加载拓扑拦截）
    for item_id, count in STARTER_ITEMS.items():
        await api.call_service(
            ITEMS_PLAY, "bag_add", entity_id=entity.id, item_id=item_id, count=count
        )


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
