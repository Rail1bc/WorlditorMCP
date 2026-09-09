"""worlditor_play_player：玩家档（玩家部件模式，DESIGN §4.5）。

职责（阶段 1 拆分后）：
- **角色视图**：显示我的 attrs 角色卡（数据来自 /scene，组件自行 fetch）。
- **world_profile 工具**：我的角色信息（attrs + 可选背包摘要）。

设计：玩家 = 内核身份实体（player/agent kind，身份红线在内核）+ **可追加
部件**——出生礼包 = worlditor_play_starter、背包 = worlditor_play_items…
本包是「玩家壳」，**零包间硬依赖**：背包摘要为软依赖（list_services 探测
bag_get，items 服务存在才附带，否则仅显示属性）。
"""

from __future__ import annotations

from worlditor_mcp.world import WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

ITEMS_PLAY = "worlditor_play_items"
_VIEW_KEY = "player"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_tool(
        "world_profile",
        _world_profile,
        description="查看你的角色信息：属性与（可选）背包摘要。",
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


def _me(api: WorlditorPlayAPI):
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    entity = api.get_entity(entity_id)
    if entity is None:
        raise WorldError(f"实体不存在：{entity_id}")
    return entity


def _has_service(api: WorlditorPlayAPI, play_id: str, name: str) -> bool:
    """部件软依赖探测：服务提供方已加载（本体包未装时玩家壳仍可用）。"""
    return any(
        s["play_id"] == play_id and s["name"] == name for s in api.list_services()
    )


async def _world_profile(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我的角色卡：attrs + （可选）背包摘要——背包为软依赖部件。"""
    me = _me(api)
    text = f"{me.name}（{me.kind}）：" + "、".join(
        f"{k}={v}" for k, v in me.attrs.items()
    )
    bag = None
    if _has_service(api, ITEMS_PLAY, "bag_get"):
        bag = await api.call_service(ITEMS_PLAY, "bag_get", entity_id=me.id)
        lines = [f"{s['name']}×{s['count']}" for s in bag["slots"]]
        text += "；背包：" + ("、".join(lines) if lines else "空的")
    else:
        text += "；背包：未启用（安装 worlditor_play_items 后可见）"
    return {
        "text": text,
        "name": me.name,
        "kind": me.kind,
        "attrs": dict(me.attrs),
        "bag": bag,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
