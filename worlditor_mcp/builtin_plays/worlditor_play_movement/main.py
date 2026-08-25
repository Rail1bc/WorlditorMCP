"""worlditor_play_movement：移动与视野（M3 第一个领域包，兼平台验收载体）。

平台能力端到端验证点（GAPS G14 / G3 / G11）：
- **过滤器链改参**：move 过滤器把相对方向（forward/back/left/right）按实体
  facing 换算为绝对方向（up/right/down/left），链尾内核默认实现照常执行。
  纯函数约定：只读 attrs，不改世界（G14）。
- **MCP 工具**：world_look / world_move / world_turn / world_who（register_tool）。
- **视图协议**：register_view 注册 3×3 视野视图（web/view.js，WebUI 动态加载）。
- **感知过滤**：list_entities(viewer_id=) 保证视野只显示可见实体（G12）。

朝向（facing）存 attrs["facing"]（默认 up），是玩法包级字段约定
（G6：命名契约入 PLAY_DEV.md）。
"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v3model import DIRECTIONS
from worlditor_mcp.world.v4engine import WorldError

_FACING_ATTR = "facing"
_DEFAULT_FACING = "up"

# 相对方向 → 顺时针偏移量（环 up → right → down → left → up）
_REL_TO_ABS = {"forward": 0, "right": 1, "back": 2, "left": 3}

_VIEW_KEY = "movement"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    # G14：move 过滤器（相对方向 → 绝对方向）
    api.register_primitive_filter(
        "move", _relative_to_absolute, label="相对方向换算（facing）"
    )
    # MCP 工具
    api.register_tool(
        "world_look",
        _world_look,
        description=(
            "查看你当前所在位置的 3×3 视野：中心是你自己，返回周围地块与实体"
            "（含你的 facing 朝向）。移动前先 look 了解可走方向。"
        ),
    )
    api.register_tool(
        "world_move",
        _world_move,
        description=(
            "沿路径移动：direction 可用相对方向（forward/back/left/right，"
            "相对你的 facing 朝向）或绝对方向（up/right/down/left）。"
            "path 为可选路径索引（scene.paths 中的 path 值）。返回新场景。"
        ),
        params={"direction": "string", "path": "integer"},
    )
    api.register_tool(
        "world_turn",
        _world_turn,
        description=(
            "转身改变 facing 朝向：direction 为 left/right（相对左转/右转）"
            "或绝对方向（up/right/down/left）。转身后 forward 的含义改变。"
        ),
        params={"direction": "string"},
    )
    api.register_tool(
        "world_who",
        _world_who,
        description="查看与你同处一地块的实体（其他人/存在）。",
    )
    # 视图：3×3 视野（url 为服务内绝对路径，经 /plays/<id>/web/* 静态服务）
    api.register_view(
        _VIEW_KEY,
        title="世界",
        icon="🗺️",
        provider={
            "type": "component",
            "url": f"/plays/{api.play_id}/web/view.js",
        },
    )


async def _relative_to_absolute(api: WorlditorPlayAPI, **params) -> dict:
    """G14 过滤器（改参）：相对方向按 facing 换算为绝对方向。

    纯函数：只读 attrs；不在此处做任何世界变更（变更只发生在链尾默认实现）。
    绝对方向原样放行。

    Returns:
        参数字典（可能改写 direction）。
    """
    direction = params.get("direction")
    if direction not in _REL_TO_ABS:
        return params
    entity_id = params.get("entity_id")
    if entity_id is None:
        return params
    facing = api.get_attrs(entity_id).get(_FACING_ATTR, _DEFAULT_FACING)
    if facing not in DIRECTIONS:
        facing = _DEFAULT_FACING
    absolute = DIRECTIONS[(DIRECTIONS.index(facing) + _REL_TO_ABS[direction]) % 4]
    return {**params, "direction": absolute}


def _me(api: WorlditorPlayAPI):
    """当前调用者实体；无身份/不存在 → WorldError。"""
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    entity = api.get_entity(entity_id)
    if entity is None:
        raise WorldError(f"实体不存在：{entity_id}")
    return entity


def _facing_of(api: WorlditorPlayAPI, entity_id: str) -> str:
    facing = api.get_attrs(entity_id).get(_FACING_ATTR, _DEFAULT_FACING)
    return facing if facing in DIRECTIONS else _DEFAULT_FACING


async def _world_look(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """3×3 视野：中心 = 我；含 facing、同图地块、实体（viewer 过滤 G12）、可走方向。"""
    me = _me(api)
    facing = _facing_of(api, me.id)
    grid = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            r, c = me.row + dr, me.col + dc
            loc = api.get_location(me.map_id, r, c)
            entities = api.list_entities(me.map_id, r, c, viewer_id=me.id)
            grid.append(
                {
                    "dr": dr,
                    "dc": dc,
                    "loc": {"name": loc.name} if loc is not None else None,
                    "entities": [
                        {
                            "id": e.id,
                            "kind": e.kind,
                            "name": e.name,
                            "is_me": e.id == me.id,
                        }
                        for e in entities
                    ],
                }
            )
    # 可走方向（本地块 connections 开启的槽位）
    loc = api.get_location(me.map_id, me.row, me.col)
    paths = []
    if loc is not None:
        for d in DIRECTIONS:
            slot = loc.connections.get(d)
            if slot is not None and slot.enabled and slot.paths:
                paths.append(d)
    return {
        "text": (
            f"你在「{loc.name if loc is not None else '未知地块'}」"
            f"（{me.row},{me.col}），面向{facing}。"
        ),
        "facing": facing,
        "map_id": me.map_id,
        "row": me.row,
        "col": me.col,
        "grid": grid,
        "paths": paths,
    }


async def _world_move(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """路径移动（走 move 原语 → 过滤器换算相对方向 → 内核默认实现）。"""
    me = _me(api)
    direction = str(kwargs.get("direction") or "forward")
    path = kwargs.get("path")
    if path is not None:
        if not isinstance(path, int) or isinstance(path, bool) or path < 0:
            raise WorldError("path 必须是非负整数索引")
    scene = await api.move(me.id, direction, path=path)
    return {
        "text": f"你向「{direction}」移动到了「{scene.location.name}」。",
        "scene": scene.to_dict(),
        "facing": _facing_of(api, me.id),
    }


async def _world_turn(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """转身：direction = left/right（相对）或绝对方向。"""
    me = _me(api)
    facing = _facing_of(api, me.id)
    direction = str(kwargs.get("direction") or "left")
    if direction in ("left", "right"):
        delta = 1 if direction == "right" else -1
        facing = DIRECTIONS[(DIRECTIONS.index(facing) + delta) % 4]
    elif direction in DIRECTIONS:
        facing = direction
    else:
        raise WorldError("direction 必须是 left/right 或 up/right/down/left 之一")
    await api.set_attrs(me.id, {_FACING_ATTR: facing})
    return {"text": f"你转向了「{facing}」。", "facing": facing}


async def _world_who(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """同地块实体（viewer 过滤 G12）。"""
    me = _me(api)
    peers = [
        {"id": e.id, "kind": e.kind, "name": e.name}
        for e in api.list_entities(me.map_id, me.row, me.col, viewer_id=me.id)
        if e.id != me.id
    ]
    return {
        "text": f"这里还有 {len(peers)} 个存在。" if peers else "这里只有你一个人。",
        "peers": peers,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：本包无自管资源（过滤器/工具/视图随生命周期自动清理）。"""
