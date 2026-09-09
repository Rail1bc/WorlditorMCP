"""worlditor_play_starter 内置包测试（出生礼包，阶段 1 拆分自 player 包）。

覆盖：依赖拓扑（requires items）、出生礼包（金币+物品，只发一次）、
缺失依赖拒绝加载。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
STARTER_ID = "worlditor_play_starter"
ITEMS_ID = "worlditor_play_items"


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _scenario(db_path, fn):
    engine = WorldEngine(WorldStore(db_path))
    loader = PlayLoader(
        engine,
        plays_dir=db_path.parent / "plays",
        builtin_dir=BUILTIN_DIR,
        worlditor_version="0.1.0",
    )

    async def main():
        await engine.initialize()
        try:
            return await fn(engine, loader)
        finally:
            await engine.terminate()

    return main()


def _copy_only(loader, tmp_path: Path, play_id: str) -> None:
    """只保留指定内置包（其余从候选里排除）。"""
    loader.builtin_dir = tmp_path / "builtin_only"
    (loader.builtin_dir).mkdir(parents=True, exist_ok=True)
    shutil.copytree(BUILTIN_DIR / play_id, loader.builtin_dir / play_id)


# ---------- 依赖拓扑与加载 ----------


def test_starter_requires_items(tmp_path):
    """依赖拓扑：starter 声明 requires items——一起加载时 items 先加载。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert STARTER_ID in ids and ITEMS_ID in ids
        assert ids.index(ITEMS_ID) < ids.index(STARTER_ID)

    _run(_scenario(tmp_path / "world.db", fn))


def test_starter_missing_dependency(tmp_path):
    """items 缺失时 starter 不加载（依赖未启用，记 load_errors）。"""

    async def fn(engine, loader):
        _copy_only(loader, tmp_path, STARTER_ID)
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert STARTER_ID not in ids
        assert loader._load_errors.get(STARTER_ID)  # noqa: SLF001

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 出生礼包 ----------


def test_starter_pack(tmp_path):
    """新玩家 → 金币 100 + 苹果×3 + 面包×2（跨包 items 服务）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        attrs = engine.get_attrs(player.id)
        assert attrs.get("gold") == 100
        assert attrs.get("starter_granted") is True
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="bread"
            )
            == 2
        )
        # agent 也有礼包
        agent = await engine.place_entity("agent", "default", 1, 0, name="小智")
        assert engine.get_attrs(agent.id).get("gold") == 100

    _run(_scenario(tmp_path / "world.db", fn))


def test_starter_pack_once(tmp_path):
    """礼包只发一次（attrs 标记幂等）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        # 重复触发 on_world_edited（place_entity op）不再发
        await engine.set_attrs(player.id, {"gold": 999})
        await engine.emit(
            "on_world_edited",
            {"op": "place_entity", "entity_id": player.id},
        )
        assert engine.get_attrs(player.id).get("gold") == 999  # 未重置
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )

    _run(_scenario(tmp_path / "world.db", fn))
