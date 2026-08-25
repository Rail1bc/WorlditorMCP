"""进程内 MCP server（v4.1，B7 / B10 / B11；v5 动态工具 G2/D2）。

工具 = 引擎动作原语的薄封装（协议无关层零改动）；返回**结构化 JSON**
``{text, ui, effects}``——agent 消费 ``text``，WebUI 渲染 ``ui``，一次实现
两端复用。

连接身份验证（token → 实体）：
- HTTP（streamable HTTP）：认证中间件校验 ``Authorization: Bearer <token>``，
  把 ``{entity_id, tier}`` 注入每个 JSON-RPC 请求的 ``params._meta``，
  工具经 ``ctx.request_context.meta`` 读取（read 档无实体 → 工具不可用）。
- stdio（本地）：启动时经 ``--token`` / 环境变量绑定固定实体。

工具集：内置 world_look / world_move / world_say / world_bag / world_use /
world_interact / world_who（M2 删除，改由玩法包注册）+ 玩法包动态工具
（register_tool：handler(api, ctx, **args)，身份经 api.caller() 读取）。
"""

from __future__ import annotations

import contextvars
import inspect
import json
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..v4engine import WorldError

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


def _entity_id(ctx: Context, fixed_identity: Any = None) -> str:
    """从连接身份解析实体 id（HTTP 读 _meta；stdio 用固定身份）。"""
    if fixed_identity is not None:
        return fixed_identity.entity_id
    meta = None
    try:
        meta = ctx.request_context.meta if ctx.request_context else None
    except ValueError:  # Context 不在请求内（进程内 call_tool 等场景）
        meta = None
    entity_id = getattr(meta, _META_ENTITY_KEY, None)
    if not entity_id:
        raise McpAuthError("连接未认证或凭据只能围观，无法执行动作")
    return entity_id


def build_dynamic_tool(
    engine: Any, binding: Any, name: str, fixed_identity: Any = None
) -> Callable:
    """从玩法包工具登记构建 FastMCP 动态工具（G2）。

    handler 签名：``async (api, ctx, **args) -> str | dict``（返回文本或
    ``{text, ui}`` 结构化 JSON）；调用前注入调用者身份（api.caller() 可读）。

    Args:
        engine: V4WorldEngine（取玩法包 API 与 handler 调用）。
        binding: engine._tools[name]（_ToolBinding：play_id/handler/params）。
        name: 工具名。
        fixed_identity: stdio 模式固定身份（HTTP 模式 None，身份经 _meta）。

    Returns:
        可传给 FastMCP.add_tool 的动态函数。
    """

    async def _dynamic(ctx: Context, **kwargs: Any) -> str:
        api = engine._play_apis.get(binding.play_id)
        if api is None:
            return _result({"text": f"玩法包未加载：{binding.play_id}"})
        try:
            entity_id = _entity_id(ctx, fixed_identity)
        except McpAuthError as e:
            return _result({"text": str(e)})
        token = _caller_entity.set(entity_id)
        try:
            result = await engine._invoke(binding.handler, api, ctx, **kwargs)
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
        params.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=_TYPE_MAP.get(ptype, str),
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


def build_mcp_server(engine: Any, fixed_identity: Any = None) -> FastMCP:
    """构建 worlditor MCP server（M2：无内置工具，工具全部由玩法包注册）。

    工具 = 玩法包 register_tool 动态注册（build_dynamic_tool）；M3 领域包
    将注册 world_look/world_move 等行为工具。fixed_identity 供 stdio 模式
    绑定固定身份（HTTP 模式身份经请求 _meta 注入）。

    Args:
        engine: V4WorldEngine 实例。
        fixed_identity: stdio 模式绑定的固定身份（TokenInfo）；HTTP 模式传 None。

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
    )
    return mcp
