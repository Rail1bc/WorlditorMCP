"""内核审查（v0.7.0 之后）所发现问题的回归测试。

每条注明发现来源、位置与"不修会怎样"，便于日后回看为什么有这条测试。

- instructions 运行期刷新是死代码（`engine.py:_refresh_instructions`）
- 零工具时 instructions 文案不实（`mcp/__init__.py:_INSTRUCTIONS_EMPTY`）
- `/plays/{id}/web/` 路径校验用 str.startswith（`mcp/http.py:_play_web`）
- JSON-RPC 批处理请求不注入身份（`mcp/http.py:_inject_identity`）
- 管理端裸 int() 入参 → 500 而非 400，且 HTTPException 返回纯文本（G26）
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from play_fixtures import install_demo_play
from world_fixtures import seed_test_world

from worlditor_mcp.admin import build_admin_app
from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.mcp import build_mcp_server
from worlditor_mcp.world.mcp.http import _inject_identity, build_http_app
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _probe_tool(api, ctx, **kwargs) -> dict:
    """运行期注册用的探针工具（签名与玩法包工具一致）。"""
    return {"text": "pong"}


# ---------- 1. instructions：文案 + 运行期刷新 ----------


def test_instructions_empty_text_is_accurate(tmp_path):
    """零工具时文案必须说"没有任何可用工具"，不能说"未加载任何玩法包"。

    世界内容包（demo_world）是加载着的，只是不注册工具——v0.7.0 起内置只剩它，
    所以这句假的文案正是每个全新安装的默认说明书。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            mcp = build_mcp_server(engine)
            engine.attach_mcp(mcp)
            text = mcp.instructions or ""
            assert "没有任何可用工具" in text, text
            assert "未加载任何玩法包" not in text, text
            assert "没有注册工具" in text  # 给出真实原因（包在、但不提供工具）
        finally:
            await engine.terminate()

    _run(run())


def test_instructions_refresh_on_runtime_tool(tmp_path):
    """运行期注册工具 → instructions 真的跟着变（原先写错对象，刷新从未生效）。

    回归背景：`_refresh_instructions` 原先写 `mcp.settings.instructions`，而 SDK 的
    Settings **没有**该字段 → ValueError 被宽 except 吞成 debug 日志。真正的存储位
    是 lowlevel server（`FastMCP.instructions` 是只读 property 读它）。表现为
    **工具在、说明书不在**：装/启用玩法包后 `tools/list` 更新了，instructions 没变。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            mcp = build_mcp_server(engine)
            engine.attach_mcp(mcp)
            assert "没有任何可用工具" in (mcp.instructions or "")
            engine.register_tool("world_probe", _probe_tool, description="探针工具")
            text = mcp.instructions or ""
            assert "world_probe" in text, text
            assert "没有任何可用工具" not in text, text
            # 卸载路径同样刷新（真实流程里 clear_play_registrations 会先摘 engine
            # 注册表、再让 MCP 侧移除；这里照同序模拟）
            engine._tools.pop("world_probe", None)  # noqa: SLF001
            engine._sync_tool_remove("world_probe")  # noqa: SLF001
            assert "没有任何可用工具" in (mcp.instructions or "")
        finally:
            await engine.terminate()

    _run(run())


# ---------- 2. 批处理 JSON-RPC 的身份注入 ----------


def test_inject_identity_handles_batch_requests():
    """批处理数组也要注入身份（原先整段跳过 → 合法凭据被判"未认证"）。"""
    info = type("I", (), {"entity_id": "e1", "tier": "play"})()
    body = json.dumps(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "a"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "b"},
            },
        ]
    ).encode()
    out = json.loads(_inject_identity(body, info))
    assert out[0]["params"]["_meta"]["worlditor_entity_id"] == "e1"
    assert out[1]["params"]["_meta"]["worlditor_tier"] == "play"


def test_inject_identity_leaves_other_bodies_alone():
    """无 params / 非 JSON / 空体：原样返回（不引入无谓的重序列化）。"""
    info = type("I", (), {"entity_id": "e1", "tier": "play"})()
    no_params = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    assert _inject_identity(no_params, info) == no_params
    assert _inject_identity(b"not json", info) == b"not json"
    assert _inject_identity(b"", info) == b""


# ---------- 6. plays_changed 信号（前端 SSE 刷新视图 tab 的触发源） ----------


def test_plays_changed_signal_emitted(tmp_path):
    """玩法包集合变化 → 广播 `plays_changed`（装/卸包后前端无需整页刷新）。

    事件由 `PlayLoader._notify_plays_changed` 在 load_all / enable / disable /
    install / uninstall 后发出；载荷形状（自定义事件一律把数据放在 `data` 下）：
    `{"event": "plays_changed", "revision": …, "data": {"reason": …, "plays": […]}}`。
    刻意不写 world_log（纯 UI 信号）。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            install_demo_play(tmp_path / "plays")
            loader = PlayLoader(
                engine, plays_dir=tmp_path / "plays", worlditor_version="0.7.0"
            )
            queue = engine.subscribe()
            await loader.load_all()
            await loader.disable("worlditor_play_demo")
            await loader.enable("worlditor_play_demo")
            reasons: list[str] = []
            while True:
                try:
                    payload = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if payload.get("event") == "plays_changed":
                    reasons.append(str((payload.get("data") or {}).get("reason")))
            assert {"load_all", "disable", "enable"} <= set(reasons), reasons
        finally:
            await engine.terminate()

    _run(run())


# ---------- 7. plays_changed：世界激活集合变化 ----------


def test_plays_changed_signal_on_world_activation(tmp_path):
    """世界激活集合变化同样广播 `plays_changed`（reason = world_plays）。

    玩家看到哪些视图 tab 由**所在世界的激活集合**决定（`/views` 按世界过滤），所以
    管理员改某世界的 `play_ids` 时，站在该世界的玩家也该自动刷新——PlayLoader 那条
    信号只覆盖包的生命周期，世界级激活不在其中。只改名字则不该发信号。
    """

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            queue = engine.subscribe()

            def drain() -> list[str]:
                out: list[str] = []
                while True:
                    try:
                        payload = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if payload.get("event") == "plays_changed":
                        out.append(str((payload.get("data") or {}).get("reason")))
                return out

            await engine.update_world("default", play_ids=["worlditor_play_x"])
            assert drain() == ["world_plays"]
            # 只改名字：激活集合没变 → 不发信号
            await engine.update_world("default", name="改名了")
            assert drain() == []
        finally:
            await engine.terminate()

    _run(run())


# ---------- 3~5：需要 HTTP 双端口场景 ----------


async def _scenario(tmp_path: Path, fn, *, with_play: bool = True):
    plays = tmp_path / "plays"
    if with_play:
        install_demo_play(plays)
        # web/ 资源测试要一个"web 前缀的兄弟目录"，用来验路径校验（见下）
        evil = plays / "worlditor_play_demo" / "web-evil"
        evil.mkdir(parents=True, exist_ok=True)
        (evil / "secret.js").write_text("// 不该被 /web/ 路由读到\n", encoding="utf-8")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    loader = PlayLoader(engine, plays_dir=plays, worlditor_version="0.7.0")
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
            return await fn(admin_client, play_client, identity)
    finally:
        await engine.terminate()


async def _admin_token(identity) -> str:
    info = await identity.register_human("admin1", "pass123", admin_key="sekret")
    return info.token


def test_play_web_rejects_web_prefix_sibling(tmp_path):
    """`/plays/{id}/web/` 不得读到 `web-evil/` 这类"前缀相同"的兄弟目录。

    回归背景：`_play_web` 原先用 `str(target).startswith(str(web_dir))`，于是
    `<pkg>/web-evil/secret.js` 被判为"在 web/ 之内"（`is_relative_to` 会拒绝，
    PlayLoader 的路径安全检查用的正是后者）。`%2e%2e` 避免客户端把 `..` 规范化掉。
    """

    async def fn(admin_client, play_client, identity):
        token = await _admin_token(identity)
        h = {"Authorization": f"Bearer {token}"}
        ok = await play_client.get("/plays/worlditor_play_demo/web/view.js", headers=h)
        assert ok.status_code == 200, ok.text
        leak = await play_client.get(
            "/plays/worlditor_play_demo/web/%2e%2e/web-evil/secret.js", headers=h
        )
        assert leak.status_code == 404, leak.text
        normal = await play_client.get(
            "/plays/worlditor_play_demo/web/%2e%2e/main.py", headers=h
        )
        assert normal.status_code == 404, normal.text

    _run(_scenario(tmp_path, fn))


def test_admin_bad_int_returns_400_not_500(tmp_path):
    """G26：坏整数入参 → 400 + `{"error": …}`（原先 ValueError 冒到 Starlette → 500）。"""

    async def fn(admin_client, play_client, identity):
        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        for method, path, body in (
            ("GET", "/admin/accounts?page=abc", None),
            ("GET", "/admin/accounts?page_size=x", None),
            # ⚠ POST /admin/maps 已无整数参数（D45 删掉了出生点），故不在此列
            ("POST", "/admin/locations", {"map_id": "m1", "row": "x", "col": 0}),
            ("POST", "/admin/invite-codes", {"count": "x"}),
        ):
            resp = (
                await admin_client.get(path, headers=h)
                if method == "GET"
                else await admin_client.post(path, json=body, headers=h)
            )
            assert resp.status_code == 400, f"{path} -> {resp.status_code} {resp.text}"
            assert "必须是整数" in resp.json()["error"], resp.text

    _run(_scenario(tmp_path, fn))


def test_http_errors_are_json(tmp_path):
    """401 / 403 / 404 统一 JSON `{"error": …}`（Starlette 默认是纯文本）。"""

    async def fn(admin_client, play_client, identity):
        resp = await admin_client.get("/admin/plays")
        assert resp.status_code == 401
        assert "error" in resp.json(), resp.text

        player = await identity.register_human("p1", "pass123")
        resp = await admin_client.get(
            "/admin/plays", headers={"Authorization": f"Bearer {player.token}"}
        )
        assert resp.status_code == 403
        assert "error" in resp.json(), resp.text

        h = {"Authorization": f"Bearer {await _admin_token(identity)}"}
        # 路由层 404（未知路径）
        resp = await admin_client.get("/admin/definitely-not-a-route", headers=h)
        assert resp.status_code == 404
        assert "error" in resp.json(), resp.text
        # 业务层：地图不存在走 WorldError → 400（这是既有语义，不是 404）
        resp = await admin_client.get("/admin/maps/nope", headers=h)
        assert resp.status_code == 400
        assert "error" in resp.json(), resp.text

        resp = await play_client.get("/plays/nope/web/x.js", headers=h)
        assert resp.status_code == 404
        assert "error" in resp.json(), resp.text

    _run(_scenario(tmp_path, fn))
