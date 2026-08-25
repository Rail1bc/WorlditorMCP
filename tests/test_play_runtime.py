"""玩法包运行时开放测试（D2/G2 动态工具、G8 emit、D15 世界激活、D14 编辑开放）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from play_fixtures import install_demo_play

from worlditor_mcp.world.mcp import build_dynamic_tool
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _make(tmp_path: Path) -> tuple[V4WorldEngine, PlayLoader]:
    engine = V4WorldEngine(V4WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0")
    return engine, loader


# ---------- 动态工具（D2 / G2） ----------


def test_register_tool_and_conflict(tmp_path):
    """register_tool：注册成功；同名冲突报错（D2）；清理恢复。"""

    async def fn():
        engine, _ = await _make(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.register_tool(
                "world_feed",
                lambda api, ctx, **kw: "喂了",
                description="喂食",
                params={"pet_id": "string"},
            )
            assert "world_feed" in engine._tools  # noqa: SLF001
            with pytest.raises(WorldError, match="冲突"):
                api.register_tool("world_feed", lambda api, ctx: "x")
            # 非法参数类型
            with pytest.raises(WorldError, match="参数类型"):
                api.register_tool("bad_tool", lambda api, ctx: "x", params={"a": "obj"})
            # 清理恢复
            engine.clear_play_registrations("pkg_a")
            assert engine.list_tools() == []
        finally:
            await engine.terminate()

    _run(fn())


def test_build_dynamic_tool_schema(tmp_path):
    """build_dynamic_tool：签名与 FastMCP schema 正确（参数类型映射）。"""

    async def fn():
        engine, _ = await _make(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.register_tool(
                "world_heal",
                lambda api, ctx, **kw: {"text": "ok"},
                description="治疗",
                params={"amount": "integer", "target": "string"},
            )
            binding = engine._tools["world_heal"]  # noqa: SLF001
            dyn = build_dynamic_tool(engine, binding, "world_heal")
            # 签名参数：ctx + amount(int) + target(str)，均为关键字
            sig = dyn.__signature__
            assert set(sig.parameters) == {"ctx", "amount", "target"}
            assert sig.parameters["amount"].annotation is int
            assert sig.parameters["target"].annotation is str
            # FastMCP schema 生成（进程内 mcp 实例 add_tool 后 list）
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("t")
            mcp.add_tool(dyn, name="world_heal", description="治疗")
            tools = await mcp.list_tools()
            tool = next(t for t in tools if t.name == "world_heal")
            props = tool.inputSchema["properties"]
            assert props["amount"]["type"] == "integer"
            assert props["target"]["type"] == "string"
        finally:
            await engine.terminate()

    _run(fn())


def test_dynamic_tool_call_with_identity(tmp_path):
    """动态工具调用：身份注入（api.caller()）+ 返回值结构化。"""

    async def fn():
        engine, _ = await _make(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)

            async def who_am_i(api, ctx, **kw):
                return {"text": f"我是 {api.caller()}"}

            api.register_tool("world_whoami", who_am_i, description="我是谁")
            binding = engine._tools["world_whoami"]  # noqa: SLF001
            dyn = build_dynamic_tool(engine, binding, "world_whoami")

            class FakeMeta:
                worlditor_entity_id = "entity_1"
                worlditor_tier = "play"

            class FakeReqCtx:
                meta = FakeMeta()

            class FakeCtx:
                def __init__(self):
                    self.request_context = FakeReqCtx()

            result = await dyn(FakeCtx())
            payload = json.loads(result)
            assert payload["text"] == "我是 entity_1"
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 自定义事件（G8 / D1） ----------


def test_emit_custom_event(tmp_path):
    """emit：任意事件名订阅 + SSE payload + log 控制。"""

    async def fn():
        engine, _ = await _make(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            received = []

            async def on_custom(api, data):
                received.append(data)

            api.register_world_event("my_custom_event", on_custom)
            await api.emit("my_custom_event", {"hello": "world"})
            assert received == [{"hello": "world"}]
            # 默认不写 world_log
            logs = await engine.store.list_world_log(limit=10)
            assert all(row["kind"] != "my_custom_event" for row in logs)
            # log=True 写入
            await api.emit("my_custom_event", {"a": 1}, log=True)
            logs = await engine.store.list_world_log(limit=10)
            assert any(row["kind"] == "my_custom_event" for row in logs)
            # SSE payload 泛化
            payload = engine._event_payload("my_custom_event", ({"a": 1},))
            assert payload["event"] == "my_custom_event"
            assert payload["data"] == {"a": 1}
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 世界激活过滤（D15） ----------


def test_world_activation_filter(tmp_path):
    """世界激活：未激活玩法包的交互不可用；激活后可交互。"""

    async def fn():
        install_demo_play(tmp_path / "plays")
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        try:
            # 默认世界 play_ids 空 = 全部激活 → 商贩可 talk
            merchant = [e for e in engine.list_entities() if e.kind == "merchant"][0]
            player = await engine.place_entity("player", "default", 0, 0, name="小明")
            result = await engine.interact(player.id, merchant.id, "talk")
            assert "阿福" in result.text
            # 建世界 B：只激活一个不存在的包 → demo 包未激活
            await engine.create_world("w_b", "世界B", play_ids=["worlditor_play_x"])
            # 把地图归属到世界 B
            await engine.assign_map("default", "w_b")
            with pytest.raises(WorldError, match="没有"):
                await engine.interact(player.id, merchant.id, "talk")
            # 激活 demo 包 → 恢复可用
            await engine.update_world("w_b", play_ids=["worlditor_play_demo"])
            result = await engine.interact(player.id, merchant.id, "talk")
            assert "阿福" in result.text
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 编辑原语开放（D14） ----------


def test_edit_primitives_via_api(tmp_path):
    """玩法包 API 编辑：spawn/despawn + 建地图 + 模板。"""

    async def fn():
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            # spawn
            npc = await api.place_entity(
                "wolf", "default", 0, 0, name="野狼", attrs={"hp": 10}
            )
            assert npc.id in engine.store.entities
            # despawn
            await api.remove_entity(npc.id)
            assert npc.id not in engine.store.entities
            # 建地图（含默认地块归属校验：新地图无地块也可创建）
            m = await api.create_map("arena", "竞技场")
            assert engine.get_map("arena") is not None
            # 模板
            from worlditor_mcp.world.v3model import WorldTemplate

            await api.save_template(WorldTemplate(id="t1", name="模板1", data={}))
            assert "t1" in engine.store.templates
            await api.delete_template("t1")
            assert "t1" not in engine.store.templates
        finally:
            await engine.terminate()

    _run(fn())
