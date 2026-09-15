"""worlditor_play_movement 内置包测试（M3 验收载体）。

端到端验证平台能力（GAPS G14/G3/G11/G12）：
- 过滤器链改参：方向别名（上/北/north…）归一为内核绝对方向 up/right/down/left
- MCP 工具：world_look 3×3 视野 / world_move / world_who
- 视图协议：register_view 注册（url 指向 /plays/<id>/web/view.js）
- 互斥规则：过滤器已挂时 override move 报错（G14）

v0.1.18：本包**无朝向概念**（facing/world_turn/相对方向已移除）——移动直接
用内核连接槽的绝对方向；防回归见 test_package_has_no_facing_concept。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
MOVEMENT_ID = "worlditor_play_movement"
DIRECTIONS = ("up", "right", "down", "left")


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


# ---------- 加载与注册 ----------


def test_movement_play_loaded(tmp_path):
    """内置包加载：过滤器 / 3 工具 / 视图注册就位。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert MOVEMENT_ID in ids
        # 过滤器：move 链上 1 个（方向别名归一）
        filters = engine.list_primitive_filters()
        move_filters = [f for f in filters if f["name"] == "move"]
        assert len(move_filters) == 1
        assert move_filters[0]["play_id"] == MOVEMENT_ID
        # 工具（无 world_turn：本包无朝向概念）
        tools = {t["name"]: t for t in engine.list_tools()}
        assert set(tools) >= {"world_look", "world_move", "world_who"}
        assert "world_turn" not in tools
        # 视图（url 为服务内绝对路径）
        views = {v["key"]: v for v in engine.list_views()}
        assert "movement" in views
        assert views["movement"]["provider"]["url"] == (
            f"/plays/{MOVEMENT_ID}/web/view.js"
        )
        # 视图静态文件存在（分发完整）
        assert (BUILTIN_DIR / MOVEMENT_ID / "web" / "view.js").is_file()

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_filter_conflicts_with_override(tmp_path):
    """G14 互斥：move 已挂过滤器（movement 包）→ 其他包 override move 报错。"""

    async def fn(engine, loader):
        await loader.load_all()
        with pytest.raises(WorldError, match="互斥|过滤器"):
            engine.override_primitive(
                "move", lambda api, *a, **k: None, play_id="other"
            )

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_package_has_no_facing_concept(tmp_path):
    """设计决策固化（v0.1.18）：内置包不得再引入朝向/转身/相对方向概念。"""

    async def fn(engine, loader):
        for name in ("main.py", "web/view.js"):
            text = (BUILTIN_DIR / MOVEMENT_ID / name).read_text(encoding="utf-8")
            for banned in ("facing", "world_turn", "relTo", "forward"):
                assert banned not in text, f"{name} 残留朝向概念：{banned}"

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


# ---------- 方向别名归一（过滤器改参 G14） ----------


def test_direction_alias_normalized(tmp_path):
    """别名归一：中文（上/北）与英文（north）都换算为内核绝对方向 up。"""

    async def fn(engine, loader):
        await loader.load_all()
        for index, alias in enumerate(("上", "north", "up", "UP")):
            player = await engine.place_entity(
                "player", "default", 0, 0, name=f"小明{index}"
            )
            # 直接调 move 原语（走过滤器链）；种子世界 0,0 的 up 连接可走
            scene = await engine.move(player.id, alias)
            assert (scene.row, scene.col) != (0, 0), f"别名 {alias} 未生效"

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_direction_alias_other_axes(tmp_path):
    """其余方位别名同样归一（右/东/east → right）。"""

    async def fn(engine, loader):
        await loader.load_all()
        for index, alias in enumerate(("右", "east", "right")):
            player = await engine.place_entity(
                "player", "default", 0, 0, name=f"小红{index}"
            )
            scene = await engine.move(player.id, alias)
            assert (scene.row, scene.col) != (0, 0), f"别名 {alias} 未生效"

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_unknown_direction_rejected(tmp_path):
    """非法方向（非别名、非绝对方向）→ 内核方向校验报错。"""

    async def fn(engine, loader):
        await loader.load_all()
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        with pytest.raises(WorldError, match="方向必须是"):
            await engine.move(player.id, "diagonal")

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


async def _call_as(player_id: str, coro_factory):
    """以 player 身份调用（注入 _caller_entity，模拟 MCP ctx 身份）。"""
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


# ---------- MCP 工具端到端 ----------


def test_world_move_tool(tmp_path):
    """world_move("上") → 移动 + 返回新场景（无 facing 字段）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def go():
            return await movement.module._world_move(  # noqa: SLF001
                movement.api, None, direction="上"
            )

        result = await _call_as(player.id, go)
        assert "scene" in result and "facing" not in result
        moved = engine.get_entity(player.id)
        assert (moved.row, moved.col) != (0, 0)
        assert result["scene"]["location"]["name"]
        assert "上" in result["text"]

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_world_move_requires_direction(tmp_path):
    """world_move 缺 direction → 明确报错（不默认 forward）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def go():
            return await movement.module._world_move(movement.api, None)  # noqa: SLF001

        with pytest.raises(WorldError, match="direction"):
            await _call_as(player.id, go)

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_world_look_tool(tmp_path):
    """world_look：3×3 网格（9 格，中心 = 我）+ 位置 + 可走方向（无 facing）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def look():
            return await movement.module._world_look(movement.api, None)  # noqa: SLF001

        result = await _call_as(player.id, look)
        assert "facing" not in result
        assert result["location"]["name"]
        assert len(result["grid"]) == 9
        center = next(g for g in result["grid"] if g["dr"] == 0 and g["dc"] == 0)
        assert any(e["is_me"] for e in center["entities"])
        assert center["loc"] is not None  # 玩家所在地块存在
        assert isinstance(result["paths"], list)
        # 广场 0,0 应至少有一个可走方向，且 text 用中文方位描述
        assert len(result["paths"]) >= 1
        assert set(result["paths"]) <= set(DIRECTIONS)
        assert "可走方向" in result["text"]

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_world_who_tool(tmp_path):
    """world_who：同地块实体列表（viewer 过滤）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity("player", "default", 0, 0, name="小明")

        async def who():
            return await movement.module._world_who(movement.api, None)  # noqa: SLF001

        # 0,0 广场有种子商贩·阿福
        result = await _call_as(player.id, who)
        assert len(result["peers"]) >= 1
        assert any(p["name"] == "商贩·阿福" for p in result["peers"])

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_tools_work_via_mcp_build(tmp_path):
    """动态工具 schema 生成：world_move 参数声明 string/integer 合法（G11 回归）。"""

    async def fn(engine, loader):
        await loader.load_all()
        from worlditor_mcp.world.mcp import build_dynamic_tool

        # world_move 的 schema 由 build_dynamic_tool 生成（FastMCP 兼容性验证）
        binding = engine._tools["world_move"]  # noqa: SLF001
        tool = build_dynamic_tool(engine, binding, "world_move")
        assert tool is not None
        params = tool.__signature__.parameters
        assert "direction" in params
        assert "path" in params

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))
