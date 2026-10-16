"""测试用世界夹具（v0.2.0：内核不再内置世界内容，测试自行铺世界）。

两种铺法：

- ``seed_test_world(engine)``：最小可用世界——一张地图 + 十字形 5 地块 + 双向
  连接（中央广场 ↔ 东南西北）。适合"只需要有地方站/能走一步"的测试。
- ``install_demo_world(engine)``：把内置世界包 ``worlditor_play_demo_world``
  的数据直接导入（不经 PlayLoader），得到原来的演示世界（41 地块、小镇广场、
  商贩·阿福…）。适合断言真实地名/实体的测试。

再加一个身份侧的通用动作 ``give_avatar``：D45/D46 之后**注册不再产生实体**，
凡是"以玩家身份做事"（调工具 / 看视图 / 看 /state）的测试都要显式给一具化身
——那正是玩法包要做的事（造 → 认领 → 指过去）。

铺法都幂等：已存在的地图/地块跳过。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from worlditor_mcp.world.play.api import WorlditorPlayAPI

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
DEMO_WORLD_ID = "worlditor_play_demo_world"

TEST_MAP_ID = "default"
# 十字形布局：(row, col) → 地块名
TEST_CELLS: dict[tuple[int, int], str] = {
    (0, 0): "中央广场",
    (-1, 0): "北门",
    (1, 0): "南站",
    (0, -1): "西巷",
    (0, 1): "东街",
}
_DIRECTIONS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


async def seed_test_world(engine, *, map_id: str = TEST_MAP_ID) -> None:
    """铺一张最小地图（十字 5 地块 + 双向连接），幂等。"""
    if engine.get_map(map_id) is None:
        await engine.create_map(map_id, "测试世界")
    for (row, col), name in TEST_CELLS.items():
        if engine.get_location(map_id, row, col) is None:
            await engine.create_location(map_id, row, col, name)
    center = (0, 0)
    for direction, (dr, dc) in _DIRECTIONS.items():
        target = (center[0] + dr, center[1] + dc)
        await _connect(engine, map_id, center, direction, target)
        opposite = {v: k for k, v in _DIRECTIONS.items()}[(dr, dc)]
        await _connect(engine, map_id, target, opposite, center)


async def _connect(engine, map_id: str, src: tuple[int, int], direction: str, dst):
    await engine.update_connection(
        map_id,
        src[0],
        src[1],
        direction,
        enabled=True,
        paths=[{"targets": [{"map_id": map_id, "row": dst[0], "col": dst[1]}]}],
    )


async def give_avatar(
    engine,
    info,
    *,
    name: str = "化身",
    map_id: str = TEST_MAP_ID,
    row: int = 0,
    col: int = 0,
):
    """给一份玩家凭据一具化身，并让这份凭据**指向它**；返回该实体。

    三步就是玩法包的三步（D46）：

    1. ``place_entity`` 造实体；
    2. ``claim_avatar`` 认领给该凭据的主体（写 ``core:account``，从此受 D14 保护）；
    3. ``set_acting_entity`` 把这份凭据的行动实体指过去（= ``api.act_as``）。

    三步都必须显式做——D45 之后内核不会再替任何人"诞生角色"。
    """
    entity = await engine.place_entity(None, map_id, row, col, name=name)
    await engine.claim_avatar(entity.id, info.account_id)
    await engine.set_acting_entity(info.token, entity.id)
    return entity


def schedule(
    text: str, *, start: str = "00:00", end: str = "24:00", weight: float = 1.0
):
    """构造结构化文案（TextSchedule）——内核只认这一种格式（v0.5.2）。

    纯字符串在 v0.5.2 起被明确拒绝（同一份数据两种写法 → 静默丢字段），
    测试里也用同一个构造器，避免各处手抄 periods 结构。
    """
    return {
        "periods": [
            {"start": start, "end": end, "items": [{"text": text, "weight": weight}]}
        ]
    }


def _load_world_module():
    path = BUILTIN_DIR / DEMO_WORLD_ID / "main.py"
    spec = importlib.util.spec_from_file_location(DEMO_WORLD_ID, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def install_demo_world(engine) -> None:
    """导入内置演示世界（41 地块 + 商贩·阿福/告示牌/木门），幂等。"""
    module = _load_world_module()
    api = WorlditorPlayAPI(engine, DEMO_WORLD_ID)
    await module.setup(api, None)
