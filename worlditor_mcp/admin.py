"""管理端点（D16：管理端口 6289，默认 127.0.0.1；tier=admin 双保险）。

管理 REST 覆盖：玩法包管理（list/enable/disable/uninstall）、身份管理
（账户/凭据/邀请码）、世界与组织树（CRUD/激活配置/归属）、地图编辑
（地图/地块/连接/模板/实体）、原语覆盖与工具/视图状态。

所有端点要求 tier=admin（不信任端口隔离本身）；错误返回 {"error": msg}。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .world import WorldError
from .world.identity import IdentityError
from .world.mcp.http import AuthMiddleware, _identity_of, _play_web
from .world.model import location_to_dict


def _require_admin(request: Request) -> None:
    info = _identity_of(request.scope)
    if info is None:
        raise HTTPException(401, "未认证或凭据无效")
    if info.tier != "admin":
        raise HTTPException(403, "需要 admin 档凭据")


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "请求体必须是 JSON") from None
    return data if isinstance(data, dict) else {}


def _ok(data: Any = None) -> JSONResponse:
    return JSONResponse({"ok": True, **({} if data is None else {"data": data})})


def _err(exc: Exception) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


def _engine(request: Request) -> Any:
    return request.app.state.world_engine


def _loader(request: Request) -> Any:
    return request.app.state.world_loader


def _identity(request: Request) -> Any:
    return request.app.state.world_identity


# ---------- 玩法包管理（§4.3） ----------


async def _plays_list(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"plays": _loader(request).list_plays()})


async def _play_enable(request: Request) -> Response:
    _require_admin(request)
    try:
        await _loader(request).enable(request.path_params["play_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


async def _play_disable(request: Request) -> Response:
    _require_admin(request)
    try:
        await _loader(request).disable(request.path_params["play_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


async def _play_uninstall(request: Request) -> Response:
    _require_admin(request)
    try:
        await _loader(request).uninstall(request.path_params["play_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


# ---------- 状态总览（原语覆盖 / 工具 / 视图） ----------


async def _overrides(request: Request) -> Response:
    _require_admin(request)
    engine = _engine(request)
    return JSONResponse(
        {
            "overrides": engine.list_primitive_overrides(),
            "filters": engine.list_primitive_filters(),
        }
    )


async def _tools(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"tools": _engine(request).list_tools()})


async def _views(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"views": _engine(request).list_views()})


async def _meta(request: Request) -> Response:
    """前端模式识别：管理端 = admin（前端据此切换管理界面，与玩家端分离）。"""
    return JSONResponse({"mode": "admin"})


async def _services(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"services": _engine(request).list_services()})


# ---------- 世界与组织树（D15） ----------


async def _worlds_list(request: Request) -> Response:
    _require_admin(request)
    engine = _engine(request)
    worlds = []
    for w in engine.list_worlds():
        d = w.to_dict()
        d["maps"] = [
            {"id": map_id, "folder_id": engine.store.map_folder.get(map_id)}
            for map_id in engine.list_world_maps(w.id)
        ]
        d["folders"] = [f.to_dict() for f in engine.list_folders(w.id)]
        worlds.append(d)
    return JSONResponse({"worlds": worlds})


async def _world_create(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        world = await _engine(request).create_world(
            str(data.get("id") or ""),
            str(data.get("name") or ""),
            desc=str(data.get("desc") or ""),
            play_ids=data.get("play_ids"),
        )
    except WorldError as e:
        return _err(e)
    return _ok(world.to_dict())


async def _world_update(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        world = await _engine(request).update_world(
            request.path_params["world_id"],
            name=data.get("name"),
            desc=data.get("desc"),
            play_ids=data.get("play_ids"),
        )
    except WorldError as e:
        return _err(e)
    return _ok(world.to_dict())


async def _world_delete(request: Request) -> Response:
    _require_admin(request)
    try:
        await _engine(request).delete_world(request.path_params["world_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


async def _world_assign_map(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        await _engine(request).assign_map(
            str(data.get("map_id") or ""),
            request.path_params["world_id"],
            folder_id=data.get("folder_id"),
        )
    except WorldError as e:
        return _err(e)
    return _ok()


async def _world_unassign_map(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    await _engine(request).unassign_map(str(data.get("map_id") or ""))
    return _ok()


async def _folder_create(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        folder = await _engine(request).create_folder(
            request.path_params["world_id"],
            str(data.get("name") or ""),
            parent_id=data.get("parent_id"),
            sort=int(data.get("sort") or 0),
        )
    except WorldError as e:
        return _err(e)
    return _ok(folder.to_dict())


async def _folder_rename(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        await _engine(request).rename_folder(
            request.path_params["folder_id"], str(data.get("name") or "")
        )
    except WorldError as e:
        return _err(e)
    return _ok()


async def _folder_move(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        await _engine(request).move_folder(
            request.path_params["folder_id"], data.get("parent_id")
        )
    except WorldError as e:
        return _err(e)
    return _ok()


async def _folder_delete(request: Request) -> Response:
    _require_admin(request)
    try:
        await _engine(request).delete_folder(request.path_params["folder_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


# ---------- 身份管理 ----------


async def _accounts(request: Request) -> Response:
    """账户检索（q 用户名子串 / role 过滤 / 分页 / 排序）+ 凭据与邀请码概览。

    账户行附带：创建时间、关联玩家实体（名称/位置/最近活跃）、未吊销
    凭据数——对应管理端「账户管理」页的复杂检索与管理（v0.1.12）。
    """
    _require_admin(request)
    params = request.query_params
    result = _identity(request).search_accounts(
        q=params.get("q", ""),
        role=params.get("role", ""),
        page=int(params.get("page") or 1),
        page_size=int(params.get("page_size") or 200),
        sort=params.get("sort", "created_desc"),
    )
    store = _engine(request).store
    return JSONResponse(
        {
            **result,
            "tokens": [
                {"token": t.token[:8] + "...", "tier": t.tier, "kind": t.kind}
                for t in store.tokens.values()
            ],
            "invite_codes": _identity(request).list_invite_codes(),
        }
    )


async def _account_tokens(request: Request) -> Response:
    """账户未吊销凭据明细（完整 token 供吊销；管理端详情用）。"""
    _require_admin(request)
    return JSONResponse(
        {
            "tokens": _identity(request).list_account_tokens(
                request.path_params["account_id"]
            )
        }
    )


async def _account_delete(request: Request) -> Response:
    """永久注销账户（删账户 + 吊销凭据 + 删除玩家实体，不可恢复）。"""
    _require_admin(request)
    try:
        await _identity(request).delete_account(request.path_params["account_id"])
    except IdentityError as e:
        return _err(e)
    return _ok()


async def _account_update(request: Request) -> Response:
    """变更角色（user/admin）：吊销全部凭据，对方重新登录生效。"""
    _require_admin(request)
    data = await _json_body(request)
    try:
        result = await _identity(request).set_account_role(
            request.path_params["account_id"], str(data.get("role") or "")
        )
    except IdentityError as e:
        return _err(e)
    return _ok(result)


async def _invite_create(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        codes = await _identity(request).create_invite_codes(
            max(1, int(data.get("count") or 1))
        )
    except IdentityError as e:
        return _err(e)
    return _ok({"codes": codes})


async def _invite_revoke(request: Request) -> Response:
    _require_admin(request)
    ok = await _identity(request).revoke_invite_code(request.path_params["code"])
    return _ok({"revoked": ok})


async def _token_revoke(request: Request) -> Response:
    _require_admin(request)
    token = request.path_params["token"]
    ok = await _identity(request).revoke_token(token)
    if not ok:
        return _err(WorldError(f"凭据不存在：{token}"))
    return _ok()


# ---------- 地图读（v0.1.12：管理端地图编辑器数据面） ----------


async def _maps_list(request: Request) -> Response:
    """地图列表（含世界归属 / 地块数 / 实体数）。"""
    _require_admin(request)
    engine = _engine(request)
    maps = []
    for m in engine.list_maps():
        locations = [loc for loc in engine.list_locations() if loc.map_id == m.id]
        maps.append(
            {
                "id": m.id,
                "name": m.name,
                "description": m.description.to_dict() if m.description else None,
                "timezone": m.timezone,
                "spawn_row": m.spawn_row,
                "spawn_col": m.spawn_col,
                "visible": m.visible,
                "world_id": engine.map_world(m.id),
                "location_count": len(locations),
                "entity_count": len(engine.list_entities(map_id=m.id)),
            }
        )
    return JSONResponse({"maps": maps})


async def _map_detail(request: Request) -> Response:
    """地图详情：元数据 + 全部地块（connections slot 全量）+ 实体 + 归属。"""
    _require_admin(request)
    engine = _engine(request)
    map_id = request.path_params["map_id"]
    m = engine.get_map(map_id)
    if m is None:
        return _err(WorldError(f"地图不存在：{map_id}"))
    locations = [
        location_to_dict(loc) for loc in engine.list_locations() if loc.map_id == map_id
    ]
    entities = [e.to_dict() for e in engine.list_entities(map_id=map_id)]
    return JSONResponse(
        {
            "map": {
                "id": m.id,
                "name": m.name,
                "description": m.description.to_dict() if m.description else None,
                "timezone": m.timezone,
                "spawn_row": m.spawn_row,
                "spawn_col": m.spawn_col,
                "visible": m.visible,
                "world_id": engine.map_world(map_id),
            },
            "locations": locations,
            "entities": entities,
        }
    )


async def _templates_list(request: Request) -> Response:
    """模板列表（GET /admin/templates：复制预设）。"""
    _require_admin(request)
    return JSONResponse(
        {
            "templates": [
                {"id": t.id, "name": t.name, "data": t.data}
                for t in _engine(request).store.templates.values()
            ]
        }
    )


# ---------- 玩法包管理页（v0.1.12：注册协议代理） ----------


async def _play_pages(request: Request) -> Response:
    """管理页清单（管理端导航：玩法包注册的管理页入口）。"""
    _require_admin(request)
    return JSONResponse({"pages": _engine(request).list_admin_pages()})


async def _play_page_action(request: Request) -> Response:
    """管理页动作代理：锁内调用玩法包 handler（数据语义归玩法包）。"""
    _require_admin(request)
    data = await _json_body(request)
    try:
        result = await _engine(request).call_admin_page_action(
            request.path_params["play_id"],
            request.path_params["page_key"],
            request.path_params["action"],
            **data,
        )
    except WorldError as e:
        return _err(e)
    return _ok(result)


# ---------- 地图编辑（D14 管理人类入口） ----------


async def _map_create(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        m = await _engine(request).create_map(
            str(data.get("id") or ""),
            str(data.get("name") or ""),
            description=data.get("description"),
            timezone=data.get("timezone"),
            spawn_row=int(data.get("spawn_row") or 0),
            spawn_col=int(data.get("spawn_col") or 0),
            visible=str(data.get("visible") or "public"),
        )
    except WorldError as e:
        return _err(e)
    return _ok({"id": m.id, "name": m.name})


async def _map_update(request: Request) -> Response:
    """地图属性编辑（PATCH；body 未提供的字段不变；description=null 清空）。"""
    _require_admin(request)
    data = await _json_body(request)
    want: dict[str, Any] = {}
    for key in ("name", "description", "timezone", "visible"):
        if key in data:
            want[key] = data[key]
    if data.get("spawn_row") is not None or data.get("spawn_col") is not None:
        want["spawn_row"] = int(data.get("spawn_row") or 0)
        want["spawn_col"] = int(data.get("spawn_col") or 0)
    try:
        m = await _engine(request).update_map(request.path_params["map_id"], **want)
    except WorldError as e:
        return _err(e)
    return _ok({"id": m.id, "name": m.name})


async def _map_delete(request: Request) -> Response:
    _require_admin(request)
    try:
        await _engine(request).delete_map(request.path_params["map_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


async def _location_upsert(request: Request) -> Response:
    """地块 upsert（地图编辑器）：不存在 = 创建（name 必填），存在 = 更新。

    坐标只读；description = None 显式清空；纯字符串/分时段 dict 均接受。
    """
    _require_admin(request)
    data = await _json_body(request)
    engine = _engine(request)
    map_id = str(data.get("map_id") or "")
    row, col = int(data.get("row") or 0), int(data.get("col") or 0)
    try:
        if engine.get_location(map_id, row, col) is None:
            loc = await engine.create_location(
                map_id,
                row,
                col,
                name=str(data.get("name") or ""),
                description=data.get("description"),
            )
        else:
            loc = await engine.update_location(
                map_id,
                row,
                col,
                name=str(data.get("name") or ""),
                description=data.get("description"),
            )
    except WorldError as e:
        return _err(e)
    return _ok({"map_id": loc.map_id, "row": loc.row, "col": loc.col})


async def _location_delete(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        await _engine(request).delete_location(
            str(data.get("map_id") or ""),
            int(data.get("row") or 0),
            int(data.get("col") or 0),
        )
    except WorldError as e:
        return _err(e)
    return _ok()


async def _connection_update(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        await _engine(request).update_connection(
            str(data.get("map_id") or ""),
            int(data.get("row") or 0),
            int(data.get("col") or 0),
            str(data.get("direction") or ""),
            enabled=data.get("enabled"),
            paths=data.get("paths"),
        )
    except WorldError as e:
        return _err(e)
    return _ok()


async def _template_create(request: Request) -> Response:
    _require_admin(request)
    from .world import WorldTemplate

    data = await _json_body(request)
    try:
        template = WorldTemplate(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            data=json.loads(json.dumps(data.get("data") or {})),
        )
        await _engine(request).save_template(template)
    except WorldError as e:
        return _err(e)
    return _ok({"id": template.id})


async def _template_delete(request: Request) -> Response:
    _require_admin(request)
    try:
        await _engine(request).delete_template(request.path_params["template_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


async def _entity_create(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        entity = await _engine(request).place_entity(
            str(data.get("kind") or ""),
            str(data.get("map_id") or ""),
            int(data.get("row") or 0),
            int(data.get("col") or 0),
            name=data.get("name"),
            desc=str(data.get("desc") or ""),
            attrs=data.get("attrs"),
            state=data.get("state"),
        )
    except WorldError as e:
        return _err(e)
    return _ok({"id": entity.id})


async def _entity_update(request: Request) -> Response:
    """实体编辑（PATCH；body 未提供的字段不变；attrs/state 整体替换）。"""
    _require_admin(request)
    data = await _json_body(request)
    want: dict[str, Any] = {}
    for key in ("name", "desc", "attrs", "state"):
        if key in data:
            want[key] = data[key]
    try:
        entity = await _engine(request).update_entity(
            request.path_params["entity_id"], **want
        )
    except WorldError as e:
        return _err(e)
    return _ok({"id": entity.id})


async def _entity_delete(request: Request) -> Response:
    _require_admin(request)
    try:
        await _engine(request).remove_entity(request.path_params["entity_id"])
    except WorldError as e:
        return _err(e)
    return _ok()


# ---------- 组装 ----------


def build_admin_app(
    identity: Any,
    *,
    engine: Any = None,
    loader: Any = None,
    static_dir: Any = None,
) -> Any:
    """管理端口 ASGI app：认证（/auth/* 公共）+ /admin/* REST + 管理 WebUI 静态。

    与玩家 app 共享同一引擎实例（app.state）；所有 /admin/* 端点要求
    tier=admin（不信任端口隔离本身，D16 双保险）。
    """
    routes: list = [
        Route("/auth/register", _register_route, methods=["POST"]),
        Route("/auth/login", _login_route, methods=["POST"]),
        Route("/auth/agent-register", _agent_register_route, methods=["POST"]),
        Route("/admin/plays", _plays_list),
        Route("/admin/plays/{play_id}/enable", _play_enable, methods=["POST"]),
        Route("/admin/plays/{play_id}/disable", _play_disable, methods=["POST"]),
        Route("/admin/plays/{play_id}/uninstall", _play_uninstall, methods=["POST"]),
        Route("/admin/overrides", _overrides),
        Route("/admin/tools", _tools),
        Route("/admin/views", _views),
        Route("/admin/services", _services),
        Route("/meta", _meta),
        Route("/admin/worlds", _worlds_list),
        Route("/admin/worlds", _world_create, methods=["POST"]),
        Route("/admin/worlds/{world_id}", _world_update, methods=["PATCH"]),
        Route("/admin/worlds/{world_id}", _world_delete, methods=["DELETE"]),
        Route(
            "/admin/worlds/{world_id}/assign-map",
            _world_assign_map,
            methods=["POST"],
        ),
        Route(
            "/admin/worlds/{world_id}/unassign-map",
            _world_unassign_map,
            methods=["POST"],
        ),
        Route(
            "/admin/worlds/{world_id}/folders",
            _folder_create,
            methods=["POST"],
        ),
        Route("/admin/folders/{folder_id}", _folder_rename, methods=["PATCH"]),
        Route("/admin/folders/{folder_id}/move", _folder_move, methods=["POST"]),
        Route("/admin/folders/{folder_id}", _folder_delete, methods=["DELETE"]),
        Route("/admin/accounts", _accounts),
        Route("/admin/accounts/{account_id}", _account_delete, methods=["DELETE"]),
        Route("/admin/accounts/{account_id}", _account_update, methods=["PATCH"]),
        Route("/admin/accounts/{account_id}/tokens", _account_tokens),
        Route("/admin/invite-codes", _invite_create, methods=["POST"]),
        Route("/admin/invite-codes/{code}", _invite_revoke, methods=["DELETE"]),
        Route("/admin/tokens/{token}", _token_revoke, methods=["DELETE"]),
        Route("/admin/maps", _map_create, methods=["POST"]),
        Route("/admin/maps", _maps_list),
        Route("/admin/maps/{map_id}", _map_detail),
        Route("/admin/maps/{map_id}", _map_update, methods=["PATCH"]),
        Route("/admin/maps/{map_id}", _map_delete, methods=["DELETE"]),
        Route("/admin/locations", _location_upsert, methods=["POST"]),
        Route("/admin/locations", _location_delete, methods=["DELETE"]),
        Route("/admin/connections", _connection_update, methods=["POST"]),
        Route("/admin/templates", _template_create, methods=["POST"]),
        Route("/admin/templates", _templates_list),
        Route(
            "/admin/templates/{template_id}",
            _template_delete,
            methods=["DELETE"],
        ),
        Route("/admin/entities", _entity_create, methods=["POST"]),
        Route("/admin/entities/{entity_id}", _entity_update, methods=["PATCH"]),
        Route(
            "/admin/entities/{entity_id}",
            _entity_delete,
            methods=["DELETE"],
        ),
        Route("/admin/play-pages", _play_pages),
        Route(
            "/admin/play-pages/{play_id}/{page_key}/{action}",
            _play_page_action,
            methods=["POST"],
        ),
        # 玩法包 web 资源（管理页组件加载；认证后访问，同玩家端口语义）
        Route("/plays/{play_id}/web/{path:path}", _play_web, methods=["GET"]),
    ]
    public_exact: tuple[str, ...] = ()
    if static_dir is not None:
        dist = Path(static_dir)
        if dist.is_dir():
            routes.append(
                Mount(
                    "/", app=StaticFiles(directory=str(dist), html=True), name="webui"
                )
            )
            public_exact = ("/",)
    app = Starlette(routes=routes)
    app.state.world_engine = engine
    app.state.world_identity = identity
    app.state.world_loader = loader
    return AuthMiddleware(
        app,
        identity,
        public_paths=(
            "/auth/register",
            "/auth/login",
            "/auth/agent-register",
            "/meta",
            "/assets",
            "/favicon.ico",
        ),
        public_exact=public_exact,
    )


# ---------- 认证端点（复用玩家端语义，避免与 mcp/http 循环依赖） ----------


async def _register_route(request: Request) -> Response:
    identity: Any = request.app.state.world_identity
    data = await _json_body(request)
    try:
        info = await identity.register_human(
            str(data.get("username") or ""),
            str(data.get("password") or ""),
            invite_code=data.get("invite_code"),
            admin_key=data.get("admin_key"),
        )
    except IdentityError as e:
        return _err(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})


async def _login_route(request: Request) -> Response:
    identity: Any = request.app.state.world_identity
    data = await _json_body(request)
    try:
        info = await identity.login(
            str(data.get("username") or ""), str(data.get("password") or "")
        )
    except IdentityError as e:
        return _err(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})


async def _agent_register_route(request: Request) -> Response:
    identity: Any = request.app.state.world_identity
    data = await _json_body(request)
    try:
        info = await identity.register_agent(
            str(data.get("name") or ""), invite_code=data.get("invite_code")
        )
    except IdentityError as e:
        return _err(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})
