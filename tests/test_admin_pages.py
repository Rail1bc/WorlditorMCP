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
from world_fixtures import seed_test_world

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
    await seed_test_world(engine)  # v0.2.0：内核不再内置世界内容，注册要有地方站
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
        # 服务的是仓库提交在案的参考组件（夹具从 tests/fixtures 复制而来）
        assert "AdminShop" in resp.text
        assert f"/admin/play-pages/{PLAY_ID}/shop" in resp.text
        # uninstall → 注册清理 + 资源 404
        resp = await admin_client.post(f"/admin/plays/{PLAY_ID}/uninstall", headers=h)
        assert resp.status_code == 200, resp.text
        assert not any(p["play_id"] == PLAY_ID for p in engine.list_admin_pages())
        assert (
            await admin_client.get(f"/plays/{PLAY_ID}/web/admin-shop.js", headers=h)
        ).status_code == 404

    _run(_scenario(tmp_path, fn))


# ---------- 内置包管理页（v0.1.12：物品管理端到端） ----------


async def _scenario_with_play(tmp_path, fn):
    """带玩法包的场景：内置世界内容包 + 夹具玩法包（物品定义/管理页测试用）。

    v0.7.0：内置玩法包已废弃，物品定义与工具/视图改由 ``play_fixtures``
    的夹具玩法包提供（它声明 apple/megaphone 两条代码定义 + shop 管理页）。
    """
    from pathlib import Path

    BUILTIN_DIR = (
        Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
    )
    install_demo_play(tmp_path / "plays")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(
        engine,
        plays_dir=tmp_path / "plays",
        builtin_dir=BUILTIN_DIR,
        worlditor_version="0.7.0",
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


def test_disable_keeps_admin_entity_templates(tmp_path):
    """G31（v0.5.2）那条不变量：停用玩法包只清**代码声明**，管理员建的东西必须留下。

    原用例守的是"物品定义分两种生命周期"（`save_item_def(user_data=True)` 落库、
    停用不删）。v2 / D37 物品不在内核后，同一条不变量由**实体模板**承担，
    而且现在由**存储位置**天然区分：包注册的模板在引擎内存表（随停用消失），
    管理员本地模板落 `templates` 表（不受影响）。
    """

    async def fn(admin_client, play_client, identity, engine, loader):
        import aiosqlite

        from worlditor_mcp.world.model import WorldTemplate

        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # 代码声明：夹具包在 **setup 里**注册的实体模板（所以重启用会自己回来）。
        # 注意别改成命令式注册——那样 enable 时包的 setup 重跑也不会恢复它。
        ids = {t["id"] for t in engine.list_templates("entity")}
        assert "pkg_npc" in ids, f"夹具包应在 setup 里声明实体模板：{ids}"
        # 管理员本地模板：落 templates 表（与"管理页保存"同一条入口）。
        # D41：实体模板 data = `{name, desc, components}`——"类型 = 一组组件的预设"，
        # 没有 kind 输入键（要带能力就在 components 里给组件键）。
        await engine.save_template(
            WorldTemplate(
                id="admin_ore",
                name="管理员矿石",
                scope="entity",
                data={"name": "金矿石", "components": {"local:ore": {}}},
            )
        )
        ids = {t["id"] for t in engine.list_templates("entity")}
        assert {"pkg_npc", "admin_ore"} <= ids
        # 落库前已按新负载规范化：只留 name / desc / components
        rows = {t["id"]: t for t in engine.list_templates("entity")}
        assert rows["admin_ore"]["data"] == {
            "name": "金矿石",
            "desc": "",
            "components": {"local:ore": {}},
        }

        resp = await admin_client.post(f"/admin/plays/{PLAY_ID}/disable", headers=h)
        assert resp.status_code == 200, resp.text

        ids = {t["id"] for t in engine.list_templates("entity")}
        assert "pkg_npc" not in ids, "包声明的模板应随停用消失"
        assert "admin_ore" in ids, "管理员本地模板必须留下"
        async with aiosqlite.connect(tmp_path / "world.db") as conn:
            cur = await conn.execute("SELECT id FROM templates WHERE scope='entity'")
            persisted = {row[0] for row in await cur.fetchall()}
        assert "admin_ore" in persisted, f"停用后本地模板不应从库里消失：{persisted}"

        # 重新启用 → 代码声明回来，本地模板不受影响
        resp = await admin_client.post(f"/admin/plays/{PLAY_ID}/enable", headers=h)
        assert resp.status_code == 200, resp.text
        ids = {t["id"] for t in engine.list_templates("entity")}
        assert {"pkg_npc", "admin_ore"} <= ids

    _run(_scenario_with_play(tmp_path, fn))


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

    # 断言演示世界内容（41 地块/小镇广场）→ 用内置包场景（世界包导入该世界）
    _run(_scenario_with_play(tmp_path, fn))


def test_entity_endpoints_cover_absent_entities(tmp_path):
    """`/admin/entities` 覆盖**不在世界上**的实体（D36 / v2 1d）。

    地图详情（`/admin/maps/{id}`）是**地图视角**：它按 `map_id` 裁，不在世界上的实体
    一个都看不见。若没有这条全局视角，"内核造得出、编辑器管不着"——而"仅靠内核就能
    完全地编辑治理实体"正是 v2 的目标，所以这条读端点不是锦上添花。
    """

    async def fn(admin_client, play_client, identity, engine, loader):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}

        # ① 不给坐标 = 造一个不在世界上的实体（**不是**默认放到 (0,0)）
        resp = await admin_client.post(
            "/admin/entities", json={"kind": "thing", "name": "箱子"}, headers=h
        )
        assert resp.status_code == 200, resp.text
        box_id = resp.json()["data"]["id"]
        # D41：创建端点回 `{id, components}`——kind 是输入便利，落成组件键（不再回 tags）
        assert "local:thing" in resp.json()["data"]["components"]
        assert "tags" not in resp.json()["data"]
        box = engine.get_entity(box_id)
        assert not box.has_position() and box.pos_key() is None

        # ② 半截坐标：报错，且错误说的是"半截位置"，不是某个 500
        resp = await admin_client.post(
            "/admin/entities",
            json={"kind": "thing", "map_id": "default", "row": 1},
            headers=h,
        )
        assert resp.status_code == 400
        assert "半截" in resp.json()["error"]

        # ③ 地图视角（含/不含）与全局视角的差别
        resp = await admin_client.get("/admin/maps/default", headers=h)
        assert resp.status_code == 200
        assert box_id not in {e["id"] for e in resp.json()["entities"]}

        resp = await admin_client.get("/admin/entities", headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        got = {e["id"]: e for e in data["entities"]}
        assert box_id in got, "全局实体视角必须看得到不在世界上的实体"
        assert data["absent"] >= 1 and data["total"] == len(data["entities"])
        # 不在世界的实体没有位置键，但要有名字与能力诊断
        assert "map_id" not in got[box_id] and "row" not in got[box_id]
        assert got[box_id]["components"]["core:info"]["name"] == "箱子"
        assert "capabilities" in got[box_id]

        # ④ ?absent= 过滤（1 只列不在世界的、0 只列在世界的，两者不相交）
        out = (await admin_client.get("/admin/entities?absent=1", headers=h)).json()
        inn = (await admin_client.get("/admin/entities?absent=0", headers=h)).json()
        assert box_id in {e["id"] for e in out["entities"]}
        assert box_id not in {e["id"] for e in inn["entities"]}
        assert all("core:position" not in e["components"] for e in out["entities"])
        assert not (
            {e["id"] for e in out["entities"]} & {e["id"] for e in inn["entities"]}
        )

        # ⑤ 给了坐标 = 照旧放进世界
        resp = await admin_client.post(
            "/admin/entities",
            json={"kind": "thing", "map_id": "default", "row": 1, "col": 0},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        placed = engine.get_entity(resp.json()["data"]["id"])
        assert placed.pos_key() == ("default", 1, 0)

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

    _run(_scenario(tmp_path, fn))


async def _accounts_search_body(admin_client, identity):
    # 造 3 账户：admin1（sekret）、user1、user2
    admin_token = await _admin_token(identity)
    u1 = await identity.register_human("user1", "pass123")
    await identity.register_human("user2", "pass123")
    # 再登录一次：login 会**吊销旧凭据**（identity.login 的既定语义），
    # 所以 user1 名下始终只有一份有效凭据——token_count 反映的是未吊销数。
    await identity.login("user1", "pass123")
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
    page2 = resp.json()
    assert len(page2["accounts"]) == 1
    # 两页正好覆盖两个账户（谁在第一页按注册时间倒序，别把顺序写死）
    rows = page1["accounts"] + page2["accounts"]
    assert {a["username"] for a in rows} == {"user1", "user2"}
    # 凭据明细（user1 登录一次 → 一份有效凭据）与绑定实体
    # （D41：实体投影没有 kind / tags——判能力看 `local:player` 组件）
    row = next(a for a in rows if a["username"] == "user1")
    assert row["token_count"] == 1
    assert row["entity"] is not None
    assert "local:player" in row["entity"]["components"]
    assert "kind" not in row["entity"] and "tags" not in row["entity"]
    assert row["created_ts"] > 0
    # tokens 端点（只列未吊销凭据，完整 token 供吊销）
    resp = await admin_client.get(f"/admin/accounts/{u1.account_id}/tokens", headers=h)
    assert resp.status_code == 200
    token_rows = resp.json()["tokens"]
    assert len(token_rows) == 1
    assert all(len(t["token"]) == 48 for t in token_rows)  # token_hex(24)
    assert any(t["tier"] == "play" for t in token_rows)
    # 排序：created_desc 默认，created_asc 反序
    resp = await admin_client.get("/admin/accounts?sort=created_asc", headers=h)
    usernames = [a["username"] for a in resp.json()["accounts"]]
    assert usernames == sorted(usernames, key=lambda u: u)
