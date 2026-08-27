"""worlditor_play_social：说话与广播（M3 领域包，D1 落地）。

- **地块说话（cell）**：world_say(text) → emit("say", {entity_id, name,
  text, map_id, row, col}, log=True)——同地块的 WebUI/agent 经 SSE 收到；
  语义（谁能听到）由订阅方按位置自行判断（通道 = 事件总线，D1）。
- **全图广播（world）**：world_say(text, scope="world") → 消耗 1 个喇叭
  （items 背包，内核物品定义）+ 每人 30s 冷却（kv 自管）→
  emit("broadcast", {entity_id, name, text}, log=True)。
- **日志视图**：world_log 工具 + 日志视图（历史回放，数据源 world_log 表）。

依赖：worlditor_play_items（喇叭持有）。
"""

from __future__ import annotations

import time

from worlditor_mcp.world import WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

ITEMS_PLAY = "worlditor_play_items"
MEGAPHONE_ITEM = "megaphone"

BROADCAST_COOLDOWN_SECONDS = 30.0
_COOLDOWN_PREFIX = "broadcast_cd:"

_VIEW_KEY = "social_log"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_tool(
        "world_say",
        _world_say,
        description=(
            "说话：text 为要说的话；scope=cell 只对同地块的人可见（默认），"
            "scope=world 全图广播（消耗 1 个喇叭，每人每 30 秒一次）。"
        ),
        params={"text": "string", "scope": "string"},
    )
    api.register_tool(
        "world_log",
        _world_log,
        description="查看最近的世界日志（limit 条，默认 50）：说话/广播/事件历史。",
        params={"limit": "integer"},
    )
    api.register_view(
        _VIEW_KEY,
        title="世界日志",
        icon="📜",
        provider={
            "type": "component",
            "url": f"/plays/{api.play_id}/web/log.js",
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


async def _world_say(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """说话：scope=cell（默认）/ world（喇叭 + 冷却）。"""
    me = _me(api)
    text = str(kwargs.get("text") or "").strip()
    if not text:
        raise WorldError("text 不能为空")
    scope = str(kwargs.get("scope") or "cell")
    if scope not in ("cell", "world"):
        raise WorldError("scope 必须是 cell 或 world")
    if scope == "cell":
        await api.emit(
            "say",
            {
                "entity_id": me.id,
                "name": me.name,
                "text": text,
                "map_id": me.map_id,
                "row": me.row,
                "col": me.col,
            },
            log=True,
        )
        return {"text": f"你说：「{text}」（同地块的人听到了）", "scope": "cell"}
    # world：喇叭 + 冷却
    remaining = await _cooldown_remaining(api, me.id)
    if remaining > 0:
        raise WorldError(f"广播冷却中，还需 {remaining:.0f} 秒")
    count = await api.call_service(
        ITEMS_PLAY, "bag_count", entity_id=me.id, item_id=MEGAPHONE_ITEM
    )
    if count < 1:
        raise WorldError("广播需要 1 个喇叭（找商贩购买或管理员发放）")
    await api.call_service(
        ITEMS_PLAY, "bag_take", entity_id=me.id, item_id=MEGAPHONE_ITEM, count=1
    )
    await api.kv_set(f"{_COOLDOWN_PREFIX}{me.id}", time.time())
    await api.emit(
        "broadcast",
        {"entity_id": me.id, "name": me.name, "text": text},
        log=True,
    )
    return {"text": f"📢 {me.name} 广播：「{text}」（全图）", "scope": "world"}


async def _cooldown_remaining(api: WorlditorPlayAPI, entity_id: str) -> float:
    last = api.kv_get(f"{_COOLDOWN_PREFIX}{entity_id}", 0.0)
    if not isinstance(last, (int, float)):
        return 0.0
    return max(0.0, BROADCAST_COOLDOWN_SECONDS - (time.time() - last))


async def _world_log(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """世界日志（最新在前）。"""
    limit = kwargs.get("limit")
    if limit is None:
        limit = 50
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise WorldError("limit 必须是正整数")
    entries = await api.list_world_log(min(limit, 500))
    return {"text": f"最近 {len(entries)} 条日志。", "entries": entries}


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
