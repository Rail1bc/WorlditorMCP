"""服务装配测试：WorlditorService 生命周期 + HTTP app 装配。

替代插件时代 test_main_wires_v3_and_v4 / test_main_enable_world_api
（main.py 已由 app.py/cli.py 取代）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from worlditor_mcp.app import WorlditorService
from worlditor_mcp.config import Settings


def _run(coro):
    return asyncio.run(coro)


def test_service_wires_and_seeds(tmp_path):
    """start：空库播种（41 地块 + 3 种子实体）；stop：连接干净关闭。"""
    settings = Settings(data_dir=tmp_path, port=0)
    service = WorlditorService(settings)
    _run(service.start())
    try:
        assert len(service.engine.list_locations()) == 41
        assert len(service.engine.list_entities()) == 3
        assert service.identity is not None
        assert service.mcp_server is not None
    finally:
        _run(service.stop())
        assert service.play_loader.plays == {}
        assert service.engine.store._conn is None  # 连接已关闭


def test_service_build_app_serves(tmp_path):
    """build_app：认证/注册/静态端点可用（httpx ASGI 直调）。"""

    async def scenario():
        settings = Settings(data_dir=tmp_path, port=0)
        service = WorlditorService(settings)
        await service.start()
        app = service.build_app()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                # agent 注册（开放模式）
                resp = await client.post("/auth/agent-register", json={"name": "探针"})
                assert resp.status_code == 200, resp.text
                token = resp.json()["token"]["token"]
                # 认证后访问快照
                resp = await client.get(
                    "/state", headers={"Authorization": f"Bearer {token}"}
                )
                assert resp.status_code == 200
                assert len(resp.json()["locations"]) == 41
                # 未认证被拒
                resp = await client.get("/state")
                assert resp.status_code == 401
        finally:
            await service.stop()

    _run(scenario())


def test_cli_serve_argparse():
    """CLI 参数解析：serve 子命令 + 覆盖 Settings。"""
    from worlditor_mcp.cli import _parse_args, _settings_from_args

    args = _parse_args(
        ["serve", "--port", "9999", "--data-dir", "x", "--admin-key", "k"]
    )
    assert args.command == "serve"
    settings = _settings_from_args(args)
    assert settings.port == 9999
    assert settings.data_dir == Path("x")
    assert settings.admin_key == "k"
