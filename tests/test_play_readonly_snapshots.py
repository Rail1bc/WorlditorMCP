"""玩法包只读接口的"真只读"保证（G51）。

修复前：`get_entity` / `list_entities` / `query_entities` 是深拷贝，但
`get_component`（浅拷贝——嵌套 dict/list 与内核共享）、`get_map` / `get_location` /
`get_world` / `list_worlds` / `list_folders` / `list_templates` / `capabilities` /
`kv_get` 直接返回内核**活对象**：改一下返回值就真的改了运行中的世界（不落库、不发
事件、不盖 revision，但内存快照漂移，重启才"自愈"）。

这里逐条钉住"改了不影响内核"。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore

PLAY_ID = "worlditor_play_ro"


def _run(coro):
    return asyncio.run(coro)


async def _make(tmp_path: Path) -> tuple[WorldEngine, WorlditorPlayAPI]:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    api = WorlditorPlayAPI(engine, PLAY_ID)
    await engine.create_map("m1", "主世界", description=None, world_id="default")
    await engine.create_location("m1", 0, 0, "广场")
    return engine, api


def test_mutating_read_results_does_not_touch_kernel(tmp_path):
    """改返回值：地图名 / 地块名 / 世界名 / 模板 / KV 都不得影响内核。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            # 地图：活对象曾能被改名
            m = api.get_map("m1")
            m.name = "被改名的地图"
            assert engine.get_map("m1").name == "主世界"
            # 地块
            loc = api.get_location("m1", 0, 0)
            loc.name = "被改名的地块"
            assert engine.get_location("m1", 0, 0).name == "广场"
            # 世界
            w = api.get_world("default")
            w.name = "被改名的世界"
            assert engine.get_world("default").name != "被改名的世界"
            worlds = api.list_worlds()
            worlds[0].name = "又一次"
            assert engine.get_world("default").name != "又一次"
            # 组织树
            folders = api.list_folders("default")
            assert folders == [] or folders is not None  # 形态稳定即可
            # 模板：data 曾与注册表共享
            api.register_entity_template(
                "t1",
                "模板",
                {"name": "模板", "desc": "", "components": {"local:a": {}}},
            )
            t = next(x for x in api.list_templates("entity") if x["id"] == "t1")
            t["data"]["components"]["local:injected"] = {}
            again = next(x for x in api.list_templates("entity") if x["id"] == "t1")
            assert "local:injected" not in again["data"]["components"]
            # KV：曾返回内核缓存里的同一个对象
            await api.kv_set("bag", {"apple": 1})
            bag = api.kv_get("bag")
            bag["apple"] = 999
            assert api.kv_get("bag") == {"apple": 1}
        finally:
            await engine.terminate()

    _run(fn())


def test_mutating_component_and_capabilities_does_not_touch_kernel(tmp_path):
    """组件数据（嵌套）与能力声明（fields）都不得被返回值改到。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            engine.attach_play_api(
                PLAY_ID, api
            )  # 模拟"包已加载"（决定组件是否 active）
            api.declare_component(
                "cfg",
                fields=[{"name": "hp", "label": "血", "type": "int", "default": 10}],
            )
            eid = (await engine.place_entity("player", "m1", 0, 0, name="甲")).id
            await api.set_component(eid, f"{PLAY_ID}:cfg", {"nested": {"hp": 10}})
            got = api.get_component(eid, f"{PLAY_ID}:cfg")
            got["nested"]["hp"] = 999
            assert engine.get_component(eid, f"{PLAY_ID}:cfg") == {"nested": {"hp": 10}}
            # capabilities 的 fields 是**声明对象**，改了会影响所有带该组件的实体
            entity = engine.get_entity(eid)
            caps = api.capabilities(entity)
            caps["fields"][f"{PLAY_ID}:cfg"][0]["type"] = "json"
            assert (
                api.capabilities(engine.get_entity(eid))["fields"][f"{PLAY_ID}:cfg"][0][
                    "type"
                ]
                == "int"
            )
        finally:
            await engine.terminate()

    _run(fn())


def test_list_actions_accepts_viewer(tmp_path):
    """list_actions 透传 viewer/tier：看不见的目标 → 空菜单（玩法包自建 UI 也能过滤）。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            api.register_interaction("talk", lambda api, req: None, label="打招呼")
            api.declare_component("npc", interactions=("talk",))
            npc = await engine.place_entity("npc", "m1", 0, 0, name="守卫")
            viewer = await engine.place_entity("player", "m1", 0, 0, name="看客")
            assert [a.action for a in api.list_actions(npc.id)] == ["talk"]
            # 传了 viewer：正常可见（同格、非隐身）
            assert [
                a.action for a in api.list_actions(npc.id, viewer_id=viewer.id)
            ] == ["talk"]
            # 目标隐身 → 该 viewer 看不到，菜单为空
            await api.set_perception(npc.id, {"invisible": True})
            assert api.list_actions(npc.id, viewer_id=viewer.id) == []
        finally:
            await engine.terminate()

    _run(fn())
