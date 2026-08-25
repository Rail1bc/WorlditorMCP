"""worlditor_play_movement 内置包测试（M3 验收载体）。

端到端验证平台能力（GAPS G14/G3/G11/G12）：
- 过滤器链改参：相对方向（forward/back/left/right）按 facing 换算绝对方向
- MCP 工具：world_look 3×3 视野 / world_move / world_turn / world_who
- 视图协议：register_view 注册（url 指向 /plays/<id>/web/view.js）
- 互斥规则：过滤器已挂时 override move 报错（G14）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4store import V4WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
MOVEMENT_ID = "worlditor_play_movement"
DIRECTIONS = ("up", "right", "down", "left")


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _make(db_path: Path, plays_root: Path) -> tuple[V4WorldEngine, PlayLoader]:
    engine = V4WorldEngine(V4WorldStore(db_path))
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
    """内置包加载：过滤器 / 4 工具 / 视图注册就位。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert MOVEMENT_ID in ids
        # 过滤器：move 链上 1 个（相对方向换算）
        filters = engine.list_primitive_filters()
        move_filters = [f for f in filters if f["name"] == "move"]
        assert len(move_filters) == 1
        assert move_filters[0]["play_id"] == MOVEMENT_ID
        # 工具
        tools = {t["name"]: t for t in engine.list_tools()}
        assert set(tools) >= {
            "world_look",
            "world_move",
            "world_turn",
            "world_who",
        }
        # 视图（url 为服务内绝对路径）
        views = {v["key"]: v for v in engine.list_views()}
        assert "movement" in views
        assert views["movement"]["provider"]["url"] == (
            f"/plays/{MOVEMENT_ID}/web/view.js"
        )
        # 视图静态文件存在（分发完整）
        view_file = BUILTIN_DIR / MOVEMENT_ID / "web" / "view.js"
        assert view_file.is_file()

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


# ---------- 相对方向换算（过滤器改参） ----------


def test_relative_direction_mapping(tmp_path):
    """facing=up 时 forward/back/left/right → up/down/left/right。"""

    async def fn(engine, loader):
        await loader.load_all()
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "up"}
        )
        # 直接调 move 原语（走过滤器链）：相对方向应换算为绝对方向
        scene = await engine.move(player.id, "forward")
        assert scene.map_id == "default"
        # up 方向连接目标（种子世界 0,0 的 up 连接）——断言走到了非原地块
        assert (scene.row, scene.col) != (0, 0)
        assert engine.get_attrs(player.id).get("facing") == "up"  # 移动不改朝向

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_relative_direction_absolute_passthrough(tmp_path):
    """绝对方向原样放行（过滤器不干预）。"""

    async def fn(engine, loader):
        await loader.load_all()
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "left"}
        )
        scene = await engine.move(player.id, "up")  # 绝对方向
        assert (scene.row, scene.col) != (0, 0)

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_relative_direction_unknown_passthrough(tmp_path):
    """非法方向（既非相对也非绝对）→ 内核方向校验报错。"""

    async def fn(engine, loader):
        await loader.load_all()
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "up"}
        )
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
    """world_move(forward) → 移动 + 返回新场景。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "up"}
        )

        # 直接调工具 handler（与 MCP 注册的 handler 相同）
        async def go():
            return await movement.module._world_move(  # noqa: SLF001
                movement.api, None, direction="forward"
            )

        result = await _call_as(player.id, go)
        assert "scene" in result and "facing" in result
        moved = engine.get_entity(player.id)
        assert (moved.row, moved.col) != (0, 0)
        # 相对方向换算生效：scene.location.name 非空
        assert result["scene"]["location"]["name"]

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_world_look_tool(tmp_path):
    """world_look：3×3 网格（9 格，中心 = 我）+ facing + 可走方向。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "right"}
        )

        async def look():
            return await movement.module._world_look(movement.api, None)  # noqa: SLF001

        result = await _call_as(player.id, look)
        assert result["facing"] == "right"
        assert len(result["grid"]) == 9
        center = next(g for g in result["grid"] if g["dr"] == 0 and g["dc"] == 0)
        assert any(e["is_me"] for e in center["entities"])
        assert center["loc"] is not None  # 玩家所在地块存在
        assert isinstance(result["paths"], list)
        # 广场 0,0 应至少有一个可走方向
        assert len(result["paths"]) >= 1

    _run(_scenario(tmp_path / "world.db", tmp_path / "plays", fn))


def test_world_turn_tool(tmp_path):
    """world_turn：left/right 相对转身 + 绝对方向。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        movement = next(p for p in plays if p.play_id == MOVEMENT_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"facing": "up"}
        )

        async def turn(direction):
            return await movement.module._world_turn(  # noqa: SLF001
                movement.api, None, direction=direction
            )

        assert (await _call_as(player.id, lambda: turn("right")))["facing"] == "right"
        assert (await _call_as(player.id, lambda: turn("left")))["facing"] == "up"
        assert (await _call_as(player.id, lambda: turn("down")))["facing"] == "down"
        with pytest.raises(WorldError, match="direction"):
            await _call_as(player.id, lambda: turn("north"))

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
