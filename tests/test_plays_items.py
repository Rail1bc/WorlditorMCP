"""worlditor_play_items 内置包测试（D8 持有下沉 + M3 跨包服务真实用例）。

覆盖：物品定义注册、bag_add/take/count/get 服务（含跨包调用）、堆叠/容量、
world_bag/world_use 工具（use 与交互联动扣减）、视图注册。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
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
    """以 player 身份调用（注入 _caller_entity，模拟 MCP ctx 身份）。"""
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


# ---------- 加载与注册 ----------


def test_items_play_loaded(tmp_path):
    """内置包加载：物品定义 / 4 服务 / 2 工具 / 视图就位。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        assert items is not None
        # 物品定义（D13：苹果/面包归 items 包）
        assert "apple" in engine.store.items
        assert "bread" in engine.store.items
        assert engine.store.items["apple"].use_action == "eat"
        # 服务
        services = {(s["play_id"], s["name"]) for s in engine.list_services()}
        assert services >= {
            (ITEMS_ID, "bag_add"),
            (ITEMS_ID, "bag_take"),
            (ITEMS_ID, "bag_count"),
            (ITEMS_ID, "bag_get"),
        }
        # 工具
        tools = {t["name"] for t in engine.list_tools()}
        assert {"world_bag", "world_use"} <= tools
        # 视图
        views = {v["key"]: v for v in engine.list_views()}
        assert views["items"]["provider"]["url"] == (f"/plays/{ITEMS_ID}/web/bag.js")

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 背包服务（含跨包调用） ----------


def test_bag_add_take_count(tmp_path):
    """bag_add/take/count：增删查；不足报错。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        api = items.api
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 0
        )
        await api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=3
        )
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )
        await api.call_service(
            ITEMS_ID, "bag_take", entity_id=player.id, item_id="apple", count=1
        )
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 2
        )
        # 不足 → WorldError
        with pytest.raises(WorldError, match="不足"):
            await api.call_service(
                ITEMS_ID, "bag_take", entity_id=player.id, item_id="apple", count=99
            )
        # 未注册物品
        with pytest.raises(WorldError, match="物品不存在"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="nope", count=1
            )
        # 非法 count
        with pytest.raises(WorldError, match="正整数"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=0
            )

    _run(_scenario(tmp_path / "world.db", fn))


def test_bag_cross_play(tmp_path):
    """跨包真实用例：另一个玩法包（pkg_b）调 items 服务发物品。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        api_b = WorlditorPlayAPI(engine, "pkg_b")
        engine.attach_play_api("pkg_b", api_b)
        # pkg_b 发礼包（出生礼包场景）
        await api_b.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=3
        )
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_bag_stack_and_capacity(tmp_path):
    """堆叠上限 99 + 格子容量 20。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        api = items.api
        # 150 个苹果 → 2 格（99 + 51）
        await api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=150
        )
        bag = await api.call_service(ITEMS_ID, "bag_get", entity_id=player.id)
        assert len(bag["slots"]) == 2
        assert bag["slots"][0]["count"] == 99
        assert bag["slots"][1]["count"] == 51
        # 20 种物品 → 满
        for i in range(18):
            item_id = f"apple{i}"
            engine.store.items[item_id] = engine.store.items["apple"]  # 直接登记定义
        for i in range(18):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id=f"apple{i}", count=1
            )
        with pytest.raises(WorldError, match="已满"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="bread", count=1
            )

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 工具 ----------


def test_world_bag_tool(tmp_path):
    """world_bag：我的背包（工具经服务通道读）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=2
        )

        async def call():
            return await items.module._world_bag(items.api, None)  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert result["used"] == 1
        assert result["slots"][0]["name"] == "苹果"
        assert result["slots"][0]["count"] == 2

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_use_tool(tmp_path):
    """world_use：交互联动——注册 eat 交互 → 使用苹果 → 交互执行 + 扣 1。"""

    async def fn(engine, loader):
        from worlditor_mcp.world.v4model import InteractionResult

        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        used = []

        async def _eat(api, req):
            used.append(req.item_id)
            return InteractionResult(text="咔嚓，好吃！")

        engine.register_interaction("eat", _eat, label="吃")
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=2
        )

        async def call():
            return await items.module._world_use(items.api, None, item_id="apple")  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert used == ["apple"]  # 交互被执行
        assert "text" in result
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 1
        )
        # 再吃一个 → 0；继续吃 → 报错（没有苹果）
        await _call_as(player.id, call)
        with pytest.raises(WorldError, match="没有"):
            await _call_as(player.id, call)

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_use_unknown_item(tmp_path):
    """world_use：未注册物品 / 不可使用物品 → WorldError。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=1
        )

        async def call(item_id):
            return await items.module._world_use(items.api, None, item_id=item_id)  # noqa: SLF001

        with pytest.raises(WorldError, match="物品不存在"):
            await _call_as(player.id, lambda: call("nope"))
        # 喇叭不可使用（use_action 为空）
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="megaphone", count=1
        )
        with pytest.raises(WorldError, match="不能使用"):
            await _call_as(player.id, lambda: call("megaphone"))

    _run(_scenario(tmp_path / "world.db", fn))
