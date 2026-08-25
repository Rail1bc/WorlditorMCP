"""原语过滤器链测试（G14）：三态语义 / 多过滤器叠加 / 互斥 / 清理。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import V4WorldEngine, WorldError
from worlditor_mcp.world.v4model import ShortCircuit
from worlditor_mcp.world.v4store import V4WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> V4WorldEngine:
    engine = V4WorldEngine(V4WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


async def _player(engine: V4WorldEngine):
    return await engine.place_entity(
        "player", "default", 0, 0, name="小明", attrs={"gold": 5}
    )


def _api(engine: V4WorldEngine, play_id: str) -> WorlditorPlayAPI:
    api = WorlditorPlayAPI(engine, play_id)
    engine.attach_play_api(play_id, api)
    return api


def test_filter_reject_rewrite_shortcircuit(tmp_path):
    """三态：否决（raise）/ 参数改写（返回 dict）/ 短路（ShortCircuit）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")

            async def reject(api, **params):
                if params["direction"] == "up":
                    raise WorldError("被束缚了，无法向上")
                return params

            async def rewrite(api, **params):
                if params["direction"] == "north":
                    params["direction"] = "up"
                return params

            async def short(api, **params):
                if params["direction"] == "teleport":
                    return ShortCircuit({"fake": "传送了"})
                return params

            api.register_primitive_filter("move", reject, label="束缚")
            api.register_primitive_filter("move", rewrite, label="方向转换")
            api.register_primitive_filter("move", short, label="传送")
            player = await _player(engine)
            # 否决
            with pytest.raises(WorldError, match="束缚"):
                await engine.move(player.id, "up")
            # 改写（north → up 后仍被 reject 拦？——顺序：reject 先执行，north 不拦）
            scene = await engine.move(player.id, "north")
            assert scene is not None  # north 被改写成 up？——不对，reject 在 rewrite 前
            # 短路
            result = await engine.move(player.id, "teleport")
            assert result == {"fake": "传送了"}
            # 过滤器状态可见（顺序）
            filters = engine.list_primitive_filters()
            assert [f["label"] for f in filters if f["name"] == "move"] == [
                "束缚",
                "方向转换",
                "传送",
            ]
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_order_and_rewrite_chain(tmp_path):
    """链序：先注册先执行；改写传递给后续过滤器。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            seen = []

            async def f1(api, **params):
                seen.append(("f1", params["direction"]))
                params["direction"] = "right"
                return params

            async def f2(api, **params):
                seen.append(("f2", params["direction"]))
                return params

            api.register_primitive_filter("move", f1, label="一")
            api.register_primitive_filter("move", f2, label="二")
            player = await _player(engine)
            await engine.move(player.id, "left")
            # f1 先看到 left，改写为 right；f2 看到改写后的 right
            assert seen == [("f1", "left"), ("f2", "right")]
            assert player.pos_key() == ("default", 0, 1)  # right 方向实际生效
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_positional_params_normalized(tmp_path):
    """参数规范化：位置参数调用同样进入过滤器（命名参数）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            seen = []

            async def f(api, **params):
                seen.append(params)
                return params

            api.register_primitive_filter("move", f, label="记录")
            player = await _player(engine)
            await engine.move(player.id, "up", path=0)
            assert seen[-1]["entity_id"] == player.id
            assert seen[-1]["direction"] == "up"
            assert seen[-1]["path"] == 0
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_mutual_exclusion_and_conflict(tmp_path):
    """互斥：过滤器与 override/disable 互斥；同包重复注册报错。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            api2 = _api(engine, "pkg_b")

            async def f(api, **params):
                return params

            async def o(api, *args, **kwargs):
                return None

            api.register_primitive_filter("move", f, label="一")
            # 同包多过滤器允许（各带 label）
            api.register_primitive_filter("move", f, label="二")
            assert len(engine.list_primitive_filters()) == 2
            # override/disable 与过滤器互斥
            with pytest.raises(WorldError, match="已挂过滤器"):
                api2.override_primitive("move", o)
            with pytest.raises(WorldError, match="已挂过滤器"):
                api2.disable_primitive("move")
            # 反向：先 override 后过滤器
            api2.override_primitive("set_data", o)
            with pytest.raises(WorldError, match="已被"):
                api.register_primitive_filter("set_data", f)
            # 非法原语名
            with pytest.raises(WorldError, match="原语必须是"):
                api.register_primitive_filter("place_entity", f)
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_cleared_on_unload(tmp_path):
    """生命周期：clear_play_registrations 清除过滤器，恢复默认。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")

            async def reject(api, **params):
                raise WorldError("拒绝一切")

            api.register_primitive_filter("move", reject, label="封锁")
            player = await _player(engine)
            with pytest.raises(WorldError, match="拒绝一切"):
                await engine.move(player.id, "up")
            engine.clear_play_registrations("pkg_a")
            assert engine.list_primitive_filters() == []
            scene = await engine.move(player.id, "up")
            assert scene is not None
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_on_get_data_masking(tmp_path):
    """get_data 遮蔽：过滤器短路返回遮蔽值（多包同挂一原语的真实用例）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            api2 = _api(engine, "pkg_b")

            async def mask(api, **params):
                if params.get("name") == "hp":
                    return ShortCircuit("??")
                return params

            async def lower(api, **params):
                return params

            api.register_primitive_filter("get_data", mask, label="遮蔽")
            api2.register_primitive_filter("get_data", lower, label="记录")
            player = await _player(engine)
            await engine.set_data(player.id, "hp", 100)
            assert await engine.get_data(player.id, "hp") == "??"
            assert await engine.get_data(player.id, "gold") == 5
        finally:
            await engine.terminate()

    _run(fn())
