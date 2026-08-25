"""worlditor_play_player：玩家（M3 领域包）。

职责（DESIGN §6）：
- **出生礼包**：新玩家/agent 实体出生 → 发初始物品（调 items 包 bag_add 服务，
  跨包真实用例）+ 初始金币（attrs 玩法数据）；只发一次（attrs 标记）。
- **角色视图**：显示我的 attrs 角色卡（数据来自 /scene，组件自行 fetch）。
- **world_profile 工具**：我的角色信息（attrs + 背包摘要，背包经 items 服务读）。

依赖：worlditor_play_items（play.yaml requires.plays，加载器拓扑保证先加载）。
"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import WorldError

ITEMS_PLAY = "worlditor_play_items"
_GOLD_ATTR = "gold"
_STARTER_ATTR = "starter_granted"

# 出生礼包：金币 + 苹果×3 + 面包×2
STARTER_GOLD = 100
STARTER_ITEMS = {"apple": 3, "bread": 2}

_VIEW_KEY = "player"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_world_event("on_world_edited", _on_edited)
    api.register_tool(
        "world_profile",
        _world_profile,
        description="查看你的角色信息：属性与背包摘要。",
    )
    api.register_view(
        _VIEW_KEY,
        title="角色",
        icon="🧍",
        provider={
            "type": "component",
            "url": f"/plays/{api.play_id}/web/profile.js",
        },
    )


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


def _me(api: WorlditorPlayAPI):
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    entity = api.get_entity(entity_id)
    if entity is None:
        raise WorldError(f"实体不存在：{entity_id}")
    return entity


async def _world_profile(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我的角色卡：attrs + 背包摘要（items 服务）。"""
    me = _me(api)
    bag = await api.call_service(ITEMS_PLAY, "bag_get", entity_id=me.id)
    lines = [f"{s['name']}×{s['count']}" for s in bag["slots"]]
    return {
        "text": (
            f"{me.name}（{me.kind}）："
            + "、".join(f"{k}={v}" for k, v in me.attrs.items())
            + "；背包："
            + ("、".join(lines) if lines else "空的")
        ),
        "name": me.name,
        "kind": me.kind,
        "attrs": dict(me.attrs),
        "bag": bag,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
