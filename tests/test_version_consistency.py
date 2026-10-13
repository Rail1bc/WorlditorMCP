"""版本串一致性守卫（v0.5.2）。

发版要 bump 的地方散在多处（Python 包 2 + 前端 2 + 视图组件上报的
clientInfo），漏一处不会报错，只会让界面/日志里的版本号说谎。这个测试把它们
全部对齐到 ``worlditor_mcp.__version__``，发版时哪个没改，CI 直接点名。

v0.7.0：内置玩法包不再随仓库携带视图组件，视图组件的唯一来源是
``tests/fixtures/plays/`` 下的参考实现（夹具包安装时复制进 tmp 玩法包目录）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import tomllib

from worlditor_mcp import __version__

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _changelog_latest() -> str:
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## v([0-9][^\s（(]*)", text, re.MULTILINE)
    assert match, "CHANGELOG.md 找不到 '## vX.Y.Z' 标题"
    return match.group(1)


def _package_json_version() -> str:
    data = json.loads((_ROOT / "webui" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _package_lock_versions() -> list[str]:
    data = json.loads(
        (_ROOT / "webui" / "package-lock.json").read_text(encoding="utf-8")
    )
    return [str(data["version"]), str(data["packages"][""]["version"])]


def _view_client_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    root = _ROOT / "tests" / "fixtures" / "plays"
    for path in sorted(root.glob("*/web/*.js")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r'clientInfo:\s*\{[^}]*version:\s*"([^"]+)"', text)
        if match:
            out[path.name] = match.group(1)
    return out


def test_python_version_strings_agree():
    """pyproject / __init__ / CHANGELOG 顶条 三处必须同一个版本号。"""
    assert _pyproject_version() == __version__
    assert _changelog_latest() == __version__


def test_frontend_version_matches_package():
    """webui/package.json 与 lock 的根版本 = Python 包版本（前端不单独发版）。"""
    assert _package_json_version() == __version__
    assert _package_lock_versions() == [__version__, __version__]


def test_view_component_client_versions_match():
    """视图组件参考实现上报的 MCP clientInfo.version 也是本版本（日志里不说谎）。"""
    versions = _view_client_versions()
    # 至少 view.js 一份（参考实现；玩法包自带组件不在仓库内，无法集中守卫）
    assert len(versions) >= 1, f"没扫到视图组件参考实现：{versions}"
    bad = {name: v for name, v in versions.items() if v != __version__}
    assert not bad, f"clientInfo.version 与 {__version__} 不一致：{bad}"
