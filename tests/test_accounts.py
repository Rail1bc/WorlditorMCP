"""账户生命周期测试：永久注销（本人/管理员）、角色变更、D14 身份化保护。

覆盖：删账户级联（凭据吊销 + 实体删除 + 用户名可复用）、角色变更强制重登、
HTTP 端点（玩家 /auth/delete-account + 管理 /admin/accounts）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from worlditor_mcp.admin import build_admin_app
from worlditor_mcp.world.identity import IdentityError, IdentityService
from worlditor_mcp.world.mcp.http import build_http_app
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore


def _run(coro):
    return asyncio.run(coro)


def _make(db_path: Path, **kwargs) -> tuple[V4WorldEngine, IdentityService]:
    engine = V4WorldEngine(V4WorldStore(db_path))
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret", **kwargs)
    return engine, identity


def _scenario(db_path, fn, **kwargs):
    engine, identity = _make(db_path, **kwargs)

    async def main():
        await engine.initialize()
        try:
            return await fn(engine, identity)
        finally:
            await engine.terminate()

    return main()


# ---------- 本人注销 ----------


def test_delete_own_account(tmp_path):
    """本人注销：账户 + 全部凭据 + 玩家实体删除；用户名可重新注册。"""

    async def fn(engine, identity):
        info = await identity.register_human("小明", "pass123")
        entity_id = info.entity_id
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


# ---------- 管理员删除 / 角色变更 ----------


def test_admin_delete_account(tmp_path):
    """管理员删除账户（含管理员）；事件触发（on_entity_removed）。"""

    async def fn(engine, identity):
        admin = await identity.register_human("管理员", "pass123", admin_key="sekret")
        player = await identity.register_human("小明", "pass123")
        removed = []
        engine.register_world_event(
            "on_entity_removed", lambda api, e: removed.append(e.id)
        )
        await identity.delete_account(player.account_id)
        assert engine.store.get_account(player.account_id) is None
        assert engine.get_entity(player.entity_id) is None
        assert identity.resolve(player.token) is None
        assert removed == [player.entity_id]
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


# ---------- D14 身份化保护（内核层） ----------


def test_remove_identity_entity_protected(tmp_path):
    """remove_entity 拒绝身份化实体；delete_identity_entity 为受控通道。"""

    async def fn(engine, identity):
        info = await identity.register_human("小明", "pass123")
        with pytest.raises(WorldError, match="身份化"):
            await engine.remove_entity(info.entity_id)
        assert engine.get_entity(info.entity_id) is not None
        # 受控通道（身份服务）
        from worlditor_mcp.world.v4engine import WorldError as WE

        await engine.delete_identity_entity(info.entity_id)
        assert engine.get_entity(info.entity_id) is None
        # 非身份化实体走受控通道 → 拒绝
        wolf = await engine.place_entity("wolf", "default", 0, 0, name="狼")
        with pytest.raises(WE, match="身份化"):
            await engine.delete_identity_entity(wolf.id)

    _run(_scenario(tmp_path / "world.db", fn))
