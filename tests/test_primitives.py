"""原语分派（D11/A3）+ 字段设施（D9/D10）测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


async def _player(engine: WorldEngine):
    return await engine.place_entity(
        "player", "default", 0, 0, name="小明", attrs={"gold": 5}
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


def test_set_data_get_data_dispatch(tmp_path):
    """set_data/get_data：默认读写 + disable 报错。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            player = await _player(engine)
            await engine.set_data(player.id, "hp", 100)
            await engine.set_data(player.id, "hp", 80)
            assert await engine.get_data(player.id, "hp") == 80
            assert (await engine.get_data(player.id))["gold"] == 5
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            api.disable_primitive("set_data")
            with pytest.raises(WorldError, match="已被禁用"):
                await engine.set_data(player.id, "hp", 50)
            # 覆盖 get_data
            api2 = WorlditorPlayAPI(engine, "pkg_b")
            engine.attach_play_api("pkg_b", api2)
            api2.override_primitive("get_data", lambda api, eid, name=None: "masked")
            assert await engine.get_data(player.id, "hp") == "masked"
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

            async def fake_interact(
                api, eid, target_id, action, args=None, item_id=None
            ):
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
    """字段三层次：kind 声明 ∪ 追加 ∪ 分类（运行时合并）。"""

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
            api.add_category_fields("生物", [{"name": "aggro", "type": "bool"}])
            fields = engine.effective_fields("monster")
            assert {f["name"] for f in fields} == {"hp", "poison", "aggro"}
            assert next(f for f in fields if f["name"] == "hp")["default"] == 10
            # 分类字段对同分类其他 kind 生效
            api.register_entity_kind("slime", label="史莱姆", categories=("生物",))
            assert {f["name"] for f in engine.effective_fields("slime")} == {"aggro"}
            # list_kinds 过滤
            kinds = engine.list_kinds(category="生物")
            assert {k["kind"] for k in kinds} == {"monster", "slime"}
            assert "monster" in [k["kind"] for k in engine.list_kinds()]
            # 非法字段类型报错
            with pytest.raises(WorldError, match="字段类型"):
                api.register_entity_kind("bad", fields=[{"name": "x", "type": "weird"}])
            # 未注册 kind 追加报错
            with pytest.raises(WorldError, match="未注册"):
                api.add_kind_fields("ghost", [{"name": "x", "type": "int"}])
        finally:
            await engine.terminate()

    _run(fn())


def test_item_fields(tmp_path):
    """物品字段：注册时声明 + add_item_fields 追加。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg_a")
            engine.attach_play_api("pkg_a", api)
            from worlditor_mcp.world import ItemDef

            api.register_item_def(
                ItemDef(id="sword", name="剑"),
                fields=[{"name": "atk", "label": "攻击", "type": "int"}],
            )
            api.add_item_fields("megaphone", [{"name": "price", "type": "int"}])
            assert engine.store.items["sword"].fields[0]["name"] == "atk"
            # add_item_fields 落内存注册表（flush 后持久化）
            await engine.flush_item_defs()
            assert "price" in {
                f.field["name"] for f in engine._item_fields["megaphone"]
            }  # noqa: SLF001
            with pytest.raises(WorldError, match="未注册"):
                api.add_item_fields("nope", [{"name": "x", "type": "int"}])
        finally:
            await engine.terminate()

    _run(fn())
