"""worlditor_play_interaction 内置包测试。

覆盖：种子实体 kind/交互注册、talk/trade/read/open、商贩购买（跨包 items
交货 + 金币扣减）、eat 效果、door 阻挡、world_interact 工具。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
INTERACTION_ID = "worlditor_play_interaction"
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


async def _call_as(player_id: str, coro_factory):
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


def _merchant(engine):
    return next(e for e in engine.list_entities() if e.kind == "merchant")


def test_interaction_play_loaded(tmp_path):
    """加载：3 种子 kind + 交互 + world_interact 工具。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        assert INTERACTION_ID in [p.play_id for p in plays]
        kinds = dict(engine._kind_specs)  # noqa: SLF001
        assert set(kinds) == {"merchant", "sign", "door"}
        assert kinds["door"].block_move is True
        interactions = set(engine._interactions)  # noqa: SLF001
        assert {
            "talk",
            "trade",
            "read",
            "open",
            "eat",
            "buy_apple",
            "buy_bread",
        } <= interactions
        tools = {t["name"] for t in engine.list_tools()}
        assert "world_interact" in tools

    _run(_scenario(tmp_path / "world.db", fn))


def test_talk_trade_read_open(tmp_path):
    """基础交互：talk/trade 菜单、read 文本、open 门状态。"""

    async def fn(engine, loader):
        await loader.load_all()
        merchant = _merchant(engine)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        # talk → text + 动作按钮
        result = await engine.interact(player.id, merchant.id, "talk")
        assert "阿福" in result.text
        assert result.ui is not None and result.ui.actions
        # trade → list 货单
        result = await engine.interact(player.id, merchant.id, "trade")
        assert result.ui is not None and result.ui.kind == "list"
        # read
        sign = next(e for e in engine.list_entities() if e.kind == "sign")
        result = await engine.interact(player.id, sign.id, "read")
        assert "小镇公告" in result.text
        # open：门 state 变更 + 阻挡解除
        door = next(e for e in engine.list_entities() if e.kind == "door")
        assert door.state.get("open") is False
        result = await engine.interact(player.id, door.id, "open")
        assert "吱呀" in result.text
        assert engine.get_state(door.id).get("open") is True

    _run(_scenario(tmp_path / "world.db", fn))


def test_door_blocks_move(tmp_path):
    """door kind block_move：注册后挡路，开门后可通行。"""

    async def fn(engine, loader):
        await loader.load_all()
        player = await engine.place_entity("player", "default", 2, 0, name="小明")
        # (2,0) 老路 → 南 (3,0) 林间路口（木门在此，种子数据）
        with pytest.raises(WorldError, match="挡住了"):
            await engine.move(player.id, "down")
        door = next(e for e in engine.list_entities() if e.kind == "door")
        await engine.interact(player.id, door.id, "open")
        scene = await engine.move(player.id, "down")
        assert (scene.row, scene.col) == (3, 0)

    _run(_scenario(tmp_path / "world.db", fn))


def test_buy_items_cross_play(tmp_path):
    """商贩购买：金币扣减 + items 包交货（跨包真实用例）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        merchant = _merchant(engine)
        player = await engine.place_entity(
            "player",
            "default",
            0,
            0,
            name="小明",
            attrs={"gold": 20, "starter_granted": True},  # 跳过 player 包礼包
        )
        # 买苹果（5金）
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert "苹果" in result.text
        assert engine.get_attrs(player.id)["gold"] == 15
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 1
        )
        # 买面包（3金）
        await engine.interact(player.id, merchant.id, "buy_bread")
        assert engine.get_attrs(player.id)["gold"] == 12
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="bread"
            )
            == 1
        )
        # 钱不够
        await engine.set_attrs(player.id, {"gold": 2})
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert "钱不够" in result.text
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 1
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_eat_effect(tmp_path):
    """eat：吃物品效果（energy+1）；持有扣减由 items world_use 负责。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player",
            "default",
            0,
            0,
            name="小明",
            attrs={"starter_granted": True},  # 跳过 player 包礼包
        )
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=1
        )
        # 经 items world_use 全链路：交互效果 + 持有扣减

        async def use():
            return await items.module._world_use(items.api, None, item_id="apple")  # noqa: SLF001

        result = await _call_as(player.id, use)
        assert "精力" in result["text"]
        assert engine.get_attrs(player.id).get("energy") == 1
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 0
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_interact_tool(tmp_path):
    """world_interact：agent 交互通道。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        interaction = next(p for p in plays if p.play_id == INTERACTION_ID)
        merchant = _merchant(engine)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def call(target_id, action):
            return await interaction.module._world_interact(  # noqa: SLF001
                interaction.api, None, target_id=target_id, action=action
            )

        result = await _call_as(player.id, lambda: call(merchant.id, "talk"))
        assert "阿福" in result["text"]
        assert result["ui"] is not None
        # 缺参数
        with pytest.raises(WorldError, match="必填"):
            await _call_as(player.id, lambda: call("", "talk"))

    _run(_scenario(tmp_path / "world.db", fn))
