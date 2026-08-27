"""管理端口测试（D16）：/admin/* 端点 + tier 校验 + 视图列表（G3）。"""

from __future__ import annotations

import asyncio

import httpx
from play_fixtures import install_demo_play

from worlditor_mcp.admin import build_admin_app
from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_mcp_server
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _scenario(tmp_path, fn, *, admin_key="sekret"):
    install_demo_play(tmp_path / "plays")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0")
    await loader.load_all()
    identity = IdentityService(engine, auth_mode="open", admin_key=admin_key)
    admin_app = build_admin_app(identity, engine=engine, loader=loader)
    mcp = build_mcp_server(engine)
    play_app = build_http_app(mcp, identity, engine=engine, loader=loader)
    try:
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=admin_app), base_url="http://admin"
            ) as admin_client,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=play_app), base_url="http://play"
            ) as play_client,
        ):
            return await fn(admin_client, play_client, identity)
    finally:
        await engine.terminate()


async def _admin_token(identity) -> str:
    info = await identity.register_human("admin1", "pass123", admin_key="sekret")
    return info.token


def test_admin_requires_admin_tier(tmp_path):
    """管理端点：未认证 401；普通玩家 403；admin 放行。"""

    async def fn(admin_client, play_client, identity):
        assert (await admin_client.get("/admin/plays")).status_code == 401
        player = await identity.register_human("p1", "pass123")
        h = {"Authorization": f"Bearer {player.token}"}
        assert (await admin_client.get("/admin/plays", headers=h)).status_code == 403
        token = await _admin_token(identity)
        resp = await admin_client.get(
            "/admin/plays", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert any(p["play_id"] == "worlditor_play_demo" for p in resp.json()["plays"])

    _run(_scenario(tmp_path, fn))


def test_admin_play_manage(tmp_path):
    """玩法包管理端点：disable → enable → uninstall。"""

    async def fn(admin_client, play_client, identity):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # disable
        resp = await admin_client.post(
            "/admin/plays/worlditor_play_demo/disable", headers=h
        )
        assert resp.status_code == 200, resp.text
        plays = (await admin_client.get("/admin/plays", headers=h)).json()["plays"]
        status = {p["play_id"]: p["status"] for p in plays}
        assert status["worlditor_play_demo"] == "disabled"
        # enable
        resp = await admin_client.post(
            "/admin/plays/worlditor_play_demo/enable", headers=h
        )
        assert resp.status_code == 200, resp.text
        plays = (await admin_client.get("/admin/plays", headers=h)).json()["plays"]
        status = {p["play_id"]: p["status"] for p in plays}
        assert status["worlditor_play_demo"] == "loaded"
        # uninstall
        resp = await admin_client.post(
            "/admin/plays/worlditor_play_demo/uninstall", headers=h
        )
        assert resp.status_code == 200, resp.text
        plays = (await admin_client.get("/admin/plays", headers=h)).json()["plays"]
        assert all(p["play_id"] != "worlditor_play_demo" for p in plays)

    _run(_scenario(tmp_path, fn))


def test_admin_worlds_and_map_edit(tmp_path):
    """世界 CRUD + 地图编辑端点 + 世界激活配置生效。"""

    async def fn(admin_client, play_client, identity):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # 建世界 + 激活集合
        resp = await admin_client.post(
            "/admin/worlds",
            json={"id": "pvp", "name": "竞技", "play_ids": ["worlditor_play_demo"]},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        worlds = (await admin_client.get("/admin/worlds", headers=h)).json()["worlds"]
        assert {w["id"] for w in worlds} >= {"default", "pvp"}
        # 激活配置更新
        resp = await admin_client.patch(
            "/admin/worlds/pvp", json={"play_ids": []}, headers=h
        )
        assert resp.status_code == 200
        # 建地图
        resp = await admin_client.post(
            "/admin/maps", json={"id": "arena", "name": "竞技场"}, headers=h
        )
        assert resp.status_code == 200, resp.text
        # 归属到世界 + 文件夹
        resp = await admin_client.post(
            "/admin/worlds/pvp/folders", json={"name": "竞技区"}, headers=h
        )
        assert resp.status_code == 200, resp.text
        folder_id = resp.json()["data"]["id"]
        resp = await admin_client.post(
            "/admin/worlds/pvp/assign-map",
            json={"map_id": "arena", "folder_id": folder_id},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        worlds = (await admin_client.get("/admin/worlds", headers=h)).json()["worlds"]
        pvp = next(w for w in worlds if w["id"] == "pvp")
        assert "arena" in pvp["maps"]
        # 建实体（地图编辑）
        resp = await admin_client.post(
            "/admin/entities",
            json={
                "kind": "wolf",
                "map_id": "default",
                "row": 0,
                "col": 0,
                "name": "狼",
            },
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        entity_id = resp.json()["data"]["id"]
        resp = await admin_client.delete(f"/admin/entities/{entity_id}", headers=h)
        assert resp.status_code == 200
        # 删除世界（有地图 → 拒绝）
        resp = await admin_client.delete("/admin/worlds/pvp", headers=h)
        assert resp.status_code == 400 and "仍有地图" in resp.json()["error"]

    _run(_scenario(tmp_path, fn))


def test_admin_identity_endpoints(tmp_path):
    """身份管理端点：账户列表 + 邀请码 + 吊销。"""

    async def fn(admin_client, play_client, identity):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        resp = await admin_client.get("/admin/accounts", headers=h)
        assert resp.status_code == 200
        assert any(a["username"] == "admin1" for a in resp.json()["accounts"])
        resp = await admin_client.post(
            "/admin/invite-codes", json={"count": 2}, headers=h
        )
        assert resp.status_code == 200
        codes = resp.json()["data"]["codes"]
        assert len(codes) == 2
        # 吊销玩家凭据
        player = await identity.register_human("p2", "pass123")
        resp = await admin_client.delete(f"/admin/tokens/{player.token}", headers=h)
        assert resp.status_code == 200
        assert identity.resolve(player.token) is None

    _run(_scenario(tmp_path, fn))


def test_views_endpoint_on_player_port(tmp_path):
    """GET /views（玩家端口，G3）：视图列表。"""

    async def fn(admin_client, play_client, identity):
        info = await identity.register_human("p3", "pass123")
        h = {"Authorization": f"Bearer {info.token}"}
        resp = await play_client.get("/views", headers=h)
        assert resp.status_code == 200
        assert "views" in resp.json()

    _run(_scenario(tmp_path, fn))
