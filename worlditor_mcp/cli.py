"""命令行入口：``worlditor serve``。

一行命令部署：``pipx install worlditor-mcp && worlditor serve``。
配置走环境变量（WORLDITOR_*，见 config.py），CLI 参数可覆盖。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import Settings


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="worlditor",
        description="一行命令部署的世界服务：MCP 世界 + 自带 WebUI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动世界 HTTP 服务（MCP + WebUI + REST）")
    serve.add_argument("--host", help="监听地址（默认 WORLDITOR_HOST 或 0.0.0.0）")
    serve.add_argument(
        "--port", type=int, help="监听端口（默认 WORLDITOR_PORT 或 6288）"
    )
    serve.add_argument(
        "--admin-port",
        type=int,
        help="管理端口（默认 WORLDITOR_ADMIN_PORT 或 6289；0 = 关闭）",
    )
    serve.add_argument(
        "--admin-host",
        help="管理端口监听地址（默认 WORLDITOR_ADMIN_HOST 或 127.0.0.1）",
    )
    serve.add_argument(
        "--data-dir", help="数据目录（默认 WORLDITOR_DATA_DIR 或 ./data）"
    )
    serve.add_argument("--admin-key", help="管理员注册密钥（默认 WORLDITOR_ADMIN_KEY）")
    serve.add_argument(
        "--auth-mode",
        choices=["open", "invite", "closed"],
        help="身份模式（默认 WORLDITOR_AUTH_MODE 或 open）",
    )
    serve.add_argument(
        "--allowed-origins",
        help="CORS 允许来源（逗号分隔，默认 WORLDITOR_ALLOWED_ORIGINS）",
    )
    serve.add_argument("--static-dir", help="WebUI 构建产物目录（默认自动探测）")
    serve.add_argument("--verbose", action="store_true", help="详细日志")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI 入口（pyproject [project.scripts] worlditor）。"""
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    if args.command == "serve":
        _setup_logging(args.verbose)
        settings = _settings_from_args(args)
        asyncio.run(_serve(settings))


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = Settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.admin_port is not None:
        settings.admin_port = args.admin_port
    if args.admin_host:
        settings.admin_host = args.admin_host
    if args.data_dir:
        settings.data_dir = Path(args.data_dir)
    if args.admin_key:
        settings.admin_key = args.admin_key
    if args.auth_mode:
        settings.auth_mode = args.auth_mode
    if args.allowed_origins:
        settings.allowed_origins = [
            o.strip() for o in args.allowed_origins.split(",") if o.strip()
        ]
    if args.static_dir:
        settings.static_dir = Path(args.static_dir)
    return settings


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _serve(settings: Settings) -> None:
    from .app import WorlditorService
    from .world.mcp.http import WorldHttpServer

    service = WorlditorService(settings)
    await service.start()
    servers = [
        WorldHttpServer(service.build_app(), host=settings.host, port=settings.port)
    ]
    if settings.admin_port:
        servers.append(
            WorldHttpServer(
                service.build_admin_app(),
                host=settings.admin_host,
                port=settings.admin_port,
            )
        )
    tasks = [asyncio.create_task(s.start()) for s in servers]
    try:
        await asyncio.gather(*tasks)
    finally:
        for s in servers:
            s.stop()
        await service.stop()


if __name__ == "__main__":
    main()
