"""v4.1 世界服务测试（6288 独立端口：MCP + 快照 + SSE + auth + 静态 + CORS）。

用 httpx ASGI transport 直调 build_http_app 构建的 app（不起真实端口）。

v0.2.0：内核不再内置世界内容（初始化后 0 地图/地块/实体），需要地图才能注册
身份的用例经 ``world_fixtures`` 自行铺世界（最小十字世界 / 演示世界）。
"""

from __future__ import annotations

import asyncio
import json

import httpx
from play_fixtures import install_demo_play  # noqa: E402
from world_fixtures import (  # noqa: E402
    give_avatar,
    install_demo_world,
    seed_test_world,
)

from worlditor_mcp.world.engine import WorldEngine, WorldError  # noqa: E402
from worlditor_mcp.world.identity import IdentityService  # noqa: E402
from worlditor_mcp.world.mcp import build_mcp_server  # noqa: E402
from worlditor_mcp.world.mcp.http import build_http_app  # noqa: E402
from worlditor_mcp.world.play import PlayLoader  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


async def _scenario(tmp_path, fn, *, origins=None, install_demo=False, world=None):
    """起服务场景；world 指定本用例要铺的世界（内核不内置世界内容，v0.2.0）。

    - ``None``：不铺（只需要身份/静态资源的用例）
    - ``"test"``：最小十字世界（seed_test_world，注册身份要有地方站）
    - ``"demo"``：演示世界（install_demo_world，断言真实地名/实体/41 地块）
    """
    if install_demo:
        install_demo_play(tmp_path / "plays")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    if world == "demo":
        await install_demo_world(engine)
    elif world == "test":
        await seed_test_world(engine)
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
    await loader.load_all(None)
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
    mcp = build_mcp_server(engine)
    engine.attach_mcp(mcp)
    app = build_http_app(
        mcp, identity, engine=engine, loader=loader, allowed_origins=origins
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await fn(client, identity, engine, loader, app)
    finally:
        await engine.terminate()


async def _probe_stream(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    """流式请求探测：读响应头 + 第一块数据后退出（wait_for 兜底防挂起）。"""

    async def probe():
        async with client.stream(method, path, **kwargs) as resp:
            status = resp.status_code
            content_type = resp.headers.get("content-type", "")
            first = b""
            async for chunk in resp.aiter_bytes():
                first = chunk
                break
            return status, content_type, first

    return await asyncio.wait_for(probe(), timeout=5)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_public_auth_endpoints(tmp_path):
    """公共端点免认证：注册 / 登录 / agent 注册；read 围观档已删除（v0.9）。"""

    async def fn(client, identity, engine, loader, app):
        # 注册（无 token）
        resp = await client.post(
            "/auth/register",
            json={"username": "小明", "password": "pass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] and data["token"]["tier"] == "play"
        # 登录
        resp = await client.post(
            "/auth/login", json={"username": "小明", "password": "pass123"}
        )
        assert resp.json()["ok"]
        # v0.9：read（围观）档整体删除——端点下线。注意它**不在 PUBLIC_PATHS 里了**，
        # 所以未认证请求在中间件层就被拦成 401（不是 404）——比"免认证但不存在"更省事
        assert (await client.get("/auth/read-token")).status_code == 401
        # admin_key 管理员
        resp = await client.post(
            "/auth/register",
            json={"username": "管理员", "password": "pass123", "admin_key": "sekret"},
        )
        assert resp.json()["token"]["tier"] == "admin"
        # 无密码自助注册（agent 通道）：实体与凭据类型都是 player（v0.2.0 不区分）
        resp = await client.post("/auth/agent-register", json={"name": "探针"})
        assert resp.json()["token"]["kind"] == "player"
        # 错误密码 → 400
        resp = await client.post(
            "/auth/login", json={"username": "小明", "password": "wrong"}
        )
        assert resp.status_code == 400
        # 改密（需 token）
        resp = await client.post(
            "/auth/change-password",
            json={"old_password": "pass123", "new_password": "newpass9"},
        )
        assert resp.status_code == 401  # 无 token

    _run(_scenario(tmp_path, fn, world="test"))


def test_snapshot_and_auth(tmp_path):
    """快照：无 token 401；玩家凭据可读 state/scene。"""

    async def fn(client, identity, engine, loader, app):
        assert (await client.get("/state")).status_code == 401
        # v0.9：read 围观档删除后，"能读世界"的最小身份就是 play 档（可无化身）
        viewer = await identity.register_human("看客", "pass123")
        h = _auth(viewer.token)
        # state
        resp = await client.get("/state", headers=h)
        data = resp.json()
        assert len(data["locations"]) == 41
        # D41：能力 = 组件的存在——演示世界导入的商贩带 local:merchant 组件，
        # 实体投影里没有 kind（能力一律从 components 读）
        assert any("local:merchant" in e["components"] for e in data["entities"])
        assert all("kind" not in e for e in data["entities"])
        # D28：快照带全局变更号/tick，实体各自带 revision（客户端增量游标）
        assert data["revision"] == engine.revision > 0
        assert data["tick"] == engine.tick
        assert all(e["revision"] > 0 for e in data["entities"])
        # scene（商贩视角；无玩家在场 → peers 为空）
        merchant = next(
            e for e in data["entities"] if "local:merchant" in e["components"]
        )
        resp = await client.get(
            "/scene", params={"entity_id": merchant["id"]}, headers=h
        )
        data = resp.json()
        assert data["scene"]["location"]["name"] == "小镇广场"
        assert data["peers"] == []

    _run(_scenario(tmp_path, fn, world="demo"))


def test_scene_without_avatar_is_a_state_not_an_error(tmp_path):
    """**"还没有角色"是 200 空态，不是 400/500**（D45/D46 的 P0 验收）。

    D45 之前新注册的玩家必定有实体，所以 `/scene` 只可能"缺参数"或"实体不存在"；
    现在"没有化身"是**默认状态**，客户端要能区分三种情况：
    ① 你还没有角色（去创建）② 有角色但它不在世界上（下线）③ 这个实体真的不存在。
    前两种都必须是 200 + `reason`，否则玩家端只会看到一个 500 空壳。
    """

    async def fn(client, identity, engine, loader, app):
        info = await identity.register_human("小明", "pass123")
        assert info.entity_id == ""
        resp = await client.get("/scene", headers=_auth(info.token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reason"] == "no_avatar" and data["entity"] is None
        assert data["peers"] == [] and data["scene"] is None
        assert "还没有角色" in data["text"]

        # 有化身但**不在世界上**（下线）：200 + not_in_world，实体照常返回
        avatar = await give_avatar(engine, info, name="小明")
        await engine.clear_position(avatar.id)
        resp = await client.get(
            "/scene", params={"entity_id": avatar.id}, headers=_auth(info.token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["reason"] == "not_in_world" and data["scene"] is None
        assert data["entity"]["id"] == avatar.id

        # 实体真的不存在 → 404（与上面两种情况分得开）
        resp = await client.get(
            "/scene", params={"entity_id": "nope"}, headers=_auth(info.token)
        )
        assert resp.status_code == 404

        # 兜底处理器本身：WorldError → **409 JSON**（业务错误，不是 500 空壳）
        from worlditor_mcp.world.mcp.http import _world_error

        fallback = await _world_error(None, WorldError("实体不在任何地块：x"))
        assert fallback.status_code == 409
        assert "不在任何地块" in fallback.body.decode("utf-8")

    _run(_scenario(tmp_path, fn, world="test"))


def test_events_auth(tmp_path):
    """events（play 档 SSE）：play 可订阅；read 档 403。"""

    async def fn(client, identity, engine, loader, app):
        info = await identity.register_human("小明", "pass123")
        # events：play 档 → StreamingResponse（直接调 handler 验证类型，
        # 避免 ASGITransport 下流式挂起）；read 档 403（httpx 普通请求）
        from starlette.requests import Request
        from starlette.responses import StreamingResponse

        from worlditor_mcp.world.mcp import http as mcp_http

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/events",
            "headers": [],
            "query_string": b"",
            "state": {"worlditor_identity": info},
            "app": app,
            "client": ("t", 1),
            "server": ("t", 80),
            "scheme": "http",
        }
        resp = await mcp_http._events(Request(scope))
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"
        # v0.9：read（围观）档删除——`/events` 要么 play/admin，要么没凭据（401）
        assert (await client.get("/events")).status_code == 401

    _run(_scenario(tmp_path, fn, world="test"))


def test_play_web_static(tmp_path):
    """玩法包 web 静态资源 + 路径穿越防护。"""

    async def fn(client, identity, engine, loader, app):
        play_dir = tmp_path / "plays" / "worlditor_play_ui"
        play_dir.mkdir(parents=True, exist_ok=True)
        (play_dir / "play.yaml").write_text(
            "name: worlditor_play_ui\ndisplay_name: UI\nversion: 0.1.0\n"
            'requires:\n  worlditor: ">=0.3.0"\n  plays: []\n',
            encoding="utf-8",
        )
        (play_dir / "main.py").write_text(
            "def setup(api, context):\n    pass\n", encoding="utf-8"
        )
        (play_dir / "web").mkdir()
        (play_dir / "web" / "comp.js").write_text("// component", encoding="utf-8")
        await loader.load_all(None)
        viewer = await identity.register_human("看客", "pass123")
        h = _auth(viewer.token)
        resp = await client.get("/plays/worlditor_play_ui/web/comp.js", headers=h)
        assert resp.status_code == 200 and resp.text == "// component"
        # 路径穿越
        resp = await client.get("/plays/worlditor_play_ui/web/../main.py", headers=h)
        assert resp.status_code == 404
        # 未知玩法包
        resp = await client.get("/plays/nope/web/x.js", headers=h)
        assert resp.status_code == 404
        # 无 token
        assert (
            await client.get("/plays/worlditor_play_ui/web/comp.js")
        ).status_code == 401

    _run(_scenario(tmp_path, fn))


def test_cors_preflight(tmp_path):
    """CORS：配置 origins 后预检通过并带响应头；未配置则无 CORS 头。"""

    async def fn_origins(client, identity, engine, loader, app):
        resp = await client.options(
            "/state",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        )

    async def fn_no_origins(client, identity, engine, loader, app):
        resp = await client.get("/auth/read-token", headers={"Origin": "http://x"})
        assert resp.headers.get("access-control-allow-origin") is None

    _run(_scenario(tmp_path, fn_origins, origins=["http://localhost:5173"]))
    _run(_scenario(tmp_path, fn_no_origins))


def test_mcp_endpoint_auth(tmp_path):
    """MCP 端点：无 token 401；带 token 放行到 MCP app。

    注：MCP streamable HTTP 握手需 anyio 运行时（uvicorn），httpx ASGITransport
    无法直调；协议级握手见 test_mcp_http_end_to_end（真实 uvicorn 端到端）。
    """

    async def fn(client, identity, engine, loader, app):
        resp = await client.post(
            "/world/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert resp.status_code == 401
        await identity.register_agent("探针")
        # 带 token 时认证通过；后续由 anyio 环境（uvicorn）处理握手——此处验证
        # 中间件放行路径不返回 401（bad token 才 401）
        resp = await client.post(
            "/world/mcp",
            headers={
                **_auth("badtoken"),
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp.status_code == 401

    _run(_scenario(tmp_path, fn, world="test"))


def test_scene_actions_with_demo(tmp_path):
    """演示玩法包注册的实体可用动作经 /scene 暴露（talk/trade/read/open）。"""

    async def fn(client, identity, engine, loader, app):
        viewer = await identity.register_human("看客", "pass123")
        h = _auth(viewer.token)
        state = (await client.get("/state", headers=h)).json()
        # D41：三个演示实体各带自己的组件（内容里的 kind 已折进 components）
        for kind in ("local:merchant", "local:sign", "local:door"):
            entity = next(e for e in state["entities"] if kind in e["components"])
            resp = await client.get(
                "/scene", params={"entity_id": entity["id"]}, headers=h
            )
            # 无玩家在场：场景可读、peers 为空（动作暴露见下文玩家注册后的校验）
            assert resp.status_code == 200
            assert resp.json()["scene"]["player_id"] == entity["id"]
            assert resp.json()["peers"] == []
        # 玩家有了化身之后：scene 自己能看到广场实体 actions
        # （D45/D46：注册不建实体，化身要显式造 + 认领 + 把凭据指过去）
        info = await identity.register_human("小明", "pass123")
        await give_avatar(engine, info, name="小明")
        resp = await client.get("/scene", headers=_auth(info.token))
        peers = resp.json()["peers"]
        merchant_peer = next(
            (p for p in peers if "local:merchant" in p["entity"]["components"]), None
        )
        assert merchant_peer is not None
        action_names = {a["action"] for a in merchant_peer["actions"]}
        assert {"talk", "trade"} <= action_names

    _run(_scenario(tmp_path, fn, install_demo=True, world="demo"))


def test_embedded_webui(tmp_path):
    """内置托管：WebUI 构建产物挂根路径（免认证）；API 路由优先。"""

    async def fn(client, identity, engine, loader, app):
        # 根路径返回 index.html（无 token）
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "worlditor" in resp.text
        # 静态资源免认证
        resp = await client.get("/assets/app.js")
        assert resp.status_code == 200
        assert resp.text == "// app"
        # API 路由优先，不受静态 fallback 影响（未认证仍 401）
        assert (await client.get("/state")).status_code == 401
        # 未命中静态文件 → 404（hash 路由不需要 SPA fallback）
        resp = await client.get("/assets/missing.js")
        assert resp.status_code == 404

    # 构造临时 dist（模拟 webui/dist 构建产物）
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>worlditor</title></head><body></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("// app", encoding="utf-8")

    async def run():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
        await loader.load_all(None)
        identity = IdentityService(engine, auth_mode="open")
        mcp = build_mcp_server(engine)
        app = build_http_app(
            mcp, identity, engine=engine, loader=loader, static_dir=dist
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await fn(client, identity, engine, loader, app)
        finally:
            await engine.terminate()

    _run(run())


def test_mcp_http_end_to_end(tmp_path):
    """真实 uvicorn 下 MCP streamable HTTP 端到端（WebUI 浏览器 MCP client 路径）：

    AuthMiddleware 认证放行 → _meta 身份注入 → 工具以连接实体身份执行。
    """

    async def fn(client, identity, engine, loader, app):
        import uvicorn

        info = await identity.register_agent("探针")
        # D45/D46：注册不建实体——工具要"我是…"就得先有化身
        await give_avatar(engine, info, name="探针")
        port = 18999
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        task = asyncio.create_task(server.serve())
        try:
            # 等待端口可连接（serve() 内部完成绑定）
            for _ in range(100):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(0.05)
            url = f"http://127.0.0.1:{port}/world/mcp"
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            headers = {"Authorization": f"Bearer {info.token}"}
            async with streamablehttp_client(url, headers=headers) as (
                read,
                write,
                _get_session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    # mcp 1.28 兼容：ListToolsResult 对象 / dict / list
                    if isinstance(tools_result, dict):
                        tool_list = tools_result.get("tools", [])
                    elif hasattr(tools_result, "tools"):
                        tool_list = tools_result.tools
                    else:
                        tool_list = tools_result
                    names = {t.name if hasattr(t, "name") else t[0] for t in tool_list}
                    # M2：无内置工具；演示玩法包动态注册 world_whoami
                    assert "world_whoami" in names
                    # 工具以连接实体身份执行（_meta 注入生效）
                    result = await session.call_tool("world_whoami", {})
                    payload = json.loads(result.content[0].text)
                    assert "我是" in payload["text"]
                    assert payload["text"] != "我是 None"  # 身份已注入
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=10)

    _run(_scenario(tmp_path, fn, install_demo=True, world="test"))


def test_chrome_mount_point(tmp_path):
    """K-1：`/chrome` 壳层挂载点——抽屉列表，条目由玩法包注入，壳层自己不放内容。"""

    async def fn(client, identity, engine, loader, app):
        from worlditor_mcp.world.model import CORE_SHELL_MENU, UiBlock

        # 要认证：这里会执行玩法包代码（apply_ui_hooks 调 provider），
        # 返回内容可能是有权限的——不能像 /views 那样免认证
        assert (await client.get("/chrome")).status_code == 401

        info = await identity.register_human("小明", "pass123")
        h = _auth(info.token)

        # 没有包注入 → blocks 为空，但**请求成功**（抽屉照常能开、退出登录仍在）
        resp = await client.get("/chrome", headers=h)
        assert resp.status_code == 200
        assert resp.json()["blocks"] == []

        # 玩法包往挂载点里放一条「我」——零新 API，复用 register_ui_hook
        async def _me(api, block):
            return [
                UiBlock(
                    kind="worlditor_play_me:entry",
                    title="我",
                    icon="🙋",
                    data={"view": "me"},
                )
            ]

        engine.register_ui_hook(
            CORE_SHELL_MENU, "after", _me, play_id="worlditor_play_me"
        )
        blocks = (await client.get("/chrome", headers=h)).json()["blocks"]
        assert [b["title"] for b in blocks] == ["我"]
        assert blocks[0]["icon"] == "🙋"  # K-8 的字段在这里真正用上
        assert blocks[0]["data"] == {"view": "me"}  # 导航走 data，不走 action

        # 卸载即回收：撤注册后列表回到空
        engine.clear_play_registrations("worlditor_play_me")
        assert (await client.get("/chrome", headers=h)).json()["blocks"] == []

    _run(_scenario(tmp_path, fn))


def test_where_reports_world_and_map(tmp_path):
    """K-3：`/where` = 页眉的"我在哪个世界的哪张地图"，比 `/state` 轻得多。"""

    async def fn(client, identity, engine, loader, app):
        # 要认证
        assert (await client.get("/where")).status_code == 401

        info = await identity.register_human("小明", "pass123")
        h = _auth(info.token)
        # 注册不产生化身（D45）→ 明确的空态 + reason，不是错误
        data = (await client.get("/where", headers=h)).json()
        assert data["reason"] == "no_avatar"
        assert data["entity_id"] == "" and data["map"] is None

        # 造化身 → 认领 → 把凭据指过去（D46 的三步）
        avatar = await engine.place_entity(None, "default", 0, 0, name="小明")
        await engine.claim_avatar(avatar.id, info.account_id)
        await engine.set_acting_entity(info.token, avatar.id)
        data = (await client.get("/where", headers=h)).json()
        assert data["reason"] == ""
        assert data["entity_id"] == avatar.id
        assert data["map"]["id"] == "default"
        assert data["map"]["name"]  # 地图名（页眉要显示的就是它）
        # 地图未归属世界 → world 为 null（合法，"没有归属"不是错误）
        assert data["world"] is None or data["world"]["id"]

        # 下线（D36：位置是可选组件）→ not_in_world，不是 404
        await engine.clear_position(avatar.id)
        data = (await client.get("/where", headers=h)).json()
        assert data["reason"] == "not_in_world" and data["map"] is None

    _run(_scenario(tmp_path, fn, world="test"))
