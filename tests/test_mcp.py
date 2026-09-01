"""v4.1 MCP 测试：工具（进程内 call_tool）+ HTTP 认证中间件。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from play_fixtures import install_demo_play  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine  # noqa: E402
from worlditor_mcp.world.identity import IdentityService  # noqa: E402
from worlditor_mcp.world.mcp import build_dynamic_tool, build_mcp_server  # noqa: E402
from worlditor_mcp.world.mcp.http import (  # noqa: E402
    AuthMiddleware,
    _inject_identity,
)
from worlditor_mcp.world.play import PlayLoader  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _loads(text: str) -> dict:
    return json.loads(text)


def _content_text(result) -> str:
    """call_tool 返回兼容：list[ContentBlock] 或 (content, structured) 元组。"""
    if isinstance(result, tuple):
        result = result[0]
    return result[0].text


async def _make_world(tmp_path: Path):
    """引擎 + 演示玩法包 + 一个 agent 凭据（先加载玩法包，出生礼包才生效）。"""
    install_demo_play(tmp_path / "plays")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
    await loader.load_all(None)
    identity = IdentityService(engine, auth_mode="open")
    info = await identity.register_agent("测试探针")
    return engine, identity, info


async def _scenario(tmp_path: Path, fn):
    engine, identity, info = await _make_world(tmp_path)
    try:
        return await fn(engine, identity, info)
    finally:
        await engine.terminate()


# ---------- 工具（M2 后无内置工具：玩法包 register_tool 动态注册） ----------


def test_dynamic_tool_via_mcp(tmp_path):
    """MCP 动态工具：attach_mcp 后玩法包注册的工具可调用；身份经请求 _meta 注入。"""

    async def fn(engine, identity, info):
        mcp = build_mcp_server(engine)
        engine.attach_mcp(mcp)
        # 未 attach 的引擎工具集为空（M2 无内置工具）
        mcp2 = build_mcp_server(engine)
        tools = await mcp2.list_tools()
        assert tools == []
        # attach 后动态工具同步注册
        tools = await mcp.list_tools()
        names = {t.name if hasattr(t, "name") else t[0] for t in tools}
        assert "world_whoami" in names
        # 无请求上下文：身份不可用 → 认证守卫拒绝
        result = await mcp.call_tool("world_whoami", {})
        payload = _loads(_content_text(result))
        assert "未认证" in payload["text"]
        # 注入请求 _meta 后以连接实体身份执行（同 HTTP 路径的身份来源）
        meta = type(
            "Meta",
            (),
            {"worlditor_entity_id": info.entity_id, "worlditor_tier": info.tier},
        )()
        request_ctx = type("RequestContext", (), {"meta": meta})()
        ctx = type("Context", (), {"request_context": request_ctx})()
        tool = build_dynamic_tool(engine, engine._tools["world_whoami"], "world_whoami")
        result = await tool(ctx)
        payload = _loads(result)
        assert "我是" in payload["text"]

    _run(_scenario(tmp_path, fn))


# ---------- HTTP 认证中间件 ----------


def test_inject_identity_unit():
    """_inject_identity：JSON-RPC 单请求注入 _meta；异常 body 原样返回。"""
    info = type("I", (), {"entity_id": "e123", "tier": "play"})()
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "world_move", "arguments": {"direction": "up"}},
        }
    ).encode()
    out = json.loads(_inject_identity(body, info))
    assert out["params"]["_meta"]["worlditor_entity_id"] == "e123"
    assert out["params"]["_meta"]["worlditor_tier"] == "play"
    # 已有 _meta 合并保留
    body2 = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "x", "arguments": {}, "_meta": {"progressToken": 9}},
        }
    ).encode()
    out2 = json.loads(_inject_identity(body2, info))
    assert out2["params"]["_meta"]["progressToken"] == 9
    assert out2["params"]["_meta"]["worlditor_entity_id"] == "e123"
    # 非法 body / 批处理不炸
    assert _inject_identity(b"not json", info) == b"not json"
    assert _inject_identity(b"[1,2]", info) == b"[1,2]"
    assert _inject_identity(b"", info) == b""


def test_auth_middleware_rejects(tmp_path):
    """中间件：无/坏 token → 401（不触达内部 app）。"""

    async def fn(engine, identity, info):
        called = []
        middleware = AuthMiddleware(_stub_app(called), identity)
        # 无 Authorization
        status, body = await _call_asgi(middleware, headers={})
        assert status == 401 and "未认证".encode() in body
        assert called == []
        # 坏 token
        status, body = await _call_asgi(
            middleware, headers={"authorization": "Bearer badtoken"}
        )
        assert status == 401
        assert called == []

    _run(_scenario(tmp_path, fn))


def test_auth_middleware_injects_identity(tmp_path):
    """中间件：有效 token → 放行并把身份注入 POST body 的 _meta。"""

    async def fn(engine, identity, info):
        seen = {}

        async def recording_app(scope, receive, send):
            seen["scope"] = scope
            chunks = []
            while True:
                msg = await receive()
                chunks.append(msg.get("body") or b"")
                if not msg.get("more_body", False):
                    break
            seen["body"] = b"".join(chunks)
            await _send_ok(send)

        middleware = AuthMiddleware(recording_app, identity)
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        ).encode()
        status, _ = await _call_asgi(
            middleware,
            headers={"authorization": f"Bearer {info.token}"},
            body=body,
            method="POST",
        )
        assert status == 200
        parsed = json.loads(seen["body"])
        assert parsed["params"]["_meta"]["worlditor_entity_id"] == info.entity_id
        assert parsed["params"]["_meta"]["worlditor_tier"] == info.tier

    _run(_scenario(tmp_path, fn))


# ---------- ASGI 测试工具 ----------


def _stub_app(called: list):
    async def app(scope, receive, send):
        called.append(scope["path"])
        await _send_ok(send)

    return app


async def _send_ok(send):
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b"{}"})


async def _call_asgi(app, *, headers: dict, body: bytes = b"", method: str = "GET"):
    """最小 ASGI 调用：返回 (status, body)。"""
    scope = {
        "type": "http",
        "method": method,
        "path": "/world/mcp",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
        "client": ("test", 123),
        "scheme": "http",
        "server": ("test", 80),
        "http_version": "1.1",
    }
    body_sent = [False]

    async def receive():
        if not body_sent[0]:
            body_sent[0] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    status = [0]
    resp_body = bytearray()

    async def send(message):
        if message["type"] == "http.response.start":
            status[0] = message["status"]
        elif message["type"] == "http.response.body":
            resp_body.extend(message.get("body") or b"")

    await app(scope, receive, send)
    return status[0], bytes(resp_body)
