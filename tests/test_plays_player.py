"""worlditor_play_player 内置包测试（阶段 1 拆分后：零依赖玩家壳）。

覆盖：缺失 items 仍可加载（价值主张）、world_profile 软依赖（有/无背包摘要）、
角色视图注册。出生礼包测试见 test_plays_starter.py。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
PLAYER_ID = "worlditor_play_player"
ITEMS_ID = "worlditor_play_items"
STARTER_ID = "worlditor_play_starter"


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


def _copy_only(loader, tmp_path: Path, *play_ids: str) -> None:
    """只保留指定内置包（其余从候选里排除）。"""
    loader.builtin_dir = tmp_path / "builtin_only"
    (loader.builtin_dir).mkdir(parents=True, exist_ok=True)
    for play_id in play_ids:
        shutil.copytree(BUILTIN_DIR / play_id, loader.builtin_dir / play_id)


async def _call_as(player_id: str, coro_factory):
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


# ---------- 零依赖（阶段 1 价值主张） ----------


def test_player_loads_without_items(tmp_path):
    """无 items/starter：player 仍可加载（玩家壳零包间依赖）。"""

    async def fn(engine, loader):
        _copy_only(loader, tmp_path, PLAYER_ID)
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert PLAYER_ID in ids
        assert ITEMS_ID not in ids and STARTER_ID not in ids
        assert not loader._load_errors.get(PLAYER_ID)  # noqa: SLF001

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_profile_soft_dependency(tmp_path):
    """软依赖：items 未装时 world_profile 无背包摘要（仅 attrs）。"""

    async def fn(engine, loader):
        _copy_only(loader, tmp_path, PLAYER_ID)
        await loader.load_all()
        player_pkg = next(
            p
            for p in loader.plays.values()
            if p.play_id == PLAYER_ID  # noqa: SLF001
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def call():
            return await player_pkg.module._world_profile(player_pkg.api, None)  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert result["name"] == "小明"
        assert result["bag"] is None
        assert "未启用" in result["text"]

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 工具与视图 ----------


def test_world_profile_tool(tmp_path):
    """world_profile：角色信息（attrs + 背包摘要，跨包读 items 服务）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        player_pkg = next(p for p in plays if p.play_id == PLAYER_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def call():
            return await player_pkg.module._world_profile(player_pkg.api, None)  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert result["name"] == "小明"
        assert result["attrs"]["gold"] == 100  # 礼包由 starter 包发放
        assert any(
            s["item_id"] == "apple" and s["count"] == 3 for s in result["bag"]["slots"]
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_player_view_registered(tmp_path):
    """角色视图注册（url 指向本包 profile.js）。"""

    async def fn(engine, loader):
        await loader.load_all()
        views = {v["key"]: v for v in engine.list_views()}
        assert views["player"]["provider"]["url"] == (
            f"/plays/{PLAYER_ID}/web/profile.js"
        )
        assert (BUILTIN_DIR / PLAYER_ID / "web" / "profile.js").is_file()

    _run(_scenario(tmp_path / "world.db", fn))
