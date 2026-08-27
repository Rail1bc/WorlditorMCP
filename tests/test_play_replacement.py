"""M4 验证（DESIGN §8）：替代玩法包可替换性 + 停用全部内置包空态。

场景：社区包 worlditor_play_warp override move（传送语义）——
1. movement 包过滤器在场时 override 被拒（G14 互斥保护）
2. 停用 movement 包后 override 成功，移动被替换
3. 停用 warp 包后移动恢复内核默认（D11 恢复语义）
4. 全部内置包停用 → 世界仍可编辑/浏览（空态）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
WARP_ID = "worlditor_play_warp"

BUILTIN_IDS = (
    "worlditor_play_movement",
    "worlditor_play_items",
    "worlditor_play_player",
    "worlditor_play_interaction",
    "worlditor_play_social",
)

_WARP_MAIN = '''"""测试替代玩法包：override move = 传送（无视连接，M4 可替换性验证）。"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI

WARP_TARGET = ("default", 0, 0)


def setup(api: WorlditorPlayAPI, context) -> None:
    """入口：覆盖 move 原语（D11：玩法包可整体替换内核能力）。"""
    api.override_primitive("move", _warp_move)


async def _warp_move(api: WorlditorPlayAPI, entity_id: str, direction: str, path=None) -> dict:
    """传送：无视连接与阻挡，直接飞到 (0,0)。"""
    await api.move_entity(entity_id, *WARP_TARGET)
    return {"text": "warped", "to": {"map_id": WARP_TARGET[0], "row": WARP_TARGET[1], "col": WARP_TARGET[1]}}


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载：override 随生命周期自动清除（内核恢复默认）。"""
'''


def _install_warp(plays_root: Path) -> Path:
    play_dir = plays_root / WARP_ID
    play_dir.mkdir(parents=True, exist_ok=True)
    (play_dir / "play.yaml").write_text(
        "name: worlditor_play_warp\n"
        "display_name: 传送玩法\n"
        "version: 0.1.0\n"
        "author: test\n"
        "requires:\n"
        '  worlditor: ">=0.1.0"\n'
        "  plays: []\n",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(_WARP_MAIN, encoding="utf-8")
    return play_dir


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _make(db_path: Path, plays_root: Path) -> tuple[WorldEngine, PlayLoader]:
    engine = WorldEngine(WorldStore(db_path))
    loader = PlayLoader(
        engine,
        plays_dir=plays_root,
        builtin_dir=BUILTIN_DIR,
        worlditor_version="0.1.0",
    )
    return engine, loader


def _scenario(db_path, plays_root, fn):
    engine, loader = _make(db_path, plays_root)

    async def main():
        await engine.initialize()
        try:
            return await fn(engine, loader)
        finally:
            await engine.terminate()

    return main()


# ---------- 替代玩法包（可替换性） ----------


def test_override_blocked_while_movement_filter(tmp_path):
    """movement 包的 move 过滤器在场 → warp 包 override 被拒（G14 互斥）。"""

    async def fn(engine, loader):
        await loader.load_all()
        _install_warp(tmp_path / "plays")
        # enable → setup 里 override 被拒 → 加载失败（原因保留在 load_errors）
        with pytest.raises(WorldError, match="玩法包加载失败"):
            await loader.enable(WARP_ID)
        assert "已挂过滤器" in loader._load_errors.get(WARP_ID, "")  # noqa: SLF001

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_disable_movement_frees_override(tmp_path):
    """停用 movement → 过滤器清除 → warp override 成功并生效。"""

    async def fn(engine, loader):
        await loader.load_all()
        _install_warp(tmp_path / "plays")
        await loader.disable("worlditor_play_movement")
        assert engine.list_primitive_filters() == []
        await loader.enable(WARP_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        # warp 生效：无视连接，传送回 (0,0)；返回 dict（override 返回值透传）
        result = await engine.move(player.id, "up")
        assert result == {
            "text": "warped",
            "to": {"map_id": "default", "row": 0, "col": 0},
        }
        assert player.pos_key() == ("default", 0, 0)

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_disable_replacement_restores_default(tmp_path):
    """再停用 warp → move 恢复内核默认（沿连接走）。"""

    async def fn(engine, loader):
        await loader.load_all()
        _install_warp(tmp_path / "plays")
        await loader.disable("worlditor_play_movement")
        await loader.enable(WARP_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await engine.move(player.id, "up")  # warp 生效
        await loader.disable(WARP_ID)
        # 恢复默认：重新启用 movement 后按连接走
        await loader.enable("worlditor_play_movement")
        await engine.move_entity(player.id, "default", 0, 0)
        scene = await engine.move(player.id, "up")
        assert (scene.row, scene.col) == (-1, 0)  # 连接目标（非 warp 目标）

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


# ---------- 空态（停用全部内置包） ----------


async def _disable_all(loader) -> None:
    """按依赖拓扑从叶子到根停用全部内置包。"""
    for play_id in (
        "worlditor_play_social",
        "worlditor_play_player",
        "worlditor_play_interaction",
        "worlditor_play_items",
        "worlditor_play_movement",
    ):
        await loader.disable(play_id)


def test_empty_state_world_usable(tmp_path):
    """全部内置包停用：世界仍可编辑/浏览（内核能力不依赖玩法包）。"""

    async def fn(engine, loader):
        await loader.load_all()
        await _disable_all(loader)
        assert not loader.plays  # 全部卸载出内存
        # 世界仍可编辑
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        # 移动 = 内核默认（无过滤器无 override）
        scene = await engine.move(player.id, "up")
        assert (scene.row, scene.col) == (-1, 0)
        # 字段原语可用
        await engine.set_data(player.id, "hp", 100)
        assert await engine.get_data(player.id, "hp") == 100
        # 只读浏览
        assert len(engine.list_locations()) == 41
        assert len(engine.list_entities()) >= 1
        # 管理端视角：状态列表显示全部 disabled
        status = {s["play_id"]: s["status"] for s in loader.list_plays()}
        assert all(status.get(p) == "disabled" for p in BUILTIN_IDS), status
        # 重新启用 → 恢复（含依赖拓扑）
        await loader.enable("worlditor_play_movement")
        assert "worlditor_play_movement" in loader.plays  # noqa: SLF001
        filters = engine.list_primitive_filters()
        assert any(f["play_id"] == "worlditor_play_movement" for f in filters)

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_empty_state_no_views(tmp_path):
    """空态：无视图注册（WebUI 兜底"无视图"提示，D7）。"""

    async def fn(engine, loader):
        await loader.load_all()
        await _disable_all(loader)
        assert engine.list_views() == []
        assert engine.list_tools() == []
        assert engine.list_services() == []

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))
