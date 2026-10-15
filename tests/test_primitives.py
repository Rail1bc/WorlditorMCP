"""原语分派（D11/A3）+ 字段设施（D9/D10）测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError
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
    # D41：kind="player" 是输入便利——实体实际带的是 local:player 组件（数据 {}）。
    return await engine.place_entity(
        "player", "default", 0, 0, name="小明", components={"local:stat": {"gold": 5}}
    )


# ---------- 原语分派 ----------


def test_override_move_and_super_channel(tmp_path):
    """override move：handler(api, *args) 生效；call_default_primitive 走默认。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            calls = []

            async def override_move(api, entity_id, direction, *, path=None):
                calls.append(direction)
                return await api.call_default_primitive(
                    "move", entity_id, direction, path=path
                )

            api.override_primitive("move", override_move)
            player = await _player(engine)
            scene = await engine.move(player.id, "up")
            assert calls == ["up"]
            assert scene is not None
            assert engine.list_primitive_overrides() == [
                {"name": "move", "play_id": "pkg_a", "mode": "override"}
            ]
        finally:
            await engine.terminate()

    _run(fn())


def test_override_replace_and_disable(tmp_path):
    """override 完全替换（不发默认事件）；disable 调用报错。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            player = await _player(engine)

            # override 完全替换：返回假场景对象（handler 返回值直接透传）
            async def fake_move(api, entity_id, direction, *, path=None):
                return {"fake": direction}

            api.override_primitive("move", fake_move)
            result = await engine.move(player.id, "up")
            assert result == {"fake": "up"}
            # disable 与 override 互斥
            api2 = WorlditorPlayAPI(engine, "pkg_b")
            with pytest.raises(WorldError, match="已被 pkg_a 登记"):
                api2.disable_primitive("move")
            with pytest.raises(WorldError, match="已被 pkg_a 登记"):
                api2.override_primitive("move", fake_move)
            # 卸载 pkg_a → 恢复默认
            engine.clear_play_registrations("pkg_a")
            assert engine.list_primitive_overrides() == []
            scene = await engine.move(player.id, "up")
            assert scene is not None
            # disable 后调用报错
            api2.disable_primitive("move")
            with pytest.raises(WorldError, match="已被禁用"):
                await engine.move(player.id, "up")
            # 非覆盖范围报错
            with pytest.raises(WorldError, match="原语必须是"):
                api2.override_primitive("place_entity", fake_move)
            with pytest.raises(WorldError, match="原语必须是"):
                api2.disable_primitive("nope")
        finally:
            await engine.terminate()

    _run(fn())


def test_override_handler_serialized_under_lock(tmp_path):
    """并发一致性（P0-1）：override handler 在引擎锁内执行。

    分派入口不持锁时，两个并发 move 的 handler「读-让出-写」序列交错：
    双方都读到旧值，自增丢失一次（n=1）；锁内执行则串行（n=2）。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            player = await _player(engine)

            async def racing_move(api, entity_id, direction, *, path=None):
                n = await api.get_data(entity_id, "n", component="local:stat") or 0
                await asyncio.sleep(0.01)  # 让出点：另一协程在此插入读-写
                await api.set_data(entity_id, "n", n + 1, component="local:stat")
                return {"ok": direction}

            api.override_primitive("move", racing_move)
            await asyncio.gather(
                engine.move(player.id, "up"), engine.move(player.id, "up")
            )
            assert await engine.get_data(player.id, "n", component="local:stat") == 2
        finally:
            await engine.terminate()

    _run(fn())


def test_set_data_get_data_dispatch(tmp_path):
    """set_data/get_data：默认读写 + disable 报错。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            player = await _player(engine)
            await engine.set_data(player.id, "hp", 100, component=_STAT)
            await engine.set_data(player.id, "hp", 80, component=_STAT)
            assert await engine.get_data(player.id, "hp", component=_STAT) == 80
            # name=None → 返回整块组件数据
            assert (await engine.get_data(player.id, component=_STAT))["gold"] == 5
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.disable_primitive("set_data")
            with pytest.raises(WorldError, match="已被禁用"):
                await engine.set_data(player.id, "hp", 50, component=_STAT)
            # 覆盖 get_data
            api2 = WorlditorPlayAPI(engine, "pkg_b")
            engine.attach_play_api("pkg_b", api2)
            api2.override_primitive(
                "get_data", lambda api, eid, name=None, component=None: "masked"
            )
            assert await engine.get_data(player.id, "hp", component=_STAT) == "masked"
        finally:
            await engine.terminate()

    _run(fn())


def test_component_primitives_and_events(tmp_path):
    """组件原语（D32）：add 已存在报错 / set 整体替换 / remove 幂等；事件键为 components_*。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            player = await _player(engine)
            seen: list[dict] = []

            def observe(api, entity, changed):
                seen.append(changed)

            engine.register_world_event("on_entity_changed", observe, play_id="obs")
            # 新建组件 → components_added
            await engine.add_component(player.id, "local:bag", {"slots": 3})
            assert engine.get_component(player.id, "local:bag") == {"slots": 3}
            assert seen[-1] == {"components_added": ["local:bag"]}
            # 已存在再 add → 报错（要整体替换用 set_component），且不改动、不发事件
            with pytest.raises(WorldError, match="组件已存在"):
                await engine.add_component(player.id, "local:bag", {})
            assert engine.get_component(player.id, "local:bag") == {"slots": 3}
            assert len(seen) == 1
            # set 已存在组件 = 整体替换 → components_set（旧键一起丢，正是 set 的语义）
            await engine.set_component(player.id, "local:bag", {"slots": 5})
            assert engine.get_component(player.id, "local:bag") == {"slots": 5}
            assert seen[-1] == {"components_set": ["local:bag"]}
            # set 不存在的组件 = 建出来 → components_added
            await engine.set_component(player.id, "local:quest", {"step": 1})
            assert seen[-1] == {"components_added": ["local:quest"]}
            # 删组件 → components_removed；再删 → False（幂等，不报错也不发事件）
            assert await engine.remove_component(player.id, "local:bag") is True
            assert engine.get_component(player.id, "local:bag") is None
            assert seen[-1] == {"components_removed": ["local:bag"]}
            assert await engine.remove_component(player.id, "local:bag") is False
            assert seen[-1] == {"components_removed": ["local:bag"]}
            # 只读接口（不进分派表）：稳定排序的组件名列表
            # （v2：位置在 core:position、名字在 core:info，所以它们也在清单中；
            #  D41：kind="player" 落成 local:player 组件——能力也在清单里）
            assert engine.list_components(player.id) == [
                "core:info",
                "core:position",
                "local:player",
                "local:quest",
                _STAT,
            ]
        finally:
            await engine.terminate()

    _run(fn())


def test_override_interact(tmp_path):
    """override interact：整体替换交互通道。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            player = await _player(engine)

            async def fake_interact(api, eid, target_id, action, args=None):
                return {"blocked": action}

            api.override_primitive("interact", fake_interact)
            result = await engine.interact(player.id, player.id, "anything")
            assert result == {"blocked": "anything"}
        finally:
            await engine.terminate()

    _run(fn())


def test_override_handler_exception_isolated(tmp_path):
    """覆盖 handler 异常：隔离为 WorldError，不拖垮内核。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)

            async def boom(api, *args, **kwargs):
                raise RuntimeError("boom")

            api.override_primitive("move", boom)
            player = await _player(engine)
            with pytest.raises(WorldError, match="执行出错"):
                await engine.move(player.id, "up")
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 字段设施（D9 / D10） ----------


def test_kind_fields_and_merge(tmp_path):
    """字段设施（D41）：声明 ∪ 同一组件内追加；**按组件分组、不跨组件摊平**。

    原用例守的是"kind 声明 ∪ 追加 ∪ 分类字段"三层合并（分类也承载字段）。D41 把
    ``add_category_fields`` 删掉后，字段只有一个归属：**声明它的那个组件**——分类
    退回纯选取分组（D10），另一个组件拿不到别人的字段。这条用例改成守同一件事：
    字段设施仍然"声明 + 追加"可用，但**绝不跨组件摊平**。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.register_entity_kind(
                "monster",
                label="怪物",
                fields=[{"name": "hp", "label": "血量", "type": "int", "default": 10}],
                categories=("生物",),
            )
            api.add_kind_fields("monster", [{"name": "poison", "type": "bool"}])
            fields = engine.effective_fields("pkg_a:monster")
            assert {f["name"] for f in fields} == {"hp", "poison"}
            assert next(f for f in fields if f["name"] == "hp")["default"] == 10
            # **不摊平**：另一个组件（同分类）一个字段都拿不到
            api.register_entity_kind("slime", label="史莱姆", categories=("生物",))
            assert engine.effective_fields("pkg_a:slime") == []
            # 分类只用于 list_kinds 的精准选取（D10），不承载字段
            kinds = engine.list_kinds(category="生物")
            assert {k["key"] for k in kinds} == {"pkg_a:monster", "pkg_a:slime"}
            assert "pkg_a:monster" in [k["key"] for k in engine.list_kinds()]
            # 同一组件内同名字段重复声明 → 报错（D41：一个地址只能有一个声明）
            with pytest.raises(WorldError, match="重复声明"):
                api.add_kind_fields("monster", [{"name": "hp", "type": "int"}])
            # 非法字段类型报错
            with pytest.raises(WorldError, match="字段类型"):
                api.register_entity_kind("bad", fields=[{"name": "x", "type": "weird"}])
            # 未声明组件追加报错
            with pytest.raises(WorldError, match="未声明"):
                api.add_kind_fields("ghost", [{"name": "x", "type": "int"}])
        finally:
            await engine.terminate()

    _run(fn())


def test_component_declaration_fields_replaces_item_fields(tmp_path):
    """D37：原「物品字段（注册声明 + 追加）」改由**组件/标签字段设施**承担。

    物品类型现在就是一条组件声明，所以"给已有类型追加字段"= ``add_tag_fields``
    （同一套设施、同一套归属记账），不再是 ``add_item_fields``。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)

            api.register_entity_tag(
                "sword",
                label="剑",
                fields=[{"name": "atk", "label": "攻击", "type": "int"}],
            )
            api.register_entity_tag("megaphone", label="喇叭")
            api.add_tag_fields("megaphone", [{"name": "price", "type": "int"}])
            row = next(k for k in api.list_kinds() if k["key"] == "pkg_a:sword")
            assert row["fields"][0]["name"] == "atk"
            # add_tag_fields 落内存注册表，且记了归属（卸载可清）
            assert "price" in {
                f.field["name"] for f in engine._tag_fields["pkg_a:megaphone"]
            }  # noqa: SLF001
            assert {f.play_id for f in engine._tag_fields["pkg_a:megaphone"]} == {
                "pkg_a"
            }
        finally:
            await engine.terminate()

    _run(fn())
