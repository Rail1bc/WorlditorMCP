"""进程内 MCP server（B7 / B10 / B11；动态工具 G2/D2）。

工具 = 引擎动作原语的薄封装（协议无关层零改动）；返回**结构化 JSON**
``{text, ui}``（D12：无 effects；ui 可选）——agent 消费 ``text``，WebUI
渲染 ``ui``，一次实现两端复用。

连接身份验证（token → 实体）：
- HTTP（streamable HTTP）：认证中间件校验 ``Authorization: Bearer <token>``，
  把 ``{entity_id, tier}`` 注入每个 JSON-RPC 请求的 ``params._meta``，
  工具经 ``ctx.request_context.meta`` 读取（read 档无实体 → 工具不可用）。

工具集：全部由玩法包 register_tool 动态注册（M2 起内核无内置工具）——
handler(api, ctx, **args)，身份经 api.caller() 读取（HTTP 经请求 _meta 注入）。
"""

from __future__ import annotations

import contextvars
import inspect
import json
import re
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..engine import WorldError

# MCP 工具返回：结构化 JSON 字符串（ensure_ascii=False，LLM/UI 双端消费）
_META_ENTITY_KEY = "worlditor_entity_id"
_META_TIER_KEY = "worlditor_tier"

# 当前调用者实体 id（MCP 动态工具 wrapper 注入；api.caller() 读取）
_caller_entity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "worlditor_caller_entity", default=None
)

# 玩法包工具参数类型 → Python 注解（FastMCP schema 生成；G11 含 array）
_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[str],
}


class McpAuthError(Exception):
    """MCP 连接/身份错误。"""


def _result(payload: dict) -> str:
    """结构化返回：``{text, ...}`` 序列化为 JSON 字符串。"""
    return json.dumps(payload, ensure_ascii=False)


def _entity_id(ctx: Context) -> str:
    """从连接身份解析实体 id（HTTP 读 _meta；无请求上下文时不可用）。"""
    meta = None
    try:
        meta = ctx.request_context.meta if ctx.request_context else None
    except ValueError:  # Context 不在请求内（进程内 call_tool 等场景）
        meta = None
    entity_id = getattr(meta, _META_ENTITY_KEY, None)
    if not entity_id:
        raise McpAuthError("连接未认证或凭据只能围观，无法执行动作")
    return entity_id


def build_dynamic_tool(engine: Any, binding: Any, name: str) -> Callable:
    """从玩法包工具登记构建 FastMCP 动态工具（G2）。

    handler 签名：``async (api, ctx, **args) -> str | dict``（返回文本或
    ``{text, ui}`` 结构化 JSON）；调用前注入调用者身份（api.caller() 可读）。

    Args:
        engine: WorldEngine（取玩法包 API 与 handler 调用）。
        binding: engine._tools[name]（_ToolBinding：play_id/handler/params）。
        name: 工具名。

    Returns:
        可传给 FastMCP.add_tool 的动态函数。
    """

    async def _dynamic(ctx: Context, **kwargs: Any) -> str:
        api = engine._play_apis.get(binding.play_id)
        if api is None:
            return _result({"text": f"玩法包未加载：{binding.play_id}"})
        try:
            entity_id = _entity_id(ctx)
        except McpAuthError as e:
            return _result({"text": str(e)})
        token = _caller_entity.set(entity_id)
        try:
            # 引擎锁内执行（DESIGN §2.4：handler 锁内执行；任务级可重入）
            result = await engine.invoke_locked(binding.handler, api, ctx, **kwargs)
        except WorldError as e:
            return _result({"text": str(e)})
        except Exception:  # noqa: BLE001
            return _result({"text": "工具执行出错，请稍后再试"})
        finally:
            _caller_entity.reset(token)
        if isinstance(result, str):
            return _result({"text": result})
        if isinstance(result, dict):
            return _result(result)
        return _result({"text": str(result)})

    params = [
        inspect.Parameter(
            "ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context
        )
    ]
    for pname, ptype in binding.params.items():
        # 参数默认 None → schema 可选（M3：工具声明参数即可选，必填校验由
        # 玩法包 handler 自管——缺参时 handler 报错更可控，KISS）
        params.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=_TYPE_MAP.get(ptype, str),
                default=None,
            )
        )
    _dynamic.__name__ = name
    _dynamic.__signature__ = inspect.Signature(params)
    # 参数描述（FastMCP 从 docstring 解析 :param x: ...）
    doc_lines = [binding.description or f"玩法包工具：{name}", ""]
    for pname in binding.params:
        doc_lines.append(f":param {pname}: 参数 {pname}")
    _dynamic.__doc__ = "\n".join(doc_lines)
    return _dynamic


# ---------- 传输安全（Host / Origin 校验；421 回归防线） ----------

# 白名单条目形态：域名 / IPv4（可带端口）与 [IPv6]（可带端口）
_IPV6_HOST_RE = re.compile(r"^\[[^\]]+\](?::(?P<port>\d+|\*))?$")
_PLAIN_HOST_RE = re.compile(r"^[^:]+(?::(?P<port>\d+|\*))?$")


def _port_variants(item: str) -> list[str]:
    """Host 白名单条目补端口变体（浏览器 Host 头带端口：``example.com:6288``）。"""
    if item.endswith(":*"):
        return [item]
    for pattern in (_IPV6_HOST_RE, _PLAIN_HOST_RE):
        match = pattern.match(item)
        if match:
            return [item] if match.group("port") else [item, f"{item}:*"]
    return [item]


def build_transport_security(
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> TransportSecuritySettings:
    """构造 MCP 传输安全设置（DNS rebinding 保护）。

    **默认关闭 Host 校验**：worlditor 是自托管世界服务（默认监听 ``0.0.0.0``，
    经局域网 IP / 域名 / 反向代理访问），而 MCP SDK 在 ``host=127.0.0.1`` 时
    会自动开启保护且只放行 localhost 变体 —— 从局域网 IP 打开玩家端会
    ``421 Invalid Host header``（玩家端视图 MCP 初始化失败）。鉴权仍是主要
    防线（``/world/mcp`` 不在公共路径，必须 Bearer token）；Host 校验属纵深
    防御，需要时用 ``WORLDITOR_MCP_ALLOWED_HOSTS`` 显式收紧。

    Args:
        allowed_hosts: Host 白名单（空 = 放行任意 Host）。条目可写
            ``example.com`` / ``192.168.1.5:6288`` / ``[::1]``，无端口时自动
            补 ``:*`` 变体（浏览器 Host 头通常带端口）。
        allowed_origins: Origin 白名单（空 = 按 hosts 派生 http/https 同源项，
            避免浏览器带 Origin 头时 403）。

    Returns:
        TransportSecuritySettings 实例（显式传入即可覆盖 SDK 的 localhost 自动保护）。
    """
    hosts: list[str] = []
    for raw in allowed_hosts or []:
        item = raw.strip()
        if item:
            hosts.extend(_port_variants(item))
    hosts = list(dict.fromkeys(hosts))
    origins = [o.strip() for o in (allowed_origins or []) if o.strip()]
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if not origins:
        # 派生同源 Origin（浏览器同源请求也带 Origin 头，不放行则 403）
        origins = list(
            dict.fromkeys(
                f"{scheme}://{host[:-2] if host.endswith(':*') else host}{suffix}"
                for host in hosts
                for scheme in ("http", "https")
                for suffix in ("", ":*")
            )
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_mcp_server(
    engine: Any,
    *,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastMCP:
    """构建 worlditor MCP server（M2：无内置工具，工具全部由玩法包注册）。

    工具 = 玩法包 register_tool 动态注册（build_dynamic_tool）；M3 领域包
    将注册 world_look/world_move 等行为工具。身份经请求 _meta 注入。

    Args:
        engine: WorldEngine 实例。
        allowed_hosts: MCP Host 白名单（空 = 放行任意 Host，见
            build_transport_security）。
        allowed_origins: MCP Origin 白名单（空 = 按 hosts 派生）。

    Returns:
        空工具集 FastMCP 实例（engine.attach_mcp 后动态工具同步注册）。
    """
    mcp = FastMCP(
        "worlditor",
        instructions=(
            "你是一个生活在 worlditor 世界中的实体。可用工具由当前世界的玩法包"
            "提供（如 world_look 查看位置、world_move 移动、world_interact 交互）。"
            "所有工具返回 JSON：text 字段是给 LLM 的文本，ui 字段是界面结构（忽略即可）。"
        ),
        streamable_http_path="/world/mcp",
        # 显式传入：SDK 在 host=127.0.0.1（默认）时会自动只放行 localhost → 421
        transport_security=build_transport_security(allowed_hosts, allowed_origins),
    )
    return mcp
