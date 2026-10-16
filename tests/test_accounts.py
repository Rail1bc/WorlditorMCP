"""账户生命周期测试：永久注销（本人/管理员）、角色变更、D14 身份化保护。

覆盖：删账户级联（凭据吊销 + 实体删除 + 用户名可复用）、角色变更强制重登、
HTTP 端点（玩家 /auth/delete-account + 管理 /admin/accounts）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.admin import build_admin_app
from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.identity import IdentityError, IdentityService
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


def _make(db_path: Path, **kwargs) -> tuple[WorldEngine, IdentityService]:
    engine = WorldEngine(WorldStore(db_path))
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret", **kwargs)
    return engine, identity


def _scenario(db_path, fn, **kwargs):
    engine, identity = _make(db_path, **kwargs)

    async def main():
        await engine.initialize()
        await seed_test_world(engine)  # v0.2.0：内核不再内置世界内容，注册要有地方站
        try:
            return await fn(engine, identity)
        finally:
            await engine.terminate()

    return main()


# ---------- 本人注销 ----------


async def _avatar(
    engine, account_id: str, *, name: str = "化身", row: int = 0, col: int = 0
):
    """造一具属于某账户的化身（D45/D46：内核不诞生角色，**玩法包才是发起方**）。

    测试里直接调内核原语 + 窄口：``place_entity``（造实体）→ ``claim_avatar``
    （认领给该账户，写 ``core:account``，从此受 D14 保护）。
    """
    entity = await engine.place_entity(None, "default", row, col, name=name)
    await engine.claim_avatar(entity.id, account_id)
    return entity


def test_delete_own_account(tmp_path):
    """本人注销：账户 + 全部凭据 + **全部化身**删除；用户名可重新注册。"""

    async def fn(engine, identity):
        info = await identity.register_human("小明", "pass123")
        assert info.entity_id == ""  # D45：注册不建实体
        entity = await _avatar(engine, info.account_id, name="小明")
        entity_id = entity.id
        # 再登录一次（login 本身会吊销旧凭据——验证与新凭据一并吊销）
        info2 = await identity.login("小明", "pass123")
        assert identity.resolve(info.token) is None  # login 吊销旧凭据
        await identity.delete_own_account(info2.token)
        # 全部凭据失效
        assert identity.resolve(info2.token) is None
        # 账户与实体消失
        assert engine.store.get_account(info.account_id) is None
        assert engine.get_entity(entity_id) is None
        # 用户名可重新注册（账号级唯一性）
        again = await identity.register_human("小明", "pass456")
        assert again.tier == "play"

    _run(_scenario(tmp_path / "world.db", fn))


def test_delete_own_account_read_tier_rejected(tmp_path):
    """read 档（围观者）不能注销（无账户绑定）。"""

    async def fn(engine, identity):
        info = await identity.create_read_token()
        with pytest.raises(IdentityError, match="无效的凭据"):
            await identity.delete_own_account(info.token)

    _run(_scenario(tmp_path / "world.db", fn))


def test_offline_avatar_still_counts_as_mine(tmp_path):
    """ "按账户找化身"与**位置无关**（D36 的默认值坑；D46 起改由 ``entities_of_account`` 承担）。

    `list_entities()` 从 v2 第 1d 期起默认只返回"在世界上"的实体——照它找，一个
    下线的化身会被判成"没有化身"，然后**再补造一具**：同一账户多出一个孤儿
    （仍绑着账户、仍不可被 `remove_entity` 删），账户页则显示成"没有化身"。

    这类"默认值改了、调用点没跟着改"的读点不会报错，只会悄悄多出一个实体——
    所以要有一条断言盯住**数量**与**跨位置的一致性**。
    """

    async def fn(engine, identity):
        info = await identity.register_human("小明", "pass123")
        first = await _avatar(engine, info.account_id, name="小明", row=0, col=0)
        second = await _avatar(engine, info.account_id, name="小明二号", row=0, col=1)

        # 下线其中一具：位置组件被摘掉（玩法包走 api.clear_position）
        await engine.clear_position(second.id)
        assert engine.get_entity(second.id).pos_key() is None
        assert second.id not in {e.id for e in engine.list_entities()}  # 默认查不到

        # 但"是不是我的化身"与位置无关：两具都要在
        mine = {e.id for e in engine.entities_of_account(info.account_id)}
        assert mine == {first.id, second.id}

        # 登录**不补造实体**（D45）：这里只发凭据，化身由玩法包管理
        before = set(engine.store.entities)
        again = await identity.login("小明", "pass123")
        assert again.entity_id == ""
        assert set(engine.store.entities) == before, "登录不该凭空多出一个实体"

        # 账户检索也要看得到两具（含下线那具）
        page = identity.search_accounts(q="小明")
        row = next(a for a in page["accounts"] if a["username"] == "小明")
        assert {e["id"] for e in row["entities"]} == {first.id, second.id}

        # 注销级联到**全部**化身（与位置无关）
        await identity.delete_account(info.account_id)
        assert engine.get_entity(first.id) is None
        assert engine.get_entity(second.id) is None

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 管理员删除 / 角色变更 ----------


def test_admin_delete_account(tmp_path):
    """管理员删除账户（含管理员）；事件触发（on_entity_removed，逐个化身）。"""

    async def fn(engine, identity):
        admin = await identity.register_human("管理员", "pass123", admin_key="sekret")
        player = await identity.register_human("小明", "pass123")
        one = await _avatar(engine, player.account_id, name="小明", row=0, col=0)
        two = await _avatar(engine, player.account_id, name="小明二号", row=0, col=1)
        removed = []
        engine.register_world_event(
            "on_entity_removed", lambda api, e: removed.append(e.id)
        )
        await identity.delete_account(player.account_id)
        assert engine.store.get_account(player.account_id) is None
        assert engine.get_entity(one.id) is None
        assert engine.get_entity(two.id) is None
        assert identity.resolve(player.token) is None
        assert sorted(removed) == sorted([one.id, two.id])
        # 管理员也能删自己（注销闭环）
        await identity.delete_account(admin.account_id)
        assert engine.store.get_account(admin.account_id) is None

    _run(_scenario(tmp_path / "world.db", fn))


def test_set_account_role(tmp_path):
    """角色变更：旧凭据吊销 → 重登按新角色；非法角色拒绝。"""

    async def fn(engine, identity):
        await identity.register_human("管理员", "pass123", admin_key="sekret")
        player = await identity.register_human("小明", "pass123")
        # 升 admin → 旧凭据失效 + 重登 tier=admin
        await identity.set_account_role(player.account_id, "admin")
        assert identity.resolve(player.token) is None
        relogin = await identity.login("小明", "pass123")
        assert relogin.tier == "admin"
        # 降级 → 重登 tier=play
        await identity.set_account_role(player.account_id, "user")
        assert identity.resolve(relogin.token) is None
        relogin = await identity.login("小明", "pass123")
        assert relogin.tier == "play"
        # 非法角色
        with pytest.raises(IdentityError, match="角色"):
            await identity.set_account_role(player.account_id, "super")
        # 不存在
        with pytest.raises(IdentityError, match="不存在"):
            await identity.set_account_role("nope", "admin")

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- HTTP 端点 ----------


def test_http_delete_own_account(tmp_path):
    """玩家端口 POST /auth/delete-account：注销成功后凭据立即无效。"""

    async def fn(engine, identity):
        from worlditor_mcp.world.mcp import build_mcp_server

        info = await identity.register_human("小明", "pass123")
        app = build_http_app(build_mcp_server(engine), identity, engine=engine)
        client = TestClient(app)
        r = client.post(
            "/auth/delete-account",
            headers={"Authorization": f"Bearer {info.token}"},
        )
        assert r.status_code == 200 and r.json().get("ok")
        assert identity.resolve(info.token) is None
        # 无凭据 → 401
        assert client.post("/auth/delete-account").status_code == 401

    _run(_scenario(tmp_path / "world.db", fn))


def test_http_admin_account_management(tmp_path):
    """管理端：删除账户 + 角色变更（PATCH）端点。"""

    async def fn(engine, identity):
        admin = await identity.register_human("管理员", "pass123", admin_key="sekret")
        player = await identity.register_human("小明", "pass123")
        app = build_admin_app(identity, engine=engine)
        client = TestClient(app)
        h = {"Authorization": f"Bearer {admin.token}"}
        # 升 admin
        r = client.patch(
            f"/admin/accounts/{player.account_id}", json={"role": "admin"}, headers=h
        )
        assert r.status_code == 200
        assert r.json()["data"]["role"] == "admin"
        assert identity.resolve(player.token) is None
        # 删除
        r = client.delete(f"/admin/accounts/{player.account_id}", headers=h)
        assert r.status_code == 200
        assert engine.store.get_account(player.account_id) is None
        # 非管理员访问 → 403
        other = await identity.register_human("路人", "pass123")
        h2 = {"Authorization": f"Bearer {other.token}"}
        assert (
            client.delete(f"/admin/accounts/{admin.account_id}", headers=h2).status_code
            == 403
        )

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 模式识别端点（管理/玩家界面分离） ----------


def test_meta_endpoints(tmp_path):
    """/meta：玩家端口 = play、管理端口 = admin；免认证可访问。"""

    async def fn(engine, identity):
        from worlditor_mcp.world.mcp import build_mcp_server

        play_app = build_http_app(build_mcp_server(engine), identity, engine=engine)
        admin_app = build_admin_app(identity, engine=engine)
        play = TestClient(play_app)
        admin = TestClient(admin_app)
        assert play.get("/meta").json()["mode"] == "play"
        assert admin.get("/meta").json()["mode"] == "admin"
        # 免认证 ≠ 已认证：无凭据时明确报告"这次连接没有身份"
        assert play.get("/meta").json()["authenticated"] is False

    _run(_scenario(tmp_path / "world.db", fn))


def test_meta_reports_stale_token_as_unauthenticated(tmp_path):
    """/meta 带身份状态：陈旧/吊销凭据 → ``authenticated=false``。

    背景（真实事故）：前端原先只凭 localStorage 里"有一串 token"就跳过登录页，
    而唯一会清掉失效凭据的自愈路径是"某个非 ``/auth`` 请求收到 401"。可启动时
    只打 ``/meta`` 与 ``/views``——两个都免认证、**恒 200**——所以删库/吊销之后
    前端永远发现不了，玩家卡在一个看得见、点什么都失败的空壳里。这条测试守住
    那个信号：状态用**字段**表达（端点仍 200），前端据此清凭据回登录页。
    """

    async def fn(engine, identity):
        from worlditor_mcp.world.mcp import build_mcp_server

        play = TestClient(
            build_http_app(build_mcp_server(engine), identity, engine=engine)
        )
        admin = TestClient(build_admin_app(identity, engine=engine))
        player = await identity.register_human("小明", "pass123")
        admin_info = await identity.register_human(
            "管理员", "pass123", admin_key="sekret"
        )
        good = {"Authorization": f"Bearer {player.token}"}
        dead = {"Authorization": "Bearer deadbeef"}

        # 有效凭据：authenticated + 档位/实体/用户名（界面也靠它显示"我是谁"）
        body = play.get("/meta", headers=good).json()
        assert body["authenticated"] is True
        assert body["tier"] == "play"
        assert body["entity_id"] == player.entity_id
        assert body["username"] == "小明"

        # 陈旧/伪造凭据：200 + authenticated=false（**不是 401**——登录页也要用它）
        resp = play.get("/meta", headers=dead)
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        assert "tier" not in resp.json()

        # 管理端口同一套语义
        assert (
            admin.get(
                "/meta", headers={"Authorization": f"Bearer {admin_info.token}"}
            ).json()["tier"]
            == "admin"
        )
        assert admin.get("/meta", headers=dead).json()["authenticated"] is False

        # 被吊销的凭据立刻变 false（管理员吊销 / 改密 → 下次启动即回登录页）
        await identity.logout(player.token)
        assert play.get("/meta", headers=good).json()["authenticated"] is False

    _run(_scenario(tmp_path / "world.db", fn))


def test_http_admin_invite_revoke(tmp_path):
    """管理端邀请码吊销端点（AdminPanel 依赖）。"""

    async def fn(engine, identity):
        admin = await identity.register_human("管理员", "pass123", admin_key="sekret")
        codes = await identity.create_invite_codes(1)
        app = build_admin_app(identity, engine=engine)
        client = TestClient(app)
        h = {"Authorization": f"Bearer {admin.token}"}
        r = client.delete(f"/admin/invite-codes/{codes[0]}", headers=h)
        assert r.status_code == 200
        # 吊销 = used 失效标记（0.x 简化：无独立 revoked 字段）
        assert identity.list_invite_codes()[0]["used"] is True

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- D14 账户绑定保护（内核层，D42 改判据） ----------


def test_remove_account_bound_entity_protected(tmp_path):
    """remove_entity 拒绝**绑定了账户**的实体；delete_account_entity 为受控通道。

    D42：判据是 `core:account`（**不是**"身份"）——所以这里额外验证
    "没绑账户的同名实体照样能删"（代理判据会白挡）。
    D46：化身怎么来的？**玩法包认领**（``claim_avatar``）——内核自己不造。
    """

    async def fn(engine, identity):
        info = await identity.register_human("小明", "pass123")
        entity = await _avatar(engine, info.account_id, name="小明")
        with pytest.raises(WorldError, match="绑定了账户"):
            await engine.remove_entity(entity.id)
        assert engine.get_entity(entity.id) is not None
        # 受控通道（身份服务）
        from worlditor_mcp.world import WorldError as WE

        await engine.delete_account_entity(entity.id)
        assert engine.get_entity(entity.id) is None
        # 没绑账户的实体走受控通道 → 拒绝
        wolf = await engine.place_entity("wolf", "default", 0, 0, name="狼")
        with pytest.raises(WE, match="只支持绑定了账户"):
            await engine.delete_account_entity(wolf.id)
        # 没绑账户 → 普通实体，可以被 remove（D14 保护的是"绑了账户的"）
        loose = await engine.place_entity("player", "default", 0, 1, name="野玩家")
        await engine.remove_entity(loose.id)
        assert engine.get_entity(loose.id) is None

    _run(_scenario(tmp_path / "world.db", fn))


def test_release_avatar_is_the_owner_channel(tmp_path):
    """**退掉自己的化身**：只能退自己的；退掉后 D14 不再拦；指针被清空（D46）。

    这条通道的存在理由：D14 让"绑账户的实体"谁都删不掉——包括**本人想删掉自己
    多余的化身**时。所以内核给一道owner-scoped 的解绑窄口，而不是给玩法包开
    删除后门：解绑 → 序列化指针清空 → 才允许 remove。
    """

    async def fn(engine, identity):
        mine = await identity.register_human("小明", "pass123")
        other = await identity.register_human("小红", "pass123")
        my_avatar = await _avatar(engine, mine.account_id, name="小明")
        other_avatar = await _avatar(engine, other.account_id, name="小红", col=1)

        # 别人的化身：退不掉（D14 对别人依然完全有效）
        with pytest.raises(WorldError, match="只能退掉自己"):
            await engine.release_avatar(other_avatar.id, mine.account_id)
        # 没有主体 → 退不掉
        with pytest.raises(WorldError, match="没有主体"):
            await engine.release_avatar(my_avatar.id, "")
        # 没绑账户的 → 不需要解绑
        loose = await engine.place_entity(None, "default", -1, 0, name="路人")
        with pytest.raises(WorldError, match="没有绑定账户"):
            await engine.release_avatar(loose.id, mine.account_id)

        # 自己的：解绑 → 指针被清 → 可以删
        await engine.store.set_token_entity(mine.token, my_avatar.id)
        cleared = await engine.release_avatar(my_avatar.id, mine.account_id)
        assert cleared == 1, "指向它的凭据指针必须一起清掉（否则留下悬空实体 id）"
        assert engine.store.get_token(mine.token).entity_id == ""
        assert engine.get_entity(my_avatar.id).user_id is None
        await engine.remove_entity(my_avatar.id)  # 不再被 D14 拦
        assert engine.get_entity(my_avatar.id) is None
        # 已经解绑的再退一次 → 报"没有绑定账户"（幂等语义：第二次是空操作式报错）
        spare = await _avatar(engine, mine.account_id, name="小明三号", col=-1)
        await engine.release_avatar(spare.id, mine.account_id)
        with pytest.raises(WorldError, match="没有绑定账户"):
            await engine.release_avatar(spare.id, mine.account_id)

    _run(_scenario(tmp_path / "world.db", fn))
