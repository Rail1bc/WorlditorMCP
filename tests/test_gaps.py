"""G1/G2/G11/G12 测试：地图可见性 / delete_map / 数组参数 / 隐身过滤。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_dynamic_tool
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> V4WorldEngine:
    engine = V4WorldEngine(V4WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


# ---------- G2 delete_map ----------


def test_delete_map_cascade(tmp_path):
    """delete_map：级联删地块/实体/背包/归属；图上玩家在场拒绝。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.create_map("raid1", "对局1")
            await engine.create_location("raid1", 0, 0, "起点")
            await engine.create_location("raid1", 1, 0, "终点")
            npc = await engine.place_entity("wolf", "raid1", 0, 0, name="狼")
            await engine.give_item(npc.id, "apple", 3)
            await engine.assign_map("raid1", "default")
            # 图上玩家在场 → 拒绝
            player = await engine.place_entity("player", "raid1", 0, 0, name="小明")
            with pytest.raises(WorldError, match="玩家/agent"):
                await engine.delete_map("raid1")
            # 玩家离开后可删
            await engine.move_entity(player.id, "default", 0, 0)
            await engine.delete_map("raid1")
            assert engine.get_map("raid1") is None
            assert engine.get_location("raid1", 0, 0) is None
            assert engine.get_entity(npc.id) is None
            assert engine.map_world("raid1") is None
            # 不存在报错
            with pytest.raises(WorldError, match="不存在"):
                await engine.delete_map("raid1")
            # 玩法包 API 可调
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            await api.create_map("raid2", "对局2")
            await api.delete_map("raid2")
            assert engine.get_map("raid2") is None
        finally:
            await engine.terminate()

    _run(fn())


# ---------- G11 数组参数 ----------


def test_array_tool_param_schema(tmp_path):
    """array 参数：schema 生成 {"type":"array","items":{"type":"string"}}。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.register_tool(
                "world_msg",
                lambda api, ctx, **kw: {"text": "ok"},
                description="群发消息",
                params={"to": "array", "text": "string"},
            )
            binding = engine._tools["world_msg"]  # noqa: SLF001
            dyn = build_dynamic_tool(engine, binding, "world_msg")
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("t")
            mcp.add_tool(dyn, name="world_msg", description="群发消息")
            tools = await mcp.list_tools()
            tool = next(t for t in tools if t.name == "world_msg")
            props = tool.inputSchema["properties"]
            assert props["to"]["type"] == "array"
            assert props["to"]["items"]["type"] == "string"
            # 非法类型仍拒绝
            with pytest.raises(WorldError, match="参数类型"):
                api.register_tool(
                    "bad_tool", lambda api, ctx: "x", params={"a": "object"}
                )
        finally:
            await engine.terminate()

    _run(fn())


# ---------- G1 地图可见性 ----------


async def _state_scenario(tmp_path, fn):
    engine = await _engine(tmp_path)
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0")
    await loader.load_all()
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
    from worlditor_mcp.world.mcp import build_mcp_server
    from worlditor_mcp.world.mcp.http import build_http_app

    mcp = build_mcp_server(engine)
    engine.attach_mcp(mcp)
    app = build_http_app(mcp, identity, engine=engine, loader=loader)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await fn(client, identity, engine)
    finally:
        await engine.terminate()


def test_map_visibility_state_filter(tmp_path):
    """G1：private 地图对非在场玩家隐藏（/state 过滤）；在场可见；admin 全见。"""

    async def fn(client, identity, engine):
        await engine.create_map("home_a", "A的家", visible="private")
        await engine.create_location("home_a", 0, 0, "客厅")
        await engine.place_entity("sofa", "home_a", 0, 0, name="沙发")
        # 玩家 B（不在 A 家）看不到 private 图
        b = await identity.register_human("bob", "pass123")
        hb = {"Authorization": f"Bearer {b.token}"}
        state = (await client.get("/state", headers=hb)).json()
        assert {m["id"] for m in state["maps"]} == {"default"}
        # 玩家 A 传送进家 → 在场可见
        await engine.move_entity(b.entity_id, "home_a", 0, 0)
        state = (await client.get("/state", headers=hb)).json()
        assert {m["id"] for m in state["maps"]} == {"default", "home_a"}
        home = next(m for m in state["maps"] if m["id"] == "home_a")
        assert home["visible"] == "private"
        assert any(loc["map_id"] == "home_a" for loc in state["locations"])
        assert any(e["map_id"] == "home_a" for e in state["entities"])
        # read 档（无实体）看不到 private
        read = (await client.get("/auth/read-token")).json()["token"]["token"]
        hr = {"Authorization": f"Bearer {read}"}
        state = (await client.get("/state", headers=hr)).json()
        assert {m["id"] for m in state["maps"]} == {"default"}
        # admin 全见
        admin = await identity.register_human("owner", "pass123", admin_key="sekret")
        ha = {"Authorization": f"Bearer {admin.token}"}
        state = (await client.get("/state", headers=ha)).json()
        assert "home_a" in {m["id"] for m in state["maps"]}

    _run(_state_scenario(tmp_path, fn))


# ---------- G12 隐身过滤 ----------


def test_invisible_filter(tmp_path):
    """G12：invisible 实体对普通 viewer 隐藏；自己可见；see_invisible 真视。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            spy = await engine.place_entity(
                "player", "default", 0, 0, name="潜行者", attrs={"invisible": True}
            )
            guard = await engine.place_entity("player", "default", 0, 0, name="守卫")
            # 守卫看不到潜行者
            peers = engine.list_entities(viewer_id=guard.id)
            assert spy.id not in {e.id for e in peers}
            # 潜行者自己可见
            peers = engine.list_entities(viewer_id=spy.id)
            assert spy.id in {e.id for e in peers}
            # 无 viewer（机制层/管理）不过滤
            all_entities = engine.list_entities()
            assert spy.id in {e.id for e in all_entities}
            # 守卫获得真视
            await engine.set_attrs(guard.id, {"see_invisible": True})
            peers = engine.list_entities(viewer_id=guard.id)
            assert spy.id in {e.id for e in peers}
        finally:
            await engine.terminate()

    _run(fn())
