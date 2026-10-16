"""MCP 工具清单变化通知（G56）。

问题：SDK 默认把 `ServerCapabilities.tools.listChanged` 报成 **false**，`add_tool`
也不发通知——运行期装/启用玩法包后，服务端 `tools/list` 已经变了，**已连接的客户端
却看不到新工具**（只能重连）。而"装包即生效、无需重启"正是这个项目的主要用法。

这里用**进程内连接**（`create_connected_server_and_client_session`）验证两件事：
1. `initialize` 结果里声明 `tools.listChanged: true`；
2. 运行期注册/移除工具时，客户端真的收到 `notifications/tools/list_changed`。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolListChangedNotification

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.mcp import build_mcp_server
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _make(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


def _register(engine: WorldEngine, name: str) -> None:
    """模拟"运行期装/启用玩法包"：注册一个工具（走 engine 的同步 MCP 通路）。"""
    api = WorlditorPlayAPI(engine, "worlditor_play_late")
    engine.attach_play_api("worlditor_play_late", api)
    api.register_tool(
        name, lambda api, ctx, **kw: {"text": "ok"}, description="运行期注册"
    )


def _is_tool_list_changed(message: object) -> bool:
    """客户端会话把通知包在 ``ServerNotification.root`` 里（两种形态都认）。"""
    inner = getattr(message, "root", message)
    return isinstance(inner, ToolListChangedNotification)


def test_server_advertises_tool_list_changed(tmp_path):
    """initialize 结果声明 tools.listChanged = true（否则客户端不理通知）。"""

    async def fn():
        engine = await _make(tmp_path)
        try:
            mcp = build_mcp_server(engine)
            engine.attach_mcp(mcp)
            async with create_connected_server_and_client_session(
                mcp._mcp_server  # noqa: SLF001
            ) as session:
                caps = session.get_server_capabilities()
                assert caps is not None and caps.tools is not None
                assert caps.tools.listChanged is True
        finally:
            await engine.terminate()

    _run(fn())


def test_tool_change_notification_reaches_client(tmp_path):
    """运行期注册/移除工具 → 客户端收到 tools/list_changed，且新清单立即可见。"""

    async def fn():
        engine = await _make(tmp_path)
        try:
            mcp = build_mcp_server(engine)
            engine.attach_mcp(mcp)
            seen: list[object] = []

            async def handler(message):
                seen.append(message)

            async with create_connected_server_and_client_session(
                mcp._mcp_server,
                message_handler=handler,  # noqa: SLF001
            ) as session:
                assert await session.list_tools() == await session.list_tools()
                _register(engine, "late_tool")
                # 广播是后台任务：让出几次让它跑完
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    if any(_is_tool_list_changed(m) for m in seen):
                        break
                assert any(_is_tool_list_changed(m) for m in seen), (
                    f"客户端没收到 tools/list_changed：{seen}"
                )
                names = [t.name for t in (await session.list_tools()).tools]
                assert "late_tool" in names
                # 移除（模拟停用/卸载玩法包）→ 再收一条
                seen.clear()
                engine.clear_play_registrations("worlditor_play_late")
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    if seen:
                        break
                assert any(_is_tool_list_changed(m) for m in seen), "工具移除后没有通知"
                names = [t.name for t in (await session.list_tools()).tools]
                assert "late_tool" not in names
        finally:
            await engine.terminate()

    _run(fn())


def test_no_sessions_is_noop(tmp_path):
    """没有活跃会话时广播是空操作（不得抛异常）。"""

    async def fn():
        engine = await _make(tmp_path)
        try:
            mcp = build_mcp_server(engine)
            engine.attach_mcp(mcp)
            _register(engine, "lonely_tool")
            await asyncio.sleep(0.02)
            assert [t["name"] for t in engine.list_tools()] == ["lonely_tool"]
        finally:
            await engine.terminate()

    _run(fn())
