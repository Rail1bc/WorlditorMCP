"""玩法包管理测试（§4.3 + G4/G5/G6/G7）：状态持久化 / 依赖 / 卸载安全。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from play_fixtures import install_demo_play

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


def _write_play(
    root: Path, name: str, main_code: str, requires_plays: list[str] | None = None
) -> Path:
    """构造一个社区玩法包目录。"""
    play_dir = root / name
    play_dir.mkdir(parents=True, exist_ok=True)
    deps = ", ".join(f'"{p}"' for p in (requires_plays or []))
    (play_dir / "play.yaml").write_text(
        f"name: {name}\n"
        f"display_name: {name}\n"
        f"version: 0.1.0\n"
        f"author: test\n"
        f"requires:\n"
        f'  worlditor: ">=0.3.0"\n'
        f"  plays: [{deps}]\n",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(main_code, encoding="utf-8")
    return play_dir


async def _make(tmp_path: Path) -> tuple[WorldEngine, PlayLoader]:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0")
    return engine, loader


def test_disable_persists_across_restart(tmp_path):
    """disable 持久化：重启后按标记跳过加载；enable 恢复。"""

    async def fn():
        install_demo_play(tmp_path / "plays")
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        assert "worlditor_play_demo" in loader.plays
        await loader.disable("worlditor_play_demo")
        assert "worlditor_play_demo" not in loader.plays
        # 重启（同库）：disabled 标记落库 → 不加载
        await loader.unload_all()
        await loader.load_all()
        assert "worlditor_play_demo" not in loader.plays
        status = {p["play_id"]: p for p in loader.list_plays()}
        assert status["worlditor_play_demo"]["status"] == "disabled"
        # enable：重新加载 + 标记清除
        await loader.enable("worlditor_play_demo")
        assert "worlditor_play_demo" in loader.plays
        await loader.unload_all()
        await loader.load_all()
        assert "worlditor_play_demo" in loader.plays
        await engine.terminate()

    _run(fn())


def test_disable_keeps_kv_data(tmp_path):
    """disable 仅卸载代码注册，play_data KV 保留（G5）；enable 后数据原样。"""

    async def fn():
        install_demo_play(tmp_path / "plays")
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        api = loader.plays["worlditor_play_demo"].api
        await api.kv_set("counter", 42)
        await loader.disable("worlditor_play_demo")
        await loader.enable("worlditor_play_demo")
        assert loader.plays["worlditor_play_demo"].api.kv_get("counter") == 42
        await engine.terminate()

    _run(fn())


def test_dependency_topology(tmp_path):
    """依赖：拓扑加载；enable 自动带依赖；disable 被依赖者拒绝。"""

    async def fn():
        _write_play(
            tmp_path / "plays",
            "worlditor_play_base",
            "def setup(api, context):\n    pass\n",
        )
        _write_play(
            tmp_path / "plays",
            "worlditor_play_upper",
            "def setup(api, context):\n    pass\n",
            requires_plays=["worlditor_play_base"],
        )
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        assert "worlditor_play_base" in loader.plays
        assert "worlditor_play_upper" in loader.plays
        # disable base → 拒绝（upper 依赖）
        with pytest.raises(WorldError, match="依赖"):
            await loader.disable("worlditor_play_base")
        # 先 disable upper 再 disable base
        await loader.disable("worlditor_play_upper")
        await loader.disable("worlditor_play_base")
        assert loader.plays == {}
        # enable upper → 自动带 base
        await loader.enable("worlditor_play_upper")
        assert "worlditor_play_base" in loader.plays
        assert "worlditor_play_upper" in loader.plays
        # 缺失依赖：load 失败不阻塞；enable 报错
        _write_play(
            tmp_path / "plays",
            "worlditor_play_orphan",
            "def setup(api, context):\n    pass\n",
            requires_plays=["worlditor_play_ghost"],
        )
        await loader.unload_all()
        await loader.load_all()
        status = {p["play_id"]: p for p in loader.list_plays()}
        assert status["worlditor_play_orphan"]["status"] == "load_failed"
        with pytest.raises(WorldError, match="不存在"):
            await loader.enable("worlditor_play_orphan")
        await engine.terminate()

    _run(fn())


def test_uninstall_security(tmp_path):
    """uninstall：社区包可删；内置包拒绝；非法 id 拒绝；目录外路径拒绝。"""

    async def fn():
        demo = install_demo_play(tmp_path / "plays")
        # 模拟内置包（builtin_dir）
        engine, loader = await _make(tmp_path)
        loader.builtin_dir = tmp_path / "builtin"
        (tmp_path / "builtin").mkdir(exist_ok=True)
        _write_play(
            tmp_path / "builtin",
            "worlditor_play_builtin_x",
            "def setup(api, context):\n    pass\n",
        )
        await loader.load_all()
        # 内置包不可卸载
        with pytest.raises(WorldError, match="内置"):
            await loader.uninstall("worlditor_play_builtin_x")
        # 非法 play_id
        with pytest.raises(WorldError, match="非法"):
            await loader.uninstall("../../evil")
        # 不存在
        with pytest.raises(WorldError, match="不存在"):
            await loader.uninstall("worlditor_play_nope")
        # 社区包可卸载（目录消失）
        assert (tmp_path / "plays" / "worlditor_play_demo").is_dir()
        await loader.uninstall("worlditor_play_demo")
        assert not (tmp_path / "plays" / "worlditor_play_demo").exists()
        assert "worlditor_play_demo" not in loader.plays
        assert demo.exists() is False
        # 卸载后 list 不再出现
        assert all(p["play_id"] != "worlditor_play_demo" for p in loader.list_plays())
        await engine.terminate()

    _run(fn())


def test_list_plays_states(tmp_path):
    """list_plays：loaded / disabled / load_failed + 错误详情。"""

    async def fn():
        install_demo_play(tmp_path / "plays")
        _write_play(
            tmp_path / "plays",
            "worlditor_play_broken_x",
            "raise RuntimeError('bad')\n",
        )
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        status = {p["play_id"]: p for p in loader.list_plays()}
        assert status["worlditor_play_demo"]["status"] == "loaded"
        assert status["worlditor_play_broken_x"]["status"] == "load_failed"
        assert status["worlditor_play_broken_x"]["error"]
        assert status["worlditor_play_demo"]["builtin"] is False
        await engine.terminate()

    _run(fn())
