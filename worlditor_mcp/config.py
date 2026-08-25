"""服务配置：环境变量加载（零配置文件，Docker 友好）。

所有配置项均有默认值，仅 ``WORLDITOR_ADMIN_KEY`` 在需要封闭部署时设置。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ENV_PREFIX = "WORLDITOR_"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(_ENV_PREFIX + name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Settings:
    """服务配置（环境变量 → 默认值）。

    Attributes:
        data_dir: 数据目录（world.db / plays/ 所在处）。
        host: 监听地址。
        port: 监听端口。
        admin_host: 管理端口监听地址（默认仅本机，D16）。
        admin_port: 管理端口（0 = 关闭管理端口）。
        auth_mode: 身份模式（open / invite / closed）。
        admin_key: 管理员注册密钥（空 = 开放注册为 admin）。
        allow_agent_register: 是否允许 agent 自助注册。
        allowed_origins: CORS 允许来源（逗号分隔；空 = 不限制来源）。
        static_dir: WebUI 构建产物目录（默认自动探测仓库 webui/dist）。
    """

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "6288")))
    admin_host: str = field(default_factory=lambda: _env("ADMIN_HOST", "127.0.0.1"))
    admin_port: int = field(default_factory=lambda: int(_env("ADMIN_PORT", "6289")))
    auth_mode: str = field(default_factory=lambda: _env("AUTH_MODE", "open"))
    admin_key: str = field(default_factory=lambda: _env("ADMIN_KEY", ""))
    allow_agent_register: bool = field(
        default_factory=lambda: _env_bool("ALLOW_AGENT_REGISTER", True)
    )
    allowed_origins: list[str] = field(default_factory=list)
    static_dir: Path | None = field(
        default_factory=lambda: Path(_env("STATIC_DIR")) if _env("STATIC_DIR") else None
    )

    def __post_init__(self) -> None:
        raw = _env("ALLOWED_ORIGINS")
        if raw:
            self.allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "world.db"

    @property
    def plays_dir(self) -> Path:
        return self.data_dir / "plays"
