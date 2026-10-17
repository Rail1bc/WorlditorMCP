"""世界服务（独立端口 6288；B7 修订为独立 uvicorn 服务）。

WebUI 与远程 MCP 客户端的**单一连接源**：

- ``/world/mcp``：MCP streamable HTTP（唯一动作通道，B10）
- ``/state`` / ``/scene``（含实体可用动作）：只读快照
- ``/events``：SSE 事件流（事件总线序列化出口，B11）
- ``/views`` / ``/chrome``：视图清单（免认证）与**壳层挂载点**（要认证，K-1）
- ``/auth/*``：身份注册 / 登录 / agent 注册 / 注销 / 改密（B13；v0.9 删掉 read 围观档）
- ``/plays/<id>/web/*``：玩法包 web 静态资源（B9）

鉴权：AuthMiddleware 校验 ``Authorization: Bearer <token>`` 或 ``?token=``，
身份存入 scope.state（handler 与 MCP _meta 注入共用）；公共路径（注册类）
白名单放行。CORS 按配置的 allowed_origins 放行（WebUI 独立域）。
"""

from __future__ import annotations

import json
import mimetypes
import urllib.parse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route

from ..engine import WorldError
from ..identity import IdentityError, IdentityService, TokenInfo

_META_ENTITY_KEY = "worlditor_entity_id"
_META_TIER_KEY = "worlditor_tier"
_META_ACCOUNT_KEY = "worlditor_account_id"
_META_USERNAME_KEY = "worlditor_username"
_META_TOKEN_KEY = "worlditor_token"
_SCOPE_IDENTITY_KEY = "worlditor_identity"


async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """``HTTPException`` → 统一 JSON 错误体 ``{"error": …}``。

    Starlette 默认渲染成纯文本，跟本模块中间件那头发出的 JSON 401 形态不一致，
    客户端统一按 JSON 解析时会崩（403/404 都走这条）。
    """
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


async def _world_error(request: Request, exc: Exception) -> JSONResponse:
    """``WorldError`` → **409 JSON**（可读文案），不再是 500。

    这些是**业务错误**（"地块不存在"、"实体不在任何地块"、"你还没有角色"），
    不是服务端故障。挂上它之前它们会穿到 Starlette 变成一屏 500——而 D36 让
    "实体不在世界上"成了合法状态、D45 之后它更是**默认状态**（新注册的凭据没有
    化身），所以"读一个不在世界上的实体"必须给出明确答复而不是 500。

    状态码取 409：请求本身合法，是**当前世界状态**让它做不了（不是没权限、不是
    找不到 URL）。文案原样透出（内核 WorldError 的消息本来就是写给用户看的）。
    """
    return JSONResponse({"error": str(exc)}, status_code=409)


# 公共路径（免认证）：自助注册类端点（B13 自助注册不依赖管理员）
PUBLIC_PATHS = (
    "/auth/register",
    "/auth/login",
    "/auth/agent-register",
    "/meta",
    "/views",
)


def _bearer_token(authorization: str) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _query_token(scope: dict) -> str:
    query = scope.get("query_string", b"").decode("latin-1")
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key == "token":
            return urllib.parse.unquote(value)
    return ""


class AuthMiddleware:
    """ASGI 认证中间件：校验 token、身份入 scope、注入 MCP 请求 _meta。

    Args:
        public_paths: 前缀匹配免认证的路径（注册类端点）。
        public_exact: 精确匹配免认证的路径（如 "/" 内置 WebUI 首页）。
    """

    def __init__(
        self,
        app: Any,
        identity: IdentityService,
        *,
        public_paths: tuple[str, ...] = (),
        public_exact: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.identity = identity
        self.public_paths = public_paths
        self.public_exact = public_exact

    @property
    def state(self) -> Any:
        """转发内部 Starlette app 的 state（handler 经 request.app.state 取依赖）。"""
        return self.app.state

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_public = path in self.public_exact or any(
            path == p or path.startswith(f"{p}/") for p in self.public_paths
        )
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        token = _bearer_token(headers.get("authorization", "")) or _query_token(scope)
        # 公共路径 = **不要求**凭据，不等于"忽略凭据"：带了凭据照样解析身份——
        # `/views` 就靠这一点按调用者所在世界过滤（v0.5.2 修：原先公共路径直接
        # 放行不解析 token，导致已登录玩家的视图列表恒按匿名/默认世界算）
        info = self.identity.resolve(token) if token else None
        if info is None and not is_public:
            await _send_json(send, scope, 401, {"error": "未认证或凭据无效"})
            return
        if info is not None:
            scope.setdefault("state", {})[_SCOPE_IDENTITY_KEY] = info
            if scope["method"] == "POST":
                receive = self._wrap_receive(receive, info)
        await self.app(scope, receive, send)

    def _wrap_receive(self, receive: Any, info: Any) -> Any:
        """包装 receive：合并 body 并把身份注入 params._meta。"""

        async def wrapped():
            chunks = []
            more = True
            while more:
                message = await receive()
                chunks.append(message.get("body") or b"")
                more = bool(message.get("more_body", False))
            body = _inject_identity(b"".join(chunks), info)
            return {"type": "http.request", "body": body, "more_body": False}

        return wrapped


def _inject_identity(body: bytes, info: Any) -> bytes:
    """JSON-RPC 请求体：在 params._meta 注入 worlditor 身份字段。

    支持**单个请求对象**与**批处理数组**（JSON-RPC 2.0 batch）。批处理原先被整段跳过
    （`isinstance(obj, dict)` 不成立即 return），于是持合法 play 凭据的客户端发批量
    `tools/call` 一律拿不到 `_meta` → 被工具入口判成"未认证"，**静默失败**。
    """
    if not body:
        return body
    try:
        obj = json.loads(body)
    except ValueError:
        return body
    if isinstance(obj, list):
        # 注意：这里不能用 any(...) —— 生成器短路会让第二个请求之后全都不被注入
        changed = False
        for item in obj:
            if _inject_into_request(item, info):
                changed = True
        if not changed:
            return body
        return json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if not _inject_into_request(obj, info):
        return body
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _inject_into_request(obj: Any, info: Any) -> bool:
    """把身份写进单个 JSON-RPC 请求对象的 ``params._meta``；返回是否有改动。

    ``params`` 不是对象时不动（与单请求路径的老行为一致：无参数请求原样放行）。

    注入 5 个字段：行动实体（**可为空**）、档位、主体 id、主体显示名、凭据串。
    ``worlditor_token`` 在这里是**服务端内部的句柄**：``api.act_as`` 要写"这份
    凭据以哪具实体行动"，而 MCP 的会话任务与 HTTP 请求不在同一个 contextvar 上下文
    里，只有随消息走的 ``_meta`` 能可靠送达。它只存在服务端（客户端发的 ``_meta``
    会被这里**覆盖**，响应里也不回显）。
    """
    if not isinstance(obj, dict):
        return False
    params = obj.get("params")
    if not isinstance(params, dict):
        return False
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    meta[_META_ENTITY_KEY] = info.entity_id
    meta[_META_TIER_KEY] = info.tier
    # 后三个字段用 getattr 取：老调用方/测试桩可能只有前两个（鸭子类型），
    # 缺了就等于"没有主体"——不该因此炸掉整个请求注入。
    meta[_META_ACCOUNT_KEY] = getattr(info, "account_id", None) or ""
    meta[_META_USERNAME_KEY] = getattr(info, "username", None) or ""
    meta[_META_TOKEN_KEY] = getattr(info, "token", "") or ""
    params["_meta"] = meta
    return True


async def _send_json(send: Any, scope: dict, status: int, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ---------- 业务端点（WebUI 数据源；鉴权经中间件 + tier 检查） ----------


def _identity_of(scope: dict) -> TokenInfo | None:
    return scope.get("state", {}).get(_SCOPE_IDENTITY_KEY)


def meta_payload(mode: str, info: TokenInfo | None) -> dict:
    """``/meta`` 响应体：端口模式 + **这次连接**的身份状态（两个端口共用）。

    ``authenticated`` 存在的理由是一个真实缺陷：前端原先只凭 localStorage 里
    "有一串 token"就认定已登录（于是跳过登录页），而唯一会清掉失效凭据的自愈
    路径是"某个非 ``/auth`` 请求收到 401"——可启动时只打 ``/meta`` 与 ``/views``，
    两个都是**免认证端点、恒 200**。于是删库/吊销凭据后前端永远发现不了：玩家停在
    一个看得见、点什么都失败的空壳里，界面上没有任何出口。

    这里把"凭据是否有效"变成启动时必打的那一次请求的返回内容：无凭据或解析不出
    → ``authenticated: false``，前端据此清凭据回登录页。端点本身仍免认证（登录页
    要靠它判断端口模式），所以状态用**字段**表达、而不是 401。

    Args:
        mode: 端口模式（``play`` / ``admin``）——前端据此切换两套界面。
        info: 中间件解析出的凭据（公共路径也解析；无/失效为 None）。

    Returns:
        响应体 dict；``info`` 为 None 时只有 mode 与 authenticated。
    """
    payload: dict[str, Any] = {"mode": mode, "authenticated": info is not None}
    if info is not None:
        payload["tier"] = info.tier
        payload["entity_id"] = info.entity_id
        payload["username"] = info.username or ""
        # D46：主体（账户）id 是**稳定的键**（换化身、重登都不变），前端与玩法包
        # 用它做自己 roster 的索引；entity_id 只是"这次以哪具行动"，可能为空。
        payload["principal"] = info.account_id or ""
    return payload


def _require_tier(info: TokenInfo | None, tiers: tuple[str, ...]) -> None:
    if info is None:
        raise HTTPException(401, "未认证或凭据无效")
    if info.tier not in tiers:
        raise HTTPException(403, f"需要 {'/'.join(tiers)} 档凭据")


async def _state(request: Request) -> Response:
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    viewer_id = info.entity_id if info else None
    tier = info.tier if info else ""
    # G1 可见性：private 地图仅"在场"玩家（+admin）可见，其地块/实体同步隐藏
    visible_maps = [
        m for m in engine.list_maps() if engine.map_visible_to(m.id, viewer_id, tier)
    ]
    visible_ids = {m.id for m in visible_maps}
    from ..model import location_to_dict, map_to_dict

    return JSONResponse(
        {
            # D28：全局变更号 + tick 窗口（客户端缓存失效/增量刷新用；实体各自也带）
            "revision": engine.revision,
            "tick": engine.tick,
            "maps": [map_to_dict(m) for m in visible_maps],
            "locations": [
                location_to_dict(loc)
                for loc in engine.list_locations()
                if loc.map_id in visible_ids
            ],
            "entities": [
                e.to_dict() for e in engine.list_entities() if e.map_id in visible_ids
            ],
        }
    )


async def _scene(request: Request) -> Response:
    """单实体场景快照（``entity_id`` 缺省 = 调用者自己）。

    D45/D46：**"还没有角色"是 200 + 明确的空态**，不是 400/500——新注册的凭据
    本来就没有化身，客户端要能区分"你还没角色"（去创建）与"这个实体不存在"
    （真的错了）。这两种情况下 ``scene`` 都是 null，``reason`` 给出机器可读的原因。
    """
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    entity_id = request.query_params.get("entity_id") or (
        info.entity_id if info else ""
    )
    if not entity_id:
        return JSONResponse(
            {
                "entity": None,
                "scene": None,
                "peers": [],
                "reason": "no_avatar",
                "text": "你还没有角色：先去创建一个，再回来看这里。",
            }
        )
    entity = engine.get_entity(entity_id)
    if entity is None:
        raise HTTPException(404, f"实体不存在：{entity_id}")
    # **问自己永远看得见**（包括"我不在世界上了"这个答案）：观察权限是拿来挡
    # 别人的；对自己套用它，"你下线了"会变成 404「场景不存在」——客户端分不出
    # 这两种情况（而 D45 之后"没有化身/不在世界上"是常态，更要说清楚）。
    mine = bool(info and entity.id == info.entity_id)
    if not mine and not engine.can_observe_entity(entity.id, info.entity_id, info.tier):
        raise HTTPException(404, "场景不存在")
    if not entity.has_position():
        # D36：位置是可选组件，缺失 = 不在世界上（下线 / 收在容器里）。
        # 这不是错误，但也没有"当前地块"可讲——给出明确状态，而不是让
        # require_position() 抛 WorldError（那会变成一屏 500）。
        return JSONResponse(
            {
                "entity": {
                    **entity.to_dict(),
                    "actions": [
                        a.to_dict()
                        for a in engine.list_actions(
                            entity.id, viewer_id=info.entity_id, tier=info.tier
                        )
                    ],
                },
                "scene": None,
                "peers": [],
                "reason": "not_in_world",
                "text": f"「{entity.name}」现在不在世界上（不在任何地块）。",
            }
        )
    scene = engine._build_scene(entity)
    peers = [
        p
        for p in engine.list_entities(
            entity.map_id, entity.row, entity.col, viewer_id=info.entity_id
        )
        if p.id != entity.id
    ]
    return JSONResponse(
        {
            "entity": {
                **entity.to_dict(),
                "actions": [
                    a.to_dict()
                    for a in engine.list_actions(
                        entity.id, viewer_id=info.entity_id, tier=info.tier
                    )
                ],
            },
            "scene": scene.to_dict(),
            "peers": [
                {
                    "entity": p.to_dict(),
                    "actions": [
                        a.to_dict()
                        for a in engine.list_actions(
                            p.id, viewer_id=info.entity_id, tier=info.tier
                        )
                    ],
                }
                for p in peers
            ],
        }
    )


async def _events(request: Request) -> Response:
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    queue = engine.subscribe(
        info.entity_id if info else None,
        info.tier if info else "",
    )

    async def event_gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            engine.unsubscribe(queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _auth_body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "请求体必须是 JSON") from None
    return data if isinstance(data, dict) else {}


def _identity_error_response(exc: Exception) -> Response:
    """身份类端点的错误 → 400（``IdentityError`` 与存储层 ``WorldError`` 共用）。

    ``WorldError`` 也要接：注册时的邀请码消费在存储层的事务里（并发抢同一个码
    → rowcount≠1 → 回滚并抛 WorldError）。只接 ``IdentityError`` 的话，这条
    真实路径会以 **500** 的形式回给用户（"邀请码已被用掉"变成"服务器错误"）。
    """
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _register(request: Request) -> Response:
    identity: IdentityService = request.app.state.world_identity
    data = await _auth_body(request)
    try:
        info = await identity.register_human(
            str(data.get("username") or ""),
            str(data.get("password") or ""),
            invite_code=data.get("invite_code"),
            admin_key=data.get("admin_key"),
        )
    except (IdentityError, WorldError) as e:
        return _identity_error_response(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})


async def _login(request: Request) -> Response:
    identity: IdentityService = request.app.state.world_identity
    data = await _auth_body(request)
    try:
        info = await identity.login(
            str(data.get("username") or ""), str(data.get("password") or "")
        )
    except (IdentityError, WorldError) as e:
        return _identity_error_response(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})


async def _agent_register(request: Request) -> Response:
    identity: IdentityService = request.app.state.world_identity
    data = await _auth_body(request)
    try:
        info = await identity.register_agent(
            str(data.get("name") or ""), invite_code=data.get("invite_code")
        )
    except (IdentityError, WorldError) as e:
        return _identity_error_response(e)
    return JSONResponse({"ok": True, "token": info.to_dict()})


async def _logout(request: Request) -> Response:
    identity: IdentityService = request.app.state.world_identity
    info = _identity_of(request.scope)
    ok = await identity.logout(info.token) if info else False
    return JSONResponse({"ok": ok})


async def _delete_account(request: Request) -> Response:
    """本人永久注销（token 即凭据；不可恢复，调用方 UI 负责确认）。"""
    identity: IdentityService = request.app.state.world_identity
    info = _identity_of(request.scope)
    if info is None or not info.account_id:
        return _identity_error_response(IdentityError("无效的凭据"))
    try:
        await identity.delete_own_account(info.token)
    except (IdentityError, WorldError) as e:
        return _identity_error_response(e)
    return JSONResponse({"ok": True})


async def _change_password(request: Request) -> Response:
    identity: IdentityService = request.app.state.world_identity
    info = _identity_of(request.scope)
    _require_tier(info, ("play", "admin"))
    data = await _auth_body(request)
    try:
        await identity.change_password(
            info.token,
            str(data.get("old_password") or ""),
            str(data.get("new_password") or ""),
        )
    except (IdentityError, WorldError) as e:
        return _identity_error_response(e)
    return JSONResponse({"ok": True})


async def _views(request: Request) -> Response:
    """视图列表（D7：前端路由初始化共用；元数据无敏感信息，免认证）。

    登录页也要用（决定是否显示"无视图"提示），故不做档位限制。
    D15/v0.3.0：已登录时按**调用者所在世界**过滤——该世界未启用的玩法包，
    它的视图 tab 不出现（与工具面过滤同一套判断）。

    D46（R9 自举路径）：**没有行动实体时不过滤**。此时
    ``play_active_for_entity("")`` 会回落到**默认世界**，于是"玩家在别的世界"
    就等于"什么视图都看不到"——包括"创建角色"的那个入口，人被困死在门口。
    宁可多显示几个 tab（点了会因为世界未启用而不可用，那是可理解的），
    也不能让唯一的出路消失。围观（read）凭据同理。
    """
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    entity_id = info.entity_id if info is not None else ""
    views = [
        v
        for v in engine.list_views()
        if not entity_id
        or engine.play_active_for_entity(entity_id, v.get("play_id", ""))
    ]
    return JSONResponse({"views": views})


async def _chrome(request: Request) -> Response:
    """壳层挂载点（K-1）：页眉抽屉的列表 ``{blocks: [...]}``。

    **要认证**（play / admin）：这里会**执行玩法包代码**（`apply_ui_hooks` 调
    provider），返回内容可能是有权限的——不能像 `/views` 那样免认证（那只是纯元数据）。

    没有包注入时 ``blocks`` 是空数组：**抽屉照常打开**，底部「退出登录」仍在
    （那三样是壳层写死的，不给玩法包）。
    """
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    block = await engine.shell_menu(entity_id=info.entity_id if info else None)
    return JSONResponse({"blocks": [b.to_dict() for b in block.blocks]})


async def _where(request: Request) -> Response:
    """页眉基础信息（K-3）：**我在哪个世界的哪张地图**。

    壳层的常驻信息不该靠 `/state`——那是全量快照，为一个页眉把整个世界拉下来不划算。
    "没有化身"与"不在世界上"都是**合法状态**（D45 / D36），用 `reason` 明说，不是错误。
    """
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    engine = request.app.state.world_engine
    info = _identity_of(request.scope)
    return JSONResponse(engine.where(info.entity_id if info else None))


async def _meta(request: Request) -> Response:
    """前端模式识别 + **连接身份状态**（玩家端 = play；见 ``meta_payload``）。"""
    return JSONResponse(meta_payload("play", _identity_of(request.scope)))


async def _play_web(request: Request) -> Response:
    _require_tier(_identity_of(request.scope), ("play", "admin"))
    loader = request.app.state.world_loader
    play_id = request.path_params.get("play_id", "")
    subpath = request.path_params.get("path", "")
    info = loader.plays.get(play_id) if loader else None
    if info is None:
        raise HTTPException(404, f"玩法包不存在：{play_id}")
    web_dir = (info.path / "web").resolve()
    target = (web_dir / subpath).resolve()
    # 路径校验用 is_relative_to（与 PlayLoader 的路径安全检查同一套语义）：
    # str.startswith 会把 `<pkg>/web-evil/x.js` 误判为在 `<pkg>/web` 之内。
    if not target.is_relative_to(web_dir) or not target.is_file():
        raise HTTPException(404, "资源不存在")
    content = target.read_bytes()
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return Response(content=content, media_type=media_type)


# ---------- 组装 ----------


def build_http_app(
    mcp: FastMCP,
    identity: IdentityService,
    *,
    engine: Any = None,
    loader: Any = None,
    allowed_origins: list[str] | None = None,
    static_dir: Any = None,
) -> Any:
    """世界服务 ASGI app：MCP streamable HTTP + 业务端点 + 内置 WebUI + 认证 + CORS。

    Args:
        mcp: FastMCP 实例（工具已注册）。
        identity: 身份服务。
        engine: WorldEngine（快照/SSE 数据源）。
        loader: PlayLoader（玩法包 web 资源）。
        allowed_origins: CORS 允许的来源（WebUI 独立部署域；内置托管时同源可留空）。
        static_dir: WebUI 构建产物目录（webui/dist）；存在时挂载为根路径静态资源
            （免认证——登录页需在未认证时加载）。
    """
    mcp_starlette = mcp.streamable_http_app()
    routes: list = list(mcp_starlette.routes) + [
        Route("/state", _state),
        Route("/scene", _scene),
        Route("/events", _events),
        Route("/views", _views),
        Route("/chrome", _chrome),
        Route("/where", _where),
        Route("/auth/register", _register, methods=["POST"]),
        Route("/auth/login", _login, methods=["POST"]),
        Route("/auth/agent-register", _agent_register, methods=["POST"]),
        Route("/auth/logout", _logout, methods=["POST"]),
        Route("/auth/change-password", _change_password, methods=["POST"]),
        Route("/auth/delete-account", _delete_account, methods=["POST"]),
        Route("/meta", _meta),
        Route("/plays/{play_id}/web/{path:path}", _play_web, methods=["GET"]),
    ]
    # 合并 FastMCP app 的 lifespan（session manager / task group 初始化）——
    # 只复制 routes 会丢失 lifespan，导致 MCP 请求 500
    from contextlib import asynccontextmanager

    mcp_lifespan = mcp_starlette.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(app):
        async with mcp_lifespan(app):
            yield

    # 内置托管：WebUI 构建产物挂根路径（API 路由优先；SPA 由 hash 路由承担，
    # 服务器只需 index.html 与 /assets/*）
    public_exact: tuple[str, ...] = ()
    if static_dir is not None:
        dist = Path(static_dir)
        if dist.is_dir():
            from starlette.staticfiles import StaticFiles

            routes.append(
                Mount(
                    "/", app=StaticFiles(directory=str(dist), html=True), name="webui"
                )
            )
            public_exact = ("/",)
            public_paths = PUBLIC_PATHS + ("/assets", "/favicon.ico")
        else:
            public_paths = PUBLIC_PATHS
    else:
        public_paths = PUBLIC_PATHS

    app = Starlette(
        routes=routes,
        lifespan=combined_lifespan,
        # HTTPException → 4xx JSON；WorldError → **409 JSON**（业务错误，不是 500）。
        # 后者在本版本变成必需：D36 让"实体不在世界上"合法、D45 之后"新凭据没有
        # 化身"更是默认状态，而 `_build_scene` 这条路径会对它抛 WorldError——
        # 不接就是一个 500 空壳，客户端连"你还没有角色"都读不到。
        exception_handlers={HTTPException: _http_error, WorldError: _world_error},
    )
    app.state.world_engine = engine
    app.state.world_identity = identity
    app.state.world_loader = loader
    app = AuthMiddleware(
        app, identity, public_paths=public_paths, public_exact=public_exact
    )
    if allowed_origins:
        app = CORSMiddleware(
            app,
            allow_origins=allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )
    return app


class WorldHttpServer:
    """独立 uvicorn 服务（main.py 装配：enable_world_api 时启动）。"""

    def __init__(self, app: Any, *, host: str, port: int) -> None:
        self._app = app
        self.host = host
        self.port = port
        self._server: Any = None

    async def start(self) -> None:
        """启动服务（在 asyncio task 中运行，阻塞直到退出）。"""
        import uvicorn

        config = uvicorn.Config(
            self._app, host=self.host, port=self.port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    def stop(self) -> None:
        """请求服务退出（配合 await 启动 task）。"""
        if self._server is not None:
            self._server.should_exit = True
