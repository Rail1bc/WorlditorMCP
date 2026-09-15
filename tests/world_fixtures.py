"""测试用世界夹具（v0.2.0：内核不再内置世界内容，测试自行铺世界）。

两种铺法：

- ``seed_test_world(engine)``：最小可用世界——一张地图 + 十字形 5 地块 + 双向
  连接（中央广场 ↔ 东南西北）。适合"只需要有地方站/能走一步"的测试。
- ``install_demo_world(engine)``：把内置世界包 ``worlditor_play_demo_world``
  的数据直接导入（不经 PlayLoader），得到原来的演示世界（41 地块、小镇广场、
  商贩·阿福…）。适合断言真实地名/实体的测试。

两者都幂等：已存在的地图/地块跳过。
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
        await engine.create_map(map_id, "测试世界", spawn_row=0, spawn_col=0)
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
