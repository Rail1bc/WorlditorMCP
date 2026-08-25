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

from .world.identity import IdentityError
from .world.mcp.http import AuthMiddleware, _identity_of
from .world.v4engine import WorldError


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
    return JSONResponse({"overrides": _engine(request).list_primitive_overrides()})


async def _tools(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"tools": _engine(request).list_tools()})


async def _views(request: Request) -> Response:
    _require_admin(request)
    return JSONResponse({"views": _engine(request).list_views()})


# ---------- 世界与组织树（D15） ----------


async def _worlds_list(request: Request) -> Response:
    _require_admin(request)
    engine = _engine(request)
    worlds = []
    for w in engine.list_worlds():
        d = w.to_dict()
        d["maps"] = engine.list_world_maps(w.id)
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
    _require_admin(request)
    store = _engine(request).store
    return JSONResponse(
        {
            "accounts": [
                {"id": a.id, "username": a.username, "role": a.role}
                for a in store.accounts.values()
            ],
            "tokens": [
                {"token": t.token[:8] + "...", "tier": t.tier, "kind": t.kind}
                for t in store.tokens.values()
            ],
            "invite_codes": _identity(request).list_invite_codes(),
        }
    )


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


async def _token_revoke(request: Request) -> Response:
    _require_admin(request)
    token = request.path_params["token"]
    ok = await _identity(request).revoke_token(token)
    if not ok:
        return _err(WorldError(f"凭据不存在：{token}"))
    return _ok()


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
        )
    except WorldError as e:
        return _err(e)
    return _ok({"id": m.id, "name": m.name})


async def _location_update(request: Request) -> Response:
    _require_admin(request)
    data = await _json_body(request)
    try:
        loc = await _engine(request).update_location(
            str(data.get("map_id") or ""),
            int(data.get("row") or 0),
            int(data.get("col") or 0),
            name=data.get("name"),
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
    from .world.v3model import WorldTemplate

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
        Route("/admin/invite-codes", _invite_create, methods=["POST"]),
        Route("/admin/tokens/{token}", _token_revoke, methods=["DELETE"]),
        Route("/admin/maps", _map_create, methods=["POST"]),
        Route("/admin/locations", _location_update, methods=["POST"]),
        Route("/admin/locations", _location_delete, methods=["DELETE"]),
        Route("/admin/connections", _connection_update, methods=["POST"]),
        Route("/admin/templates", _template_create, methods=["POST"]),
        Route(
            "/admin/templates/{template_id}",
            _template_delete,
            methods=["DELETE"],
        ),
        Route("/admin/entities", _entity_create, methods=["POST"]),
        Route(
            "/admin/entities/{entity_id}",
            _entity_delete,
            methods=["DELETE"],
        ),
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
