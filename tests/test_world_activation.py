"""世界激活真生效（v0.3.0 / D15 + G15）：四条路径按"所在世界"过滤。

回归背景：v0.2.x 只有**事件**与**交互**按世界过滤（`_binding_active` /
`interact`），MCP 工具、原语覆盖与过滤器、kind 阻挡、玩家视图仍全局生效——
"每世界启停玩法包"配了等于摆设。本模块守住四条路径：

1. MCP 工具：调用者所在世界未启用该包 → 明确拒绝（端到端走真实 HTTP + MCP 会话）
2. 玩家视图：`GET /views` 按调用者世界过滤（tab 不出现）
3. 原语：覆盖/过滤器所属包在该世界未启用 → 视为不存在（回落内核默认实现）
4. 组件：声明的可用动作列表按世界过滤（`block_move` 已随 D34 整体移除，
   未激活包里声明的东西不生效改用 `interactions` 观测——D41：能力 = 组件的存在）
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
from play_fixtures import install_demo_play, install_probe_play
from world_fixtures import give_avatar, seed_test_world

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_mcp_server
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.model import UiBlock
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "world-activation", "version": "0"},
    },
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _sse_json(text: str):
    if text.lstrip().startswith("event:"):
        for line in text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        return None
    return json.loads(text) if text.strip() else None


async def _call_tool(client, token: str, name: str, args: dict) -> dict:
    """streamable HTTP 会话流程调用工具，返回解析后的负载。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    init = await client.post("/world/mcp", json=_INIT, headers=headers)
    assert init.status_code == 200, init.text
    session = init.headers.get("mcp-session-id", "")
    assert session, "未取得 MCP 会话"
    await client.post(
        "/world/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**headers, "Mcp-Session-Id": session},
    )
    resp = await client.post(
        "/world/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
        headers={**headers, "Mcp-Session-Id": session},
    )
    assert resp.status_code == 200, resp.text
    content = (_sse_json(resp.text) or {}).get("result", {}).get("content") or []
    text = content[0].get("text", "") if content else ""
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def test_tools_and_views_follow_world_activation(tmp_path):
    """端到端：收窄世界激活集合 → 工具被拒、视图消失；放开 → 恢复。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        # v0.7.0：内置玩法包已废弃——用两个测试夹具包做激活对比
        # （demo = 工具 world_whoami + 视图 demo；probe = 工具 world_ping + 视图 ping）
        install_demo_play(tmp_path / "plays")
        install_probe_play(tmp_path / "plays")
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        engine.attach_mcp(mcp)
        app = build_http_app(mcp, identity, engine=engine, loader=loader)
        player = await identity.register_agent("世界探针")
        # D45/D46：注册不建实体——以玩家身份调工具前先给一具化身
        # （造 → 认领 → 指过去；这正是玩法包做的事）
        await give_avatar(engine, player, name="世界探针")

        port = _free_port()
        server = uvicorn_server(app, port)
        task = asyncio.create_task(server.serve())
        try:
            await _wait_port(port)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=20.0, trust_env=False
            ) as client:
                h = {"Authorization": f"Bearer {player.token}"}
                # 基线：默认世界 play_ids=[]（全部激活）
                who = await _call_tool(client, player.token, "world_whoami", {})
                assert "我是" in who.get("text", ""), who
                pinged = await _call_tool(client, player.token, "world_ping", {})
                assert "pong" in pinged.get("text", ""), pinged
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} >= {"demo", "ping"}

                # 只留 demo：probe 在该世界失效
                await engine.update_world("default", play_ids=["worlditor_play_demo"])
                denied = await _call_tool(client, player.token, "world_ping", {})
                assert "未启用该玩法包" in denied.get("text", ""), denied
                assert "worlditor_play_probe" in denied.get("text", ""), denied
                still = await _call_tool(client, player.token, "world_whoami", {})
                assert "我是" in still.get("text", ""), still
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} == {"demo"}, views

                # 放开 → 恢复
                await engine.update_world("default", play_ids=[])
                restored = await _call_tool(client, player.token, "world_ping", {})
                assert "pong" in restored.get("text", ""), restored
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)
            await engine.terminate()

    asyncio.run(run())


def test_views_filter_uses_caller_world_not_default(tmp_path):
    """G33（v0.5.2）：`/views` 必须按**调用者所在世界**过滤，而不是"默认世界"。

    原先 `/views` 挂在免认证公共路径上，中间件遇到公共路径**直接放行、不解析
    token** → `_identity_of()` 恒为 None → 过滤退化成匿名（= 默认世界的激活集合）。
    默认世界通常是"全部启用"，所以只在默认世界里测（旧测试就是）永远发现不了；
    这里让玩家站到另一个世界里。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)  # 默认世界的地图
        install_demo_play(tmp_path / "plays")
        install_probe_play(tmp_path / "plays")
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        app = build_http_app(mcp, identity, engine=engine, loader=loader)
        try:
            # 乙世界：只启用 demo；玩家站在乙世界的地图上
            await engine.create_world(
                "world_b", "乙世界", play_ids=["worlditor_play_demo"]
            )
            await engine.create_map("m_b", "乙世界地图")
            await engine.create_location("m_b", 0, 0, "乙世界广场")
            await engine.assign_map("m_b", "world_b")
            player = await identity.register_agent("世界探针")
            avatar = await give_avatar(engine, player, name="世界探针")
            await engine.move_entity(avatar.id, "m_b", 0, 0)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://play"
            ) as client:
                h = {"Authorization": f"Bearer {player.token}"}
                # 已登录：按玩家所在世界 → 只有 demo 的视图
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} == {"demo"}, views

                # 匿名（无凭据）仍按默认世界算（默认世界全启用，视图齐全）
                anon = (await client.get("/views")).json()["views"]
                assert {v["key"] for v in anon} >= {"demo", "ping"}

                # 放开乙世界 → 恢复
                await engine.update_world("world_b", play_ids=[])
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} >= {"demo", "ping"}
        finally:
            await engine.terminate()

    asyncio.run(run())


def test_primitive_filter_follows_world(tmp_path):
    """原语过滤器：挂过滤器的包在该世界未启用 → 过滤器不参与（默认实现生效）。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        try:
            api = WorlditorPlayAPI(engine, "pkg_filter")
            engine.attach_play_api("pkg_filter", api)
            seen: list[str] = []

            def _no_north(api, **params):
                seen.append(params["direction"])
                # 把 up 改写成 down（过滤器改参语义）
                return {
                    **params,
                    "direction": "down"
                    if params["direction"] == "up"
                    else params["direction"],
                }

            engine.register_primitive_filter("move", _no_north, play_id="pkg_filter")
            player = await engine.place_entity("player", "default", 0, 0, name="小明")

            # 世界 A（默认世界，空 = 全部激活）：过滤器生效 → up 被改写成 down
            scene = await engine.move(player.id, "up")
            assert seen == ["up"], seen
            assert (scene.row, scene.col) == (1, 0), (scene.row, scene.col)

            # 世界 B：只激活别的包 → 过滤器不生效（up 正常向北）
            await engine.create_world("w_b", "B", play_ids=["other_pkg"])
            await engine.assign_map("default", "w_b")
            await engine.move_entity(player.id, "default", 0, 0)
            seen.clear()
            scene = await engine.move(player.id, "up")
            assert seen == [], "未激活世界的过滤器不应被调用"
            assert (scene.row, scene.col) == (-1, 0), (scene.row, scene.col)
        finally:
            await engine.terminate()

    asyncio.run(run())


def test_component_actions_follow_world(tmp_path):
    """组件声明的动作按世界过滤：未激活该包的世界里，动作不出现也不能用。

    v2 第 1 期（D34）：阻挡机制**整体移除**，本用例的观测面从"墙挡路"换成
    ``available_actions`` / ``capabilities()["interactions"]``——它们与
    ``interact`` 的拒绝判定同源（D21 的同一条过滤路径）。
    D41：这里的 "wall" 是一个组件（声明者 = pkg_wall），实体带上它才具备 knock。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        try:
            api = WorlditorPlayAPI(engine, "pkg_wall")
            engine.attach_play_api("pkg_wall", api)

            async def _knock(api, req):
                from worlditor_mcp.world.model import InteractionResult

                return InteractionResult(text="咚")

            engine.register_interaction(
                "knock", _knock, label="敲门", play_id="pkg_wall"
            )
            engine.register_entity_kind(
                "wall", interactions=("knock",), play_id="pkg_wall"
            )
            wall = await engine.place_entity("wall", "default", -1, 0, name="北墙")
            # D41：kind 是输入便利——裸名解析到唯一声明者（pkg_wall）的组件键
            assert wall.has_component("pkg_wall:wall")
            player = await engine.place_entity("player", "default", 0, 0, name="小明")

            # 默认世界全部激活：动作可见且可用
            assert engine.available_actions(wall.id) == ["knock"]
            assert engine.capabilities(wall)["interactions"] == ["knock"]
            result = await engine.interact(player.id, wall.id, "knock")
            assert result.text == "咚"
            # D34：墙不再阻挡——移动在任何世界都照常（本用例不再拿阻挡当观测面）
            await engine.move(player.id, "up")
            assert player.pos_key() == ("default", -1, 0)

            # 世界 B 不激活 pkg_wall：动作不再出现、能力面为空、交互被拒
            await engine.create_world("w_b", "B", play_ids=["other_pkg"])
            await engine.assign_map("default", "w_b")
            assert engine.available_actions(wall.id) == []
            caps = engine.capabilities(wall)
            assert caps["interactions"] == []
            assert caps["active_components"] == []
            assert caps["inactive_components"] == ["pkg_wall:wall"]
            assert wall.has_component("pkg_wall:wall")  # 组件还在实体上，只是不生效
            with pytest.raises(WorldError, match="没有"):
                await engine.interact(player.id, wall.id, "knock")
        finally:
            await engine.terminate()

    asyncio.run(run())


def test_ui_hook_injection_follows_world(tmp_path):
    """部件注入（ui_hook）：注入方在该世界未启用 → 不注入。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        try:
            api = WorlditorPlayAPI(engine, "pkg_panel")
            engine.attach_play_api("pkg_panel", api)

            def _panel(api, block):
                return [UiBlock(kind="text", text="背包面板")]

            engine.register_ui_hook("character", "after", _panel, play_id="pkg_panel")
            player = await engine.place_entity("player", "default", 0, 0, name="小明")

            base = UiBlock(kind="character", text="角色卡")
            out = await engine.apply_ui_hooks(base, entity_id=player.id)
            assert len(out.blocks) == 1, "注入方激活 → 面板出现"

            await engine.create_world("w_b", "B", play_ids=["other_pkg"])
            await engine.assign_map("default", "w_b")
            base = UiBlock(kind="character", text="角色卡")
            out = await engine.apply_ui_hooks(base, entity_id=player.id)
            assert out.blocks == [], "注入方未激活 → 不注入"
        finally:
            await engine.terminate()

    asyncio.run(run())


def uvicorn_server(app, port: int):
    import uvicorn

    return uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )


async def _wait_port(port: int) -> None:
    for _ in range(100):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    raise AssertionError("服务端口未就绪")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
