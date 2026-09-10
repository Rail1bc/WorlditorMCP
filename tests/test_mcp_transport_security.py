"""MCP 传输安全（Host / Origin 校验）：局域网 IP、域名访问不得 421。

回归背景（v0.1.16）：``FastMCP`` 在 ``host=127.0.0.1``（构造默认值）时会自动
开启 DNS rebinding 保护且只放行 localhost 变体 —— 用户从局域网 IP / 域名打开
玩家端时，视图内 MCP 初始化报 ``421 Invalid Host header``（"mcp 初始化失败
http421"）。修复 = 显式传入 transport_security（默认关闭 Host 校验；可用
``WORLDITOR_MCP_ALLOWED_HOSTS`` 收紧）。
"""

from __future__ import annotations

import asyncio
import socket

import httpx

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_mcp_server, build_transport_security
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_LAN_IP = "192.168.1.29"  # 任意非 localhost 地址：模拟局域网 / 域名访问


def _run(coro):
    return asyncio.run(coro)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------- 设置构造（单元） ----------


def test_transport_security_default_allows_any_host():
    """默认（未配置白名单）：关闭 Host 校验 → 局域网 IP / 域名可用。"""
    security = build_transport_security()
    assert security.enable_dns_rebinding_protection is False
    assert security.allowed_hosts == []


def test_transport_security_whitelist_port_and_origin_variants():
    """白名单：无端口条目补 ``:*`` 变体；Origin 按 http/https 同源派生。"""
    security = build_transport_security(["world.example.com", "10.0.0.7:6288", "[::1]"])
    assert security.enable_dns_rebinding_protection is True
    # 域名无端口 → 自动补带端口变体（浏览器 Host 头带端口）
    assert "world.example.com" in security.allowed_hosts
    assert "world.example.com:*" in security.allowed_hosts
    assert "10.0.0.7:6288" in security.allowed_hosts
    assert "[::1]:*" in security.allowed_hosts
    # Origin 派生（浏览器同源请求带 Origin 头，不派生则 403）
    assert "http://world.example.com:*" in security.allowed_origins
    assert "https://world.example.com" in security.allowed_origins
    # 显式 origins 覆盖派生
    explicit = build_transport_security(
        ["world.example.com"], ["https://world.example.com"]
    )
    assert explicit.allowed_origins == ["https://world.example.com"]


# ---------- 真实 uvicorn 端到端（Host 头回归） ----------


async def _probe(tmp_path, host_header: str, *, allowed_hosts=None, origin=None):
    """起真实 uvicorn，用指定 Host 头对 /world/mcp 发 initialize。

    Returns:
        httpx.Response（421 = SDK Host 校验拒绝）。
    """
    import uvicorn

    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
    await loader.load_all(None)
    identity = IdentityService(engine, auth_mode="open")
    mcp = build_mcp_server(engine, allowed_hosts=allowed_hosts)
    engine.attach_mcp(mcp)
    app = build_http_app(mcp, identity, engine=engine, loader=loader)
    info = await identity.register_agent("探针")
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
        headers = {
            "Authorization": f"Bearer {info.token}",
            "Host": host_header.format(port=port),
            "Accept": "application/json, text/event-stream",
        }
        if origin:
            headers["Origin"] = origin.format(port=port)
        # trust_env=False：绕开系统代理（代理会按 Host 头选目标 → 合成 Host 直接 502）
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            return await client.post(
                f"http://127.0.0.1:{port}/world/mcp", json=_INIT, headers=headers
            )
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        await engine.terminate()


def test_mcp_lan_host_not_rejected(tmp_path):
    """默认配置：Host = 局域网 IP（带 Origin）→ MCP 初始化成功（非 421）。"""
    resp = _run(
        _probe(
            tmp_path,
            f"{_LAN_IP}:{{port}}",
            origin=f"http://{_LAN_IP}:{{port}}",
        )
    )
    assert resp.status_code != 421, resp.text
    assert resp.status_code == 200, resp.text
    assert "protocolVersion" in resp.text


def test_mcp_domain_host_not_rejected(tmp_path):
    """默认配置：Host = 自定义域名（反代 / Docker 场景）→ 非 421。"""
    resp = _run(_probe(tmp_path, "world.example.com:{port}"))
    assert resp.status_code == 200, resp.text


def test_mcp_whitelist_enforced_when_configured(tmp_path):
    """显式白名单：放行名单内 Host，名单外仍 421（收紧能力有效）。"""
    allowed = _run(_probe(tmp_path, f"{_LAN_IP}:{{port}}", allowed_hosts=[_LAN_IP]))
    assert allowed.status_code == 200, allowed.text
    denied = _run(
        _probe(tmp_path, "evil.example.com:{port}", allowed_hosts=[_LAN_IP])
    )
    assert denied.status_code == 421, denied.text
