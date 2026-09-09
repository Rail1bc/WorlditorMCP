"""管理页注册协议测试（v0.1.12）+ 管理端新读端点（地图/模板/账户检索）。

覆盖：
- register_admin_page 校验（URL 必须本包资源 / 至少一个 action / 冲突）
- GET /admin/play-pages 清单 + 管理页 action 代理（锁内调用、kv 语义归玩法包）
- 卸载清理（clear_play_registrations）
- /plays/<play_id>/web/* 管理端口服务（认证后）
- 地图读端点（列表/详情）、模板列表
- 账户检索（q/role/分页/排序/实体/凭据明细）
"""

from __future__ import annotations

import asyncio

import httpx
from play_fixtures import PLAY_ID, install_demo_play

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
    """同 test_admin：起引擎 + demo play + 双端口，另暴露 engine/loader。"""
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
            return await fn(admin_client, play_client, identity, engine, loader)
    finally:
        await engine.terminate()


async def _admin_token(identity) -> str:
    info = await identity.register_human("admin1", "pass123", admin_key="sekret")
    return info.token


# ---------- 管理页：注册与清单 ----------


def test_admin_page_registered_and_listed(tmp_path):
    """demo play 注册管理页；GET /admin/play-pages 返回清单（admin tier）。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        pages = engine.list_admin_pages()
        assert any(
            p["play_id"] == PLAY_ID
            and p["key"] == "shop"
            and p["actions"] == ["list", "set_price"]
            and p["component_url"] == f"/plays/{PLAY_ID}/web/admin-shop.js"
            for p in pages
        )
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        resp = await admin_client.get("/admin/play-pages", headers=h)
        assert resp.status_code == 200
        assert any(
            p["play_id"] == PLAY_ID and p["key"] == "shop" for p in resp.json()["pages"]
        )
        # 未认证 401
        assert (await admin_client.get("/admin/play-pages")).status_code == 401
        # 普通玩家 403
        player = await identity.register_human("p1", "pass123")
        h2 = {"Authorization": f"Bearer {player.token}"}
        assert (
            await admin_client.get("/admin/play-pages", headers=h2)
        ).status_code == 403

    _run(_scenario(tmp_path, fn))


def test_admin_page_validation_errors(tmp_path):
    """register_admin_page 校验：URL 非本包资源 / 无 action / 冲突。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        from worlditor_mcp.world import WorldError

        ok = {"list": lambda api: {}}
        # URL 必须本包资源
        try:
            engine.register_admin_page(
                "x",
                title="X",
                component_url="/plays/other/web/x.js",
                actions=ok,
                play_id=PLAY_ID,
            )
            raise AssertionError("应拒绝跨包 URL")
        except WorldError as e:
            assert "必须指向本站本包资源" in str(e)
        # 无 actions
        try:
            engine.register_admin_page(
                "x",
                title="X",
                component_url=f"/plays/{PLAY_ID}/web/x.js",
                actions={},
                play_id=PLAY_ID,
            )
            raise AssertionError("应拒绝空 actions")
        except WorldError as e:
            assert "至少一个 action" in str(e)
        # 同包 key 冲突
        try:
            engine.register_admin_page(
                "shop",
                title="重复",
                component_url=f"/plays/{PLAY_ID}/web/x.js",
                actions=ok,
                play_id=PLAY_ID,
            )
            raise AssertionError("应拒绝 key 冲突")
        except WorldError as e:
            assert "冲突" in str(e)

    _run(_scenario(tmp_path, fn))


def test_admin_page_action_proxy(tmp_path):
    """管理页 action 代理：list 读（kv 覆盖层）、set_price 写（语义归玩法包）。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # list：默认货单
        resp = await admin_client.post(
            f"/admin/play-pages/{PLAY_ID}/shop/list", json={}, headers=h
        )
        assert resp.status_code == 200, resp.text
        prices = resp.json()["data"]["prices"]
        assert prices["apple"]["price"] == 5
        # set_price：写 kv（namespace = 本包 id）
        resp = await admin_client.post(
            f"/admin/play-pages/{PLAY_ID}/shop/set_price",
            json={"item_id": "apple", "price": 7},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == {"item_id": "apple", "price": 7}
        assert engine.kv_get(PLAY_ID, "shop_prices") == {"apple": 7}
        # list 反映 kv 覆盖
        resp = await admin_client.post(
            f"/admin/play-pages/{PLAY_ID}/shop/list", json={}, headers=h
        )
        assert resp.json()["data"]["prices"]["apple"]["price"] == 7
        # 非法参数：ValueError → 错误透出（400）
        resp = await admin_client.post(
            f"/admin/play-pages/{PLAY_ID}/shop/set_price",
            json={"item_id": "apple", "price": -1},
            headers=h,
        )
        assert resp.status_code == 400
        assert "error" in resp.json()
        # 不存在的 action
        resp = await admin_client.post(
            f"/admin/play-pages/{PLAY_ID}/shop/nope", json={}, headers=h
        )
        assert resp.status_code == 400
        assert "action 不存在" in resp.json()["error"]

    _run(_scenario(tmp_path, fn))


def test_admin_page_web_and_uninstall(tmp_path):
    """管理端口服务本包 web 资源（认证后）；uninstall 清理管理页注册。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        # 未认证 401
        assert (
            await admin_client.get(f"/plays/{PLAY_ID}/web/admin-shop.js")
        ).status_code == 401
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        resp = await admin_client.get(f"/plays/{PLAY_ID}/web/admin-shop.js", headers=h)
        assert resp.status_code == 200, resp.text
        assert "测试夹具管理页组件" in resp.text
        # uninstall → 注册清理 + 资源 404
        resp = await admin_client.post(f"/admin/plays/{PLAY_ID}/uninstall", headers=h)
        assert resp.status_code == 200, resp.text
        assert not any(p["play_id"] == PLAY_ID for p in engine.list_admin_pages())
        assert (
            await admin_client.get(f"/plays/{PLAY_ID}/web/admin-shop.js", headers=h)
        ).status_code == 404

    _run(_scenario(tmp_path, fn))


# ---------- 内置包管理页（v0.1.12：物品管理端到端） ----------


async def _scenario_builtin(tmp_path, fn):
    """内置包场景：loader 指向 builtin_plays（物品管理页测试用）。"""
    from pathlib import Path

    BUILTIN_DIR = (
        Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
    )
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(
        engine,
        plays_dir=tmp_path / "plays",
        builtin_dir=BUILTIN_DIR,
        worlditor_version="0.1.11",
    )
    await loader.load_all()
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
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
            return await fn(admin_client, play_client, identity, engine, loader)
    finally:
        await engine.terminate()


def test_builtin_items_admin_page_endpoint(tmp_path):
    """内置包管理页：清单 + 代理 action + 组件资源服务。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # 清单
        resp = await admin_client.get("/admin/play-pages", headers=h)
        assert resp.status_code == 200
        assert any(
            p["play_id"] == "worlditor_play_items" and p["key"] == "items"
            for p in resp.json()["pages"]
        )
        # 代理 list
        resp = await admin_client.post(
            "/admin/play-pages/worlditor_play_items/items/list", json={}, headers=h
        )
        assert resp.status_code == 200, resp.text
        ids = {i["id"] for i in resp.json()["data"]["items"]}
        assert {"apple", "bread", "megaphone"} <= ids
        # 代理 create + list 反映
        resp = await admin_client.post(
            "/admin/play-pages/worlditor_play_items/items/create",
            json={"id": "gold_ore", "name": "金矿石", "stackable": True},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        resp = await admin_client.post(
            "/admin/play-pages/worlditor_play_items/items/list", json={}, headers=h
        )
        assert "gold_ore" in {i["id"] for i in resp.json()["data"]["items"]}
        # 组件资源（认证后）
        resp = await admin_client.get(
            "/plays/worlditor_play_items/web/admin-items.js", headers=h
        )
        assert resp.status_code == 200
        assert "AdminItemsView" in resp.text
        # 未认证 401
        assert (
            await admin_client.get("/plays/worlditor_play_items/web/admin-items.js")
        ).status_code == 401

    _run(_scenario_builtin(tmp_path, fn))


# ---------- 管理端地图/模板读端点 ----------


def test_map_read_endpoints(tmp_path):
    """GET /admin/maps 列表（归属 + 计数）；GET /admin/maps/{id} 详情；模板列表。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        resp = await admin_client.get("/admin/maps", headers=h)
        assert resp.status_code == 200, resp.text
        maps = {m["id"]: m for m in resp.json()["maps"]}
        assert "default" in maps
        d = maps["default"]
        assert d["world_id"] == "default"
        assert d["location_count"] == 41
        assert d["entity_count"] >= 3  # 种子 3 + 管理员注册的 player 实体
        assert d["visible"] == "public"
        # 详情：地块全量（含 connections slot）+ 实体 + 归属
        resp = await admin_client.get("/admin/maps/default", headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["map"]["name"] == "主世界"
        assert len(data["locations"]) == 41
        plaza = next(
            loc for loc in data["locations"] if loc["row"] == 0 and loc["col"] == 0
        )
        assert plaza["name"] == "小镇广场"
        assert "connections" in plaza and "down" in plaza["connections"]
        slot = plaza["connections"]["down"]
        assert slot["enabled"] is True and slot["paths"][0]["targets"]
        assert len(data["entities"]) >= 3
        # 模板：先建再列
        resp = await admin_client.post(
            "/admin/templates",
            json={"id": "t1", "name": "测试模板", "data": {"name": "X"}},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        resp = await admin_client.get("/admin/templates", headers=h)
        assert any(t["id"] == "t1" for t in resp.json()["templates"])
        # 不存在地图 404 语义（400 + error）
        resp = await admin_client.get("/admin/maps/nope", headers=h)
        assert resp.status_code == 400
        assert "不存在" in resp.json()["error"]

    _run(_scenario(tmp_path, fn))


# ---------- 账户检索 ----------


def test_accounts_search(tmp_path):
    """账户检索：q / role / 分页 / 排序 / 实体与凭据明细。"""

    async def fn(admin_client, play_client, identity, engine, loader):
        try:
            await _accounts_search_body(admin_client, identity)
        except Exception:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            raise


async def _accounts_search_body(admin_client, identity):
    # 造 3 账户：admin1（sekret）、user1、user2（+ user1 二次登录多一份凭据）
    admin_token = await _admin_token(identity)
    u1 = await identity.register_human("user1", "pass123")
    await identity.register_human("user2", "pass123")
    await identity.login("user1", "pass123")  # 第二份未吊销凭据
    h = {"Authorization": f"Bearer {admin_token}"}
    # q 过滤
    resp = await admin_client.get("/admin/accounts?q=user", headers=h)
    data = resp.json()
    assert {a["username"] for a in data["accounts"]} == {"user1", "user2"}
    assert data["total"] == 2
    # role 过滤
    resp = await admin_client.get("/admin/accounts?role=admin", headers=h)
    assert [a["username"] for a in resp.json()["accounts"]] == ["admin1"]
    # 分页：page_size=1 两页；row 含实体与凭据数
    resp = await admin_client.get(
        "/admin/accounts?q=user&page=1&page_size=1", headers=h
    )
    page1 = resp.json()
    assert page1["total"] == 2 and len(page1["accounts"]) == 1
    resp = await admin_client.get(
        "/admin/accounts?q=user&page=2&page_size=1", headers=h
    )
    assert len(resp.json()["accounts"]) == 1
    # 凭据明细（user1 两份登录）
    row = next(a for a in page1["accounts"] if a["username"] == "user1")
    assert row["token_count"] == 2
    assert row["entity"] is not None and row["entity"]["kind"] == "player"
    assert row["created_ts"] > 0
    # tokens 端点
    resp = await admin_client.get(f"/admin/accounts/{u1.account_id}/tokens", headers=h)
    assert resp.status_code == 200
    token_rows = resp.json()["tokens"]
    assert len(token_rows) == 2
    assert all(len(t["token"]) == 48 for t in token_rows)  # token_hex(24)
    assert any(t["tier"] == "play" for t in token_rows)
    # 排序：created_desc 默认，created_asc 反序
    resp = await admin_client.get("/admin/accounts?sort=created_asc", headers=h)
    usernames = [a["username"] for a in resp.json()["accounts"]]
    assert usernames == sorted(usernames, key=lambda u: u)
