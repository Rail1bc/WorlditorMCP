"""世界激活真生效（v0.3.0 / D15 + G15）：四条路径按"所在世界"过滤。

回归背景：v0.2.x 只有**事件**与**交互**按世界过滤（`_binding_active` /
`interact`），MCP 工具、原语覆盖与过滤器、kind 阻挡、玩家视图仍全局生效——
"每世界启停玩法包"配了等于摆设。本模块守住四条路径：

1. MCP 工具：调用者所在世界未启用该包 → 明确拒绝（端到端走真实 HTTP + MCP 会话）
2. 玩家视图：`GET /views` 按调用者世界过滤（tab 不出现）
3. 原语：覆盖/过滤器所属包在该世界未启用 → 视为不存在（回落内核默认实现）
4. kind：`block_move` 与可用动作列表按世界过滤
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
from world_fixtures import seed_test_world

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
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        engine.attach_mcp(mcp)
        app = build_http_app(mcp, identity, engine=engine, loader=loader)
        player = await identity.register_agent("世界探针")
        assert player.entity_id, "玩家应有实体（测试世界已铺地图）"

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
                looked = await _call_tool(client, player.token, "world_look", {})
                assert "中央广场" in looked.get("text", ""), looked
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} >= {"items", "movement", "social_log"}

                # 只留 social：movement/items 在该世界失效
                await engine.update_world("default", play_ids=["worlditor_play_social"])
                denied = await _call_tool(client, player.token, "world_look", {})
                assert "未启用该玩法包" in denied.get("text", ""), denied
                assert "worlditor_play_movement" in denied.get("text", ""), denied
                said = await _call_tool(
                    client, player.token, "world_say", {"text": "还在"}
                )
                assert "还在" in said.get("text", ""), said
                views = (await client.get("/views", headers=h)).json()["views"]
                assert {v["key"] for v in views} == {"social_log"}, views

                # 放开 → 恢复
                await engine.update_world("default", play_ids=[])
                restored = await _call_tool(client, player.token, "world_look", {})
                assert "中央广场" in restored.get("text", ""), restored
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)
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


def test_kind_block_and_actions_follow_world(tmp_path):
    """kind 声明的阻挡/动作按世界过滤：未激活该包的世界里，墙不挡、动作不出现。"""

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
                "wall",
                block_move=True,
                interactions=("knock",),
                play_id="pkg_wall",
            )
            wall = await engine.place_entity("wall", "default", -1, 0, name="北墙")
            player = await engine.place_entity("player", "default", 0, 0, name="小明")

            # 默认世界全部激活：墙挡路 + 动作可见
            assert "knock" in engine.available_actions(wall.id)
            with pytest.raises(WorldError, match="挡住"):
                await engine.move(player.id, "up")
            result = await engine.interact(player.id, wall.id, "knock")
            assert result.text == "咚"

            # 世界 B 不激活 pkg_wall：不挡路、动作不可见、交互被拒
            await engine.create_world("w_b", "B", play_ids=["other_pkg"])
            await engine.assign_map("default", "w_b")
            assert engine.available_actions(wall.id) == []
            scene = await engine.move(player.id, "up")
            assert (scene.row, scene.col) == (-1, 0), "未激活世界里墙不挡路"
            with pytest.raises(Exception, match="没有"):
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
