"""玩法包管理测试（§4.3 + G4/G5/G6/G7）：状态持久化 / 依赖 / 卸载安全。"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from play_fixtures import install_demo_play

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


def _make_zip(top: str, *, name: str | None = None, setup: str | None = None) -> bytes:
    """构造一个 zip 玩法包（顶层目录 top；play.yaml 的 name 默认同 top）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            f"{top}/play.yaml",
            f"name: {name or top}\n"
            f"display_name: 测试包\n"
            f"version: 0.1.0\n"
            f"requires:\n"
            f'  worlditor: ">=0.3.0"\n'
            f"  plays: []\n",
        )
        z.writestr(
            f"{top}/main.py",
            setup or "def setup(api, context):\n    pass\n",
        )
    return buf.getvalue()


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


# ---------- 安装一致性（v0.7.3：目录名与 play.yaml name 必须一致） ----------


def test_install_zip_rejects_dir_name_mismatch(tmp_path):
    """顶层目录名 ≠ play.yaml 的 name：拒绝安装且不留目录。

    修复前：包能装上（返回的 play_id 还是错的），实际以 yaml 的 name 加载；
    `uninstall` 按目录名定位 → **两个名字都卸不掉**，目录永久残留。
    """

    async def fn():
        engine, loader = await _make(tmp_path)
        with pytest.raises(WorldError, match="不一致"):
            await loader.install_zip(
                _make_zip("worlditor_play_dirmismatch", name="worlditor_play_real"),
                filename="x.zip",
            )
        assert not (tmp_path / "plays" / "worlditor_play_dirmismatch").exists()
        assert loader.plays == {}
        await engine.terminate()

    _run(fn())


def test_install_zip_rejects_missing_prefix(tmp_path):
    """顶层目录缺 worlditor_play_ 前缀：拒绝。

    修复前：能装上、`list_plays` 里看不到（discover 只认前缀）、重启后静默消失，
    目录成为 API 删不掉的孤儿。
    """

    async def fn():
        engine, loader = await _make(tmp_path)
        with pytest.raises(WorldError, match="worlditor_play_"):
            await loader.install_zip(_make_zip("notprefixed"), filename="x.zip")
        assert not (tmp_path / "plays" / "notprefixed").exists()
        await engine.terminate()

    _run(fn())


def test_install_zip_rejects_taken_play_id(tmp_path):
    """play_id 已被内置包占用：拒绝安装（否则顶掉内置、重启后两个都不在）。"""

    async def fn():
        (tmp_path / "builtin").mkdir()
        _write_play(
            tmp_path / "builtin",
            "worlditor_play_taken",
            "def setup(api, context):\n    pass\n",
        )
        engine, loader = await _make(tmp_path)
        loader.builtin_dir = tmp_path / "builtin"
        await loader.load_all()
        with pytest.raises(WorldError, match="占用"):
            await loader.install_zip(_make_zip("worlditor_play_taken"))
        assert not (tmp_path / "plays" / "worlditor_play_taken").exists()
        await engine.terminate()

    _run(fn())


def test_duplicate_play_id_builtin_wins(tmp_path):
    """同名目录（内置 + 社区残留）：内置胜出，社区目录只在 note 里报"被忽略"。

    修复前 `load_all` 把两个都拒掉 → 内置内容包在重启后整体消失。
    """

    async def fn():
        (tmp_path / "builtin").mkdir()
        _write_play(
            tmp_path / "builtin",
            "worlditor_play_dup",
            "def setup(api, context):\n    pass\n",
        )
        _write_play(
            tmp_path / "plays",
            "worlditor_play_dup",
            "def setup(api, context):\n    pass\n",
        )
        engine, loader = await _make(tmp_path)
        loader.builtin_dir = tmp_path / "builtin"
        await loader.load_all()
        assert "worlditor_play_dup" in loader.plays
        assert loader.plays["worlditor_play_dup"].builtin is True
        rows = [p for p in loader.list_plays() if p["play_id"] == "worlditor_play_dup"]
        assert len(rows) == 1, "同名目录只应出一行"
        assert rows[0]["status"] == "loaded"
        assert "同名目录被忽略" in rows[0]["note"]
        await engine.terminate()

    _run(fn())


def test_uninstall_removes_community_shadow_of_builtin(tmp_path):
    """同名残留可被卸载：删社区那份、内置那份保持加载。"""

    async def fn():
        (tmp_path / "builtin").mkdir()
        _write_play(
            tmp_path / "builtin",
            "worlditor_play_dup",
            "def setup(api, context):\n    pass\n",
        )
        _write_play(
            tmp_path / "plays",
            "worlditor_play_dup",
            "def setup(api, context):\n    pass\n",
        )
        engine, loader = await _make(tmp_path)
        loader.builtin_dir = tmp_path / "builtin"
        await loader.load_all()
        await loader.uninstall("worlditor_play_dup")
        assert not (tmp_path / "plays" / "worlditor_play_dup").exists()
        assert (tmp_path / "builtin" / "worlditor_play_dup").is_dir()
        assert "worlditor_play_dup" in loader.plays  # 内置仍在
        await engine.terminate()

    _run(fn())


def test_failed_load_rolls_back_component_declarations(tmp_path):
    """首次加载失败：组件声明一并回滚（旧行为只在卸载时清）。

    否则 `list_kinds()` 会一直列出一个从未加载成功的包声明的组件。
    """

    async def fn():
        _write_play(
            tmp_path / "plays",
            "worlditor_play_bad_decl",
            "def setup(api, context):\n"
            "    api.declare_component('side', label='副作用')\n"
            "    raise RuntimeError('声明完就炸')\n",
        )
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        status = {p["play_id"]: p for p in loader.list_plays()}
        assert status["worlditor_play_bad_decl"]["status"] == "load_failed"
        assert not any(
            k.startswith("worlditor_play_bad_decl") for k in engine.list_kinds()
        )
        await engine.terminate()

    _run(fn())


def test_uninstall_rmtree_failure_keeps_state(tmp_path, monkeypatch):
    """删目录失败：包保持加载、禁用标记不落库（旧行为是"报错了但已卸载"）。"""

    async def fn():
        install_demo_play(tmp_path / "plays")
        engine, loader = await _make(tmp_path)
        await loader.load_all()
        assert "worlditor_play_demo" in loader.plays

        def boom(*args, **kwargs):
            raise OSError("设备忙")

        monkeypatch.setattr("worlditor_mcp.world.play.shutil.rmtree", boom)
        with pytest.raises(WorldError, match="删除玩法包目录失败"):
            await loader.uninstall("worlditor_play_demo")
        assert "worlditor_play_demo" in loader.plays  # 没被 teardown 掉
        assert "worlditor_play_demo" not in loader._disabled  # noqa: SLF001
        monkeypatch.undo()
        assert (tmp_path / "plays" / "worlditor_play_demo").is_dir()
        await engine.terminate()

    _run(fn())
