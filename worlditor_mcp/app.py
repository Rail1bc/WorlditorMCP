"""服务装配：引擎 + 身份 + 玩法包 + MCP + HTTP app（``worlditor serve`` 核心）。

从插件时代的 main.py 提炼：独立进程生命周期（启动/停止），零框架依赖。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import __version__
from .config import Settings
from .world.identity import IdentityService
from .world.mcp import build_mcp_server
from .world.mcp.http import build_http_app
from .world.play import PlayLoader
from .world.v4engine import V4WorldEngine
from .world.v4store import V4WorldStore

logger = logging.getLogger("worlditor")


def _builtin_plays_dir() -> Path:
    """内置玩法包目录（随服务分发，G4：包内只读、可停用不可删除）。"""
    return Path(__file__).resolve().parent / "builtin_plays"


def _default_static_dir() -> Path:
    """WebUI 构建产物默认位置（仓库布局：worlditor_mcp/ 同级 webui/dist）。"""
    return Path(__file__).resolve().parent.parent / "webui" / "dist"


class WorlditorService:
    """worlditor 服务实例：装配全部组件并管理生命周期。

    Attributes:
        settings: 服务配置。
        engine: v4 世界引擎（事实层 + 原语 + 事件总线）。
        identity: 身份服务（账户 / token 三档 / 邀请码）。
        play_loader: 玩法包加载器（内置包 + 数据目录 plays/）。
        mcp_server: FastMCP 实例（工具已注册）。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = V4WorldEngine(V4WorldStore(settings.db_path))
        self.identity = IdentityService(
            self.engine,
            auth_mode=settings.auth_mode,
            admin_key=settings.admin_key,
            allow_agent_register=settings.allow_agent_register,
        )
        self.play_loader = PlayLoader(
            self.engine,
            plays_dir=settings.plays_dir,
            demo_dir=_builtin_plays_dir(),
            worlditor_version=__version__,
        )
        self.mcp_server: Any | None = None  # start() 内玩法包加载后构建（动态工具）

    async def start(self) -> None:
        """启动：建数据目录、初始化引擎（空库播种）、加载玩法包、构建 MCP server。"""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        await self.engine.initialize()
        loaded = await self.play_loader.load_all()
        # MCP server 在玩法包加载后构建：动态工具（register_tool）随注册表同步
        self.mcp_server = build_mcp_server(self.engine)
        self.engine.attach_mcp(self.mcp_server)
        logger.info(
            "worlditor %s 已就绪：实体 %d 个，玩法包 %d 个，工具 %d 个",
            __version__,
            len(self.engine.list_entities()),
            len(loaded),
            len(self.engine.list_tools()),
        )

    async def stop(self) -> None:
        """停止：卸载玩法包、关闭引擎（幂等，可多次调用）。"""
        await self.play_loader.unload_all()
        await self.engine.terminate()

    def build_app(self) -> Any:
        """构建世界服务 ASGI app（MCP + REST + SSE + 认证 + WebUI 静态）。"""
        return build_http_app(
            self.mcp_server,
            self.identity,
            engine=self.engine,
            loader=self.play_loader,
            allowed_origins=self.settings.allowed_origins or None,
            static_dir=self.settings.static_dir or _default_static_dir(),
        )

    def build_admin_app(self) -> Any:
        """构建管理端口 ASGI app（D16：/admin/* 要求 tier=admin）。"""
        from .admin import build_admin_app as _build_admin

        return _build_admin(
            self.identity,
            engine=self.engine,
            loader=self.play_loader,
            static_dir=self.settings.static_dir or _default_static_dir(),
        )
