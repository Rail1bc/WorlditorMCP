"""worlditor_play_social 内置包测试（D1 说话通道落地）。

覆盖：cell 说话（emit say + 日志）、world 广播（喇叭消耗 + 冷却）、
world_log 工具、日志视图注册。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
SOCIAL_ID = "worlditor_play_social"
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


def test_social_play_loaded(tmp_path):
    """加载：world_say/world_log 工具 + 日志视图 + requires items。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert SOCIAL_ID in ids and ITEMS_ID in ids
        assert ids.index(ITEMS_ID) < ids.index(SOCIAL_ID)
        tools = {t["name"] for t in engine.list_tools()}
        assert {"world_say", "world_log"} <= tools
        views = {v["key"]: v for v in engine.list_views()}
        assert views["social_log"]["provider"]["url"] == (
            f"/plays/{SOCIAL_ID}/web/log.js"
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_cell_say(tmp_path):
    """cell 说话：emit say 事件（带位置）+ 写日志。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        social = next(p for p in plays if p.play_id == SOCIAL_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        seen = []
        engine.register_world_event("say", lambda api, data: seen.append(data))

        async def say():
            return await social.module._world_say(  # noqa: SLF001
                social.api, None, text="大家好呀"
            )

        result = await _call_as(player.id, say)
        assert result["scope"] == "cell"
        assert seen and seen[0]["text"] == "大家好呀"
        assert seen[0]["entity_id"] == player.id
        assert seen[0]["map_id"] == "default"
        # 日志已写（log=True）
        log = await engine.list_world_log()
        assert any(e["kind"] == "say" for e in log)

    _run(_scenario(tmp_path / "world.db", fn))


def test_cell_say_empty(tmp_path):
    """空 text → WorldError。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        social = next(p for p in plays if p.play_id == SOCIAL_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def say():
            return await social.module._world_say(social.api, None, text="  ")  # noqa: SLF001

        with pytest.raises(WorldError, match="不能为空"):
            await _call_as(player.id, say)

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_broadcast(tmp_path):
    """world 广播：消耗喇叭 + emit broadcast + 冷却生效。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        social = next(p for p in plays if p.play_id == SOCIAL_ID)
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="megaphone", count=2
        )
        seen = []
        engine.register_world_event("broadcast", lambda api, data: seen.append(data))

        async def say():
            return await social.module._world_say(  # noqa: SLF001
                social.api, None, text="全镇集合！", scope="world"
            )

        result = await _call_as(player.id, say)
        assert result["scope"] == "world"
        assert seen and seen[0]["text"] == "全镇集合！"
        # 喇叭 -1
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="megaphone"
            )
            == 1
        )
        # 冷却：立即再广播 → 拒绝
        with pytest.raises(WorldError, match="冷却"):
            await _call_as(player.id, say)
        # 冷却过期后可再广播
        from worlditor_mcp.builtin_plays.worlditor_play_social import (
            main as social_main,
        )

        # 直接把冷却时间改到过去
        raw = None
        for k, v in engine.store.play_data.items():
            if k[0] == SOCIAL_ID and k[1].startswith("broadcast_cd:"):
                raw = (k[1], v)
        assert raw is not None
        await engine.kv_set(
            SOCIAL_ID, raw[0], time.time() - social_main.BROADCAST_COOLDOWN_SECONDS - 1
        )
        await _call_as(player.id, say)
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="megaphone"
            )
            == 0
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_broadcast_no_megaphone(tmp_path):
    """没有喇叭 → WorldError。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        social = next(p for p in plays if p.play_id == SOCIAL_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def say():
            return await social.module._world_say(  # noqa: SLF001
                social.api, None, text="hi", scope="world"
            )

        with pytest.raises(WorldError, match="喇叭"):
            await _call_as(player.id, say)

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_log_tool(tmp_path):
    """world_log 工具：读取最近日志。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        social = next(p for p in plays if p.play_id == SOCIAL_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await _call_as(
            player.id,
            lambda: social.module._world_say(social.api, None, text="你好"),  # noqa: SLF001
        )

        async def log():
            return await social.module._world_log(social.api, None, limit=10)  # noqa: SLF001

        result = await _call_as(player.id, log)
        assert len(result["entries"]) >= 1
        assert any(e["kind"] == "say" for e in result["entries"])
        # 非法 limit
        with pytest.raises(WorldError, match="limit"):
            await _call_as(
                player.id, lambda: social.module._world_log(social.api, None, limit=0)
            )  # noqa: SLF001

    _run(_scenario(tmp_path / "world.db", fn))
