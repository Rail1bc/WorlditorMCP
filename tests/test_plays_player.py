"""worlditor_play_player 内置包测试（出生礼包跨包真实用例）。

覆盖：依赖拓扑（requires items）、出生礼包（金币+物品，只发一次）、
world_profile 工具、角色视图注册。
"""

from __future__ import annotations

from pathlib import Path

from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.v4engine import V4WorldEngine
from worlditor_mcp.world.v4store import V4WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
PLAYER_ID = "worlditor_play_player"
ITEMS_ID = "worlditor_play_items"


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _scenario(db_path, fn):
    engine = V4WorldEngine(V4WorldStore(db_path))
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


async def _call_as(player_id: str, coro_factory):
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


# ---------- 依赖拓扑与加载 ----------


def test_player_requires_items(tmp_path):
    """依赖拓扑：player 声明 requires items——一起加载时 items 先加载。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert PLAYER_ID in ids and ITEMS_ID in ids
        # 拓扑顺序：items 在 player 前
        assert ids.index(ITEMS_ID) < ids.index(PLAYER_ID)

    _run(_scenario(tmp_path / "world.db", fn))


def test_player_missing_dependency(tmp_path):
    """items 缺失时 player 不加载（依赖未启用，记 load_errors）。"""

    async def fn(engine, loader):
        # 只留 player（把 items 排除）
        loader.builtin_dir = tmp_path / "builtin_only_player"
        (tmp_path / "builtin_only_player").mkdir(parents=True, exist_ok=True)
        import shutil

        src = BUILTIN_DIR / PLAYER_ID
        dst = tmp_path / "builtin_only_player" / PLAYER_ID
        shutil.copytree(src, dst)
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert PLAYER_ID not in ids
        assert loader._load_errors.get(PLAYER_ID)  # noqa: SLF001

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
        # 重复触发 place_entity 编辑事件（如移动实体引发的编辑事件）不再发
        await engine.set_attrs(player.id, {"gold": 999})
        from worlditor_mcp.world.v4model import WORLD_EVENTS

        assert "on_world_edited" in WORLD_EVENTS
        # 直接再触发一次 on_world_edited（place_entity op）
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
        assert result["attrs"]["gold"] == 100
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
