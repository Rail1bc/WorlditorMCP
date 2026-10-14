"""原语过滤器链测试（G14）：三态语义 / 多过滤器叠加 / 互斥 / 清理。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import ShortCircuit
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore

# v2（D32）：字段归属组件（空信封不行），测试统一用 local:stat。
_STAT = "local:stat"


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    # v0.2.0：内核不再内置地图/地块，测试自铺最小世界（中央广场 (0,0) 可四向走）
    await seed_test_world(engine)
    return engine


async def _player(engine: WorldEngine):
    # v2（D32）：没有扁平 attrs 了，玩法数据归 local: 组件。
    return await engine.place_entity(
        "player", "default", 0, 0, name="小明", components={_STAT: {"gold": 5}}
    )


def _api(engine: WorldEngine, play_id: str) -> WorlditorPlayAPI:
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
            await engine.set_data(player.id, "hp", 100, component=_STAT)
            assert await engine.get_data(player.id, "hp", component=_STAT) == "??"
            assert await engine.get_data(player.id, "gold", component=_STAT) == 5
        finally:
            await engine.terminate()

    _run(fn())


def test_filter_on_component_primitives_and_core_bypass(tmp_path):
    """组件原语同样进分派表（可过滤/否决/短路）；``core:`` 组件的写入绕过分派表（D33）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            seen: list[tuple[str, str]] = []

            def recorder(primitive: str):
                async def record(api, **params):
                    seen.append((primitive, params["component"]))
                    if params["component"] == "local:banned":
                        raise WorldError("这个组件不许写")
                    return params

                return record

            api.register_primitive_filter(
                "set_component", recorder("set_component"), label="组件白名单"
            )
            api.register_primitive_filter(
                "set_data", recorder("set_data"), label="字段白名单"
            )
            player = await _player(engine)

            await engine.set_component(player.id, "local:free", {"a": 1})
            assert engine.get_component(player.id, "local:free") == {"a": 1}
            await engine.set_data(player.id, "hp", 7, component="local:vitals")
            assert await engine.get_data(player.id, "hp", component="local:vitals") == 7
            assert seen == [
                ("set_component", "local:free"),
                ("set_data", "local:vitals"),
            ]

            # 过滤器否决：整块新建被拦下（默认实现没跑）
            with pytest.raises(WorldError, match="不许写"):
                await engine.set_component(player.id, "local:banned", {"a": 1})
            assert engine.get_component(player.id, "local:banned") is None
            assert seen[-1] == ("set_component", "local:banned")

            # core: 组件的写入**跳过**分派表：过滤器既看不到、也拦不住（D33）
            await engine.set_component(player.id, "core:perception", {"sight": 3})
            await engine.set_data(player.id, "sight", 9, component="core:perception")
            assert engine.get_component(player.id, "core:perception") == {"sight": 9}
            assert len(seen) == 3  # core: 的两次写入都没进过滤器链

            # add_component 同样是分派原语：短路 → 默认实现不跑（返回值即 ShortCircuit 的值）
            async def shadow_add(api, **params):
                if params["component"] == "local:ghost":
                    return ShortCircuit({"fake": "短路"})
                return params

            api.register_primitive_filter("add_component", shadow_add, label="影子")
            assert await engine.add_component(player.id, "local:ghost", {"x": 1}) == {
                "fake": "短路"
            }
            assert engine.get_component(player.id, "local:ghost") is None

            # remove_component 也在分派表里：可被否决；清注册后恢复默认
            async def veto_remove(api, **params):
                if params["component"] == "local:free":
                    raise WorldError("这个组件删不得")
                return params

            api.register_primitive_filter(
                "remove_component", veto_remove, label="删除白名单"
            )
            with pytest.raises(WorldError, match="删不得"):
                await engine.remove_component(player.id, "local:free")
            assert engine.get_component(player.id, "local:free") == {"a": 1}
            engine.clear_play_registrations("pkg_a")
            assert await engine.remove_component(player.id, "local:free") is True
            assert engine.get_component(player.id, "local:free") is None

            # remove_component 对 core: 同样绕过（D33）——连"删不得"这条否决也够不着它
            api.register_primitive_filter(
                "remove_component", veto_remove, label="删除白名单"
            )
            await engine.add_component(player.id, "core:sight", {"n": 1})
            assert await engine.remove_component(player.id, "core:sight") is True
            assert engine.get_component(player.id, "core:sight") is None
        finally:
            await engine.terminate()

    _run(fn())
