"""D27 事件阶段与顺序测试：phase（input→simulate→present）/ order / 注册序兜底。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


def _recorder(seen: list, name: str):
    """返回一个记录执行顺序的 handler（同步即可：_invoke 兼容同步函数）。"""

    def handler(api, *args):
        seen.append(name)

    return handler


def test_phase_beats_registration_order(tmp_path):
    """阶段优先：present 先注册也排在 input 之后（跨包顺序显式化）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            seen: list[str] = []
            engine.register_world_event(
                "on_custom", _recorder(seen, "present"), phase="present", play_id="p1"
            )
            engine.register_world_event(
                "on_custom", _recorder(seen, "input"), phase="input", play_id="p1"
            )
            engine.register_world_event(
                "on_custom", _recorder(seen, "simulate"), play_id="p1"
            )
            await engine.emit("on_custom", {"x": 1})
            assert seen == ["input", "simulate", "present"]
        finally:
            await engine.terminate()

    _run(fn())


def test_order_within_phase(tmp_path):
    """同阶段内按 order 升序（可负）；同 phase/order 按注册序稳定兜底。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            seen: list[str] = []
            engine.register_world_event(
                "on_custom", _recorder(seen, "late"), order=10, play_id="p1"
            )
            engine.register_world_event(
                "on_custom", _recorder(seen, "first"), order=-5, play_id="p1"
            )
            engine.register_world_event(
                "on_custom", _recorder(seen, "mid_a"), play_id="p1"
            )
            engine.register_world_event(
                "on_custom", _recorder(seen, "mid_b"), play_id="p1"
            )
            await engine.emit("on_custom", {"x": 1})
            assert seen == ["first", "mid_a", "mid_b", "late"]
        finally:
            await engine.terminate()

    _run(fn())


def test_builtin_event_keeps_registration_order(tmp_path):
    """老行为不变：不给 phase/order 时仍是注册序（内置事件同样适用）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            seen: list[str] = []
            for name in ("a", "b", "c"):
                engine.register_world_event(
                    "on_world_edited", _recorder(seen, name), play_id="p1"
                )
            await engine.emit("on_world_edited", {"op": "x"})
            assert seen == ["a", "b", "c"]
        finally:
            await engine.terminate()

    _run(fn())


def test_on_tick_respects_phase(tmp_path):
    """心跳也按阶段排序（每个订阅者仍有自己的 interval）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            seen: list[str] = []
            engine.register_world_event(
                "on_tick",
                _recorder(seen, "present"),
                interval=0.01,
                phase="present",
                play_id="p1",
            )
            engine.register_world_event(
                "on_tick",
                _recorder(seen, "input"),
                interval=0.01,
                phase="input",
                play_id="p1",
            )
            await engine._tick_once()
            assert seen == ["input", "present"]
        finally:
            await engine.terminate()

    _run(fn())


def test_register_validation(tmp_path):
    """阶段名/order/interval 校验：不静默造新阶段。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            handler = _recorder([], "x")
            with pytest.raises(WorldError, match="阶段"):
                engine.register_world_event("on_custom", handler, phase="setup")
            with pytest.raises(WorldError, match="阶段"):
                engine.register_world_event("on_custom", handler, phase=1)
            with pytest.raises(WorldError, match="order"):
                engine.register_world_event("on_custom", handler, order=1.5)
            with pytest.raises(WorldError, match="interval"):
                engine.register_world_event("on_tick", handler)
            with pytest.raises(WorldError, match="事件名"):
                engine.register_world_event("", handler)
            # 空串/None = 默认阶段（simulate），不报错
            engine.register_world_event("on_custom", handler, phase="")
        finally:
            await engine.terminate()

    _run(fn())


def test_play_api_passthrough(tmp_path):
    """玩法包 API 出口：register_world_event 带 phase/order。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            seen: list[str] = []
            api = WorlditorPlayAPI(engine, "pkg_a")
            api.register_world_event(
                "on_custom", _recorder(seen, "later"), phase="present"
            )
            api.register_world_event(
                "on_custom", _recorder(seen, "earlier"), phase="input"
            )
            await engine.emit("on_custom", {"x": 1})
            assert seen == ["earlier", "later"]
        finally:
            await engine.terminate()

    _run(fn())
