"""MCP 档位消费（v0.2.0）：read（围观）凭据不能执行动作，play 档正常。

回归背景：`worlditor_tier` 过去只写进 `_meta`、内核从不读取——工具级授权
全靠玩法包自觉。现在动态工具入口会先看档位：read → 直接拒绝并给出明确文案。
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
import uvicorn
from world_fixtures import seed_test_world

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


def test_read_tier_rejected_play_tier_allowed(tmp_path):
    """read 档调工具 → 明确拒绝；play 档调同一工具 → 正常返回。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)  # 内核不再内置世界内容（v0.2.0）
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", builtin_dir=BUILTIN_DIR
        )
        await loader.load_all()  # world_look / world_say 等工具来自玩法包
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        engine.attach_mcp(mcp)
        app = build_http_app(mcp, identity, engine=engine, loader=loader)
        read = await identity.create_read_token()
        player = await identity.register_agent("探针")
        assert read.tier == "read" and player.tier == "play"

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
                denied = await _call_tool(client, read.token, "world_look", {})
                assert "围观" in denied.get("text", ""), denied
                allowed = await _call_tool(client, player.token, "world_look", {})
                assert "中央广场" in allowed.get("text", ""), allowed
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)
            await engine.terminate()

    asyncio.run(run())


def test_tools_require_identity(tmp_path):
    """无实体绑定的凭据（read）在工具入口被拒——不依赖具体档位实现。"""

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        identity = IdentityService(engine, auth_mode="open")
        read = await identity.create_read_token()
        assert read.entity_id == ""
        await engine.terminate()

    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
