"""worlditor_play_movement：移动与视野（M3 第一个领域包，兼平台验收载体）。

平台能力端到端验证点（GAPS G14 / G3 / G11 / G12）：
- **过滤器链改参**：move 过滤器把方向别名（上/下/左/右、north/south/east/west、
  up/right/down/left）归一为内核连接槽的绝对方向，链尾内核默认实现照常执行。
  纯函数约定：只读入参，不改世界（G14）。
- **MCP 工具**：world_look / world_move / world_who（register_tool）。
- **视图协议**：register_view 注册 3×3 视野视图（web/view.js，WebUI 动态加载）。
- **感知过滤**：list_entities(viewer_id=) 保证视野只显示可见实体（G12）。

设计：**本包无朝向概念**（v0.1.18 移除朝向字段、转身工具与相对方向）——
移动直接用内核地块连接槽的绝对方向（up/right/down/left，见 DESIGN 数据模型）；
"朝向/视角"属于具体玩法的自由发挥空间，内置包不钦定，玩家/agent 也就不必
先"转身"再前进（少一轮往返、少一次换算错误）。
"""

from __future__ import annotations

from worlditor_mcp.world import DIRECTIONS, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

# 方向别名 → 内核绝对方向（G14 过滤器演示：改参归一；中英文都收，对 LLM 友好）
_DIR_ALIASES = {
    "up": "up",
    "上": "up",
    "北": "up",
    "north": "up",
    "right": "right",
    "右": "right",
    "东": "right",
    "east": "right",
    "down": "down",
    "下": "down",
    "南": "down",
    "south": "down",
    "left": "left",
    "左": "left",
    "西": "left",
    "west": "left",
}

# 绝对方向 → 中文方位（提示文案）
_DIR_LABELS = {"up": "上", "right": "右", "down": "下", "left": "左"}

_VIEW_KEY = "movement"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    # G14：move 过滤器（方向别名 → 绝对方向）
    api.register_primitive_filter("move", _normalize_direction, label="方向别名归一")
    # MCP 工具
    api.register_tool(
        "world_look",
        _world_look,
        description=(
            "查看你当前所在位置的 3×3 视野：中心是你自己，返回周围地块、实体与"
            "可走方向（up/right/down/left）。移动前先 look 了解可走方向。"
        ),
    )
    api.register_tool(
        "world_move",
        _world_move,
        description=(
            "移动到相邻地块：direction 用 up/right/down/left，也接受 上/右/下/左 "
            "与 north/east/south/west；path 为可选路径索引（scene.paths 中的 path 值）。"
            "返回新场景。"
        ),
        params={"direction": "string", "path": "integer"},
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


async def _normalize_direction(api: WorlditorPlayAPI, **params) -> dict:
    """G14 过滤器（改参）：方向别名归一为内核绝对方向。

    纯函数：不触碰世界状态；未识别的值原样放行（由内核方向校验报错）。

    Returns:
        参数字典（可能改写 direction）。
    """
    direction = params.get("direction")
    if not isinstance(direction, str):
        return params
    absolute = _DIR_ALIASES.get(direction.strip().lower())
    if absolute is None:
        return params
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


def _walkable(api: WorlditorPlayAPI, map_id: str, row: int, col: int) -> list[str]:
    """本地块可走方向（connections 开启且含路径的槽位）。"""
    loc = api.get_location(map_id, row, col)
    if loc is None:
        return []
    return [
        d
        for d in DIRECTIONS
        if (slot := loc.connections.get(d)) is not None and slot.enabled and slot.paths
    ]


async def _world_look(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """3×3 视野：中心 = 我；同图地块、实体（viewer 过滤 G12）、可走方向。"""
    me = _me(api)
    grid = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            loc = api.get_location(me.map_id, me.row + dr, me.col + dc)
            entities = api.list_entities(
                me.map_id, me.row + dr, me.col + dc, viewer_id=me.id
            )
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
    here = api.get_location(me.map_id, me.row, me.col)
    paths = _walkable(api, me.map_id, me.row, me.col)
    where = here.name if here is not None else "未知地块"
    exits = "、".join(_DIR_LABELS.get(d, d) for d in paths) if paths else "无"
    return {
        "text": f"你在「{where}」（{me.row},{me.col}），可走方向：{exits}。",
        "location": {
            "map_id": me.map_id,
            "row": me.row,
            "col": me.col,
            "name": where,
        },
        "map_id": me.map_id,
        "row": me.row,
        "col": me.col,
        "grid": grid,
        "paths": paths,
    }


async def _world_move(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """移动到相邻地块（走 move 原语 → 过滤器归一方向 → 内核默认实现）。"""
    me = _me(api)
    raw = str(kwargs.get("direction") or "").strip()
    if not raw:
        raise WorldError("缺少 direction（可用 up/right/down/left 或 上/右/下/左）")
    path = kwargs.get("path")
    if path is not None:
        if not isinstance(path, int) or isinstance(path, bool) or path < 0:
            raise WorldError("path 必须是非负整数索引")
    scene = await api.move(me.id, raw, path=path)
    direction = _DIR_ALIASES.get(raw.lower(), raw)
    label = _DIR_LABELS.get(direction, direction)
    return {
        "text": f"你向「{label}」移动到了「{scene.location.name}」。",
        "scene": scene.to_dict(),
    }


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
