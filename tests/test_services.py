"""跨包服务机制测试（M3：玩法包间同步调用通道）。

覆盖：注册/冲突、跨包调用、服务不存在、异常隔离、卸载清理、
管理端点可见性。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


def _make(db_path: Path) -> tuple[WorldEngine, WorlditorPlayAPI]:
    engine = WorldEngine(WorldStore(db_path))
    return engine, WorlditorPlayAPI(engine, "pkg_a")


def _scenario(db_path, fn):
    engine, api = _make(db_path)

    async def main():
        await engine.initialize()
        try:
            return await fn(engine, api)
        finally:
            await engine.terminate()

    return main()


def test_register_and_list(tmp_path):
    """注册服务 + 列表可见 + 同包同名冲突。"""

    async def fn(engine, api):
        engine.attach_play_api("pkg_a", api)

        async def _greet(api, **params):
            return f"hi {params.get('who', '?')}"

        api.register_service("greet", _greet)
        services = {s["name"]: s for s in engine.list_services()}
        assert services["greet"]["play_id"] == "pkg_a"
        # 同包同名冲突
        with pytest.raises(WorldError, match="冲突"):
            api.register_service("greet", _greet)
        # 空名/不可调用
        with pytest.raises(WorldError, match="不能为空"):
            api.register_service("", _greet)
        with pytest.raises(WorldError, match="可调用"):
            api.register_service("bad", None)

    _run(_scenario(tmp_path / "world.db", fn))


def test_cross_play_call(tmp_path):
    """跨包调用：pkg_b 调 pkg_a 的服务（提供者 api 操作自己的数据）。"""

    async def fn(engine, api_a):
        engine.attach_play_api("pkg_a", api_a)
        api_b = WorlditorPlayAPI(engine, "pkg_b")
        engine.attach_play_api("pkg_b", api_b)

        async def _kv_get(api, **params):
            # 服务 handler 用提供者自己的 api（读写提供者的 namespace）
            return api.kv_get(params["key"], params.get("default"))

        api_a.register_service("kv_get", _kv_get)
        await api_b.kv_set("secret", 42)
        # pkg_b 读不到 pkg_a 的 kv（namespace 隔离）
        assert await api_b.call_service("pkg_a", "kv_get", key="secret") is None
        await api_a.kv_set("secret", 7)
        assert await api_b.call_service("pkg_a", "kv_get", key="secret") == 7

    _run(_scenario(tmp_path / "world.db", fn))


def test_service_not_found(tmp_path):
    """服务不存在 / 提供方未加载 → WorldError。"""

    async def fn(engine, api):
        engine.attach_play_api("pkg_a", api)
        with pytest.raises(WorldError, match="服务不存在"):
            await api.call_service("pkg_a", "nope")
        with pytest.raises(WorldError, match="服务不存在"):
            await api.call_service("pkg_missing", "nope")

    _run(_scenario(tmp_path / "world.db", fn))


def test_service_error_isolated(tmp_path):
    """服务 handler 抛异常 → WorldError（不拖垮内核，调用方可继续）。"""

    async def fn(engine, api):
        engine.attach_play_api("pkg_a", api)

        async def _boom(api, **params):
            raise RuntimeError("服务炸了")

        api.register_service("boom", _boom)
        with pytest.raises(WorldError, match="服务执行出错"):
            await api.call_service("pkg_a", "boom")
        # 内核仍可用
        assert engine.list_services()[0]["name"] == "boom"

    _run(_scenario(tmp_path / "world.db", fn))


def test_services_cleaned_on_unload(tmp_path):
    """卸载清理：clear_play_registrations 后服务消失，调用报错。"""

    async def fn(engine, api):
        engine.attach_play_api("pkg_a", api)
        api.register_service("s1", lambda api, **p: 1)
        assert engine.list_services()
        engine.clear_play_registrations("pkg_a")
        assert engine.list_services() == []
        with pytest.raises(WorldError, match="服务不存在"):
            await api.call_service("pkg_a", "s1")

    _run(_scenario(tmp_path / "world.db", fn))


def test_admin_services_endpoint(tmp_path):
    """管理端点 /admin/services 可见（test_admin 风格冒烟）。"""

    async def fn(engine, api):
        from starlette.testclient import TestClient

        from worlditor_mcp.admin import build_admin_app
        from worlditor_mcp.world.identity import IdentityService

        engine.attach_play_api("pkg_a", api)
        api.register_service("s1", lambda api, **p: 1)
        identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
        app = build_admin_app(identity, engine=engine)
        client = TestClient(app)
        # 无凭据 → 401/403
        assert client.get("/admin/services").status_code in (401, 403)
        # 管理员身份（注册带 admin_key）
        info = await identity.register_human("admin1", "pass123", admin_key="sekret")
        resp = client.get(
            "/admin/services",
            headers={"Authorization": f"Bearer {info.token}"},
        )
        assert resp.status_code == 200
        assert any(
            s["name"] == "s1" and s["play_id"] == "pkg_a"
            for s in resp.json()["services"]
        )

    _run(_scenario(tmp_path / "world.db", fn))
