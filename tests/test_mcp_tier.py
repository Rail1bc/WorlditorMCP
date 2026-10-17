"""MCP 档位消费：**play 档正常执行动作**；`read`（围观）档在 v0.9 已整体删除。

回归背景：`worlditor_tier` 过去只写进 `_meta`、内核从不读取——工具级授权
全靠玩法包自觉。v0.2.0 起动态工具入口先看档位；v0.9（D53）删掉 read 档后，
这里守的是两件事：①play 档不被误拦；②read 档**不会回来**（签发方法、
拒绝分支都不该再存在）。
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
import uvicorn
from play_fixtures import install_demo_play
from world_fixtures import give_avatar, seed_test_world

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_mcp_server
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tier-test", "version": "0"},
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
    """按 streamable HTTP 会话流程调用一个工具，返回解析后的工具负载。"""
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
    body = _sse_json(resp.text) or {}
    content = (body.get("result") or {}).get("content") or []
    text = content[0].get("text", "") if content else ""
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def test_play_tier_can_call_tools(tmp_path):
    """play 档调工具 → 正常返回（read 围观档已随 v0.9 删除，没有"只能看"的档位了）。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)  # 内核不再内置世界内容（v0.2.0）
        install_demo_play(tmp_path / "plays")  # v0.7.0：工具来自夹具玩法包
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        engine.attach_mcp(mcp)
        app = build_http_app(mcp, identity, engine=engine, loader=loader)
        player = await identity.register_agent("探针")
        assert player.tier == "play"
        assert not hasattr(identity, "create_read_token")  # v0.9：围观档已删除
        # D45/D46：play 档要有化身才调得动"需要身体"的工具（造 → 认领 → 指过去）
        await give_avatar(engine, player, name="探针")

        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(0.05)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=20.0, trust_env=False
            ) as client:
                allowed = await _call_tool(client, player.token, "world_whoami", {})
                assert "我是" in allowed.get("text", ""), allowed
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)
            await engine.terminate()

    asyncio.run(run())


def test_tools_require_identity(tmp_path):
    """没有化身的 play 凭据是合法状态（D45）；工具闸门看的是"有没有身体"，不是档位。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        identity = IdentityService(engine, auth_mode="open")
        # v0.9：read 围观档删除——"能读但没有身体"的最小身份就是 play 档
        info = await identity.register_agent("还没身体")
        assert info.tier == "play" and info.entity_id == ""
        await engine.terminate()

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
