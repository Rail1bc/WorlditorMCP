"""remove_data / remove_state 测试（C：D23 的另一半——字段能被显式删掉）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import ShortCircuit
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


def _api(engine: WorldEngine, play_id: str) -> WorlditorPlayAPI:
    api = WorlditorPlayAPI(engine, play_id)
    engine.attach_play_api(play_id, api)
    return api


def test_remove_data_default(tmp_path):
    """默认实现：删字段 → True、attrs 少一个键、事件带 attrs_removed、落库。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            wolf = await engine.place_entity(
                "wolf", "default", 0, 0, attrs={"hp": 3, "mp": 1}
            )
            seen: list[tuple[str, dict]] = []

            def observe(api, entity, changed):
                seen.append((entity.id, changed))

            engine.register_world_event("on_entity_changed", observe, play_id="obs")
            assert await engine.remove_data(wolf.id, "hp") is True
            assert engine.get_attrs(wolf.id) == {"mp": 1}
            assert seen == [(wolf.id, {"attrs_removed": ["hp"]})]
            # 别处写的字段不受影响（对比"整体覆盖 attrs"那种会连坐的写法）
            assert engine.get_attrs(wolf.id)["mp"] == 1
        finally:
            await engine.terminate()

    _run(fn())


def test_remove_data_survives_restart(tmp_path):
    """删除是落盘的：重启后字段仍然没有。"""

    async def fn():
        engine = await _engine(tmp_path)
        wolf = await engine.place_entity("wolf", "default", 0, 0, attrs={"hp": 3})
        assert await engine.remove_data(wolf.id, "hp") is True
        await engine.terminate()

        engine2 = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine2.initialize()
        try:
            assert engine2.get_entity(wolf.id).attrs == {}
        finally:
            await engine2.terminate()

    _run(fn())


def test_remove_data_missing_is_noop(tmp_path):
    """字段本来就不存在 = 幂等：返回 False，不落盘、不发事件、不推进变更号。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            wolf = await engine.place_entity("wolf", "default", 0, 0)
            before = engine.revision
            assert await engine.remove_data(wolf.id, "absent") is False
            assert engine.revision == before
            with pytest.raises(WorldError, match="字段名"):
                await engine.remove_data(wolf.id, "")
            with pytest.raises(WorldError, match="实体不存在"):
                await engine.remove_data("nope", "hp")
        finally:
            await engine.terminate()

    _run(fn())


def test_remove_state(tmp_path):
    """state 容器对称操作（不经分派，与 set_state 一致）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            door = await engine.place_entity(
                "door", "default", 0, 0, state={"open": True, "lock": "iron"}
            )
            assert await engine.remove_state(door.id, "open") is True
            assert engine.get_state(door.id) == {"lock": "iron"}
            assert await engine.remove_state(door.id, "open") is False
        finally:
            await engine.terminate()

    _run(fn())


def test_remove_data_is_dispatchable(tmp_path):
    """走原语分派：过滤器可改参/否决，override 完全替换，disable 报"已被禁用"。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            wolf = await engine.place_entity(
                "wolf", "default", 0, 0, attrs={"hp": 3, "alias": 7}
            )

            # 过滤器改参：要删 "alias" 时改删 "hp"
            async def rename(api, **params):
                if params["name"] == "alias":
                    params["name"] = "hp"
                return params

            api.register_primitive_filter("remove_data", rename, label="字段别名")
            assert await engine.remove_data(wolf.id, "alias") is True
            assert engine.get_attrs(wolf.id) == {"alias": 7}

            # 过滤器否决：锁血（hp 不许删）
            async def veto(api, **params):
                if params["name"] == "hp":
                    raise WorldError("锁血：这个字段删不掉")
                return params

            api2 = _api(engine, "pkg_b")
            api2.register_primitive_filter("remove_data", veto, label="锁血")
            with pytest.raises(WorldError, match="锁血"):
                await engine.remove_data(wolf.id, "hp")
            assert engine.get_attrs(wolf.id) == {"alias": 7}

            # 短路：假装删掉了（跳过默认实现）——先撤掉上面两个过滤器（清注册）
            engine.clear_play_registrations("pkg_a")
            engine.clear_play_registrations("pkg_b")

            async def shadow(api, **params):
                return ShortCircuit(True)

            api3 = _api(engine, "pkg_c")
            api3.register_primitive_filter("remove_data", shadow, label="遮蔽")
            assert await engine.remove_data(wolf.id, "alias") is True
            assert engine.get_attrs(wolf.id) == {"alias": 7}  # 没真删
        finally:
            await engine.terminate()

    _run(fn())


def test_remove_data_override_and_disable(tmp_path):
    """override 整体替换；disable 后调用报错（D11 分派表语义对新原语同样成立）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _api(engine, "pkg_a")
            wolf = await engine.place_entity("wolf", "default", 0, 0, attrs={"hp": 3})

            async def keep(api, entity_id, name):
                return False  # 永不删除

            api.override_primitive("remove_data", keep)
            assert await engine.remove_data(wolf.id, "hp") is False
            assert engine.get_attrs(wolf.id) == {"hp": 3}
            # 覆盖状态管理页可见
            assert any(
                o["name"] == "remove_data" for o in engine.list_primitive_overrides()
            )

            # 与 override 互斥的过滤器登记被拒
            api2 = _api(engine, "pkg_b")
            with pytest.raises(WorldError, match="无法登记过滤器"):
                api2.register_primitive_filter("remove_data", lambda api, **p: p)

            # 禁用后调用报错（换个包来禁用：override/disable/过滤器三者互斥，D11/G14）
            engine.clear_play_registrations("pkg_a")
            api3 = _api(engine, "pkg_c")
            api3.disable_primitive("remove_data")
            with pytest.raises(WorldError, match="已被禁用"):
                await engine.remove_data(wolf.id, "hp")
        finally:
            await engine.terminate()

    _run(fn())
