"""内容包单事务导入（G55）：``api.import_bundle``。

背景：世界包按老办法逐条 `create_map` / `create_location` / `place_entity` 写内容，
中途抛错会留下**半张世界**；而按官方幂等写法（"地图已存在则跳过"）重跑时会
**假装成功**——得到一张看起来导入完成、实际缺地块的世界。`import_bundle` 把整批
内容放进一次 SQLite 提交：要么全落盘、要么一个字节都不写。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore

PLAY_ID = "worlditor_play_content"

_MAP = {"id": "main", "name": "主世界", "spawn_row": 0, "spawn_col": 0}
_LOCS = [
    {"row": 0, "col": 0, "name": "广场"},
    {"row": 0, "col": 1, "name": "商店"},
]
_ENTS = [
    {
        "row": 0,
        "col": 0,
        "name": "阿福",
        "desc": "广场上的老商贩",
        "components": {"local:merchant": {"mood": "good"}},
    },
    {"row": 0, "col": 1, "name": "货架"},
]


def _run(coro):
    return asyncio.run(coro)


async def _make(tmp_path: Path) -> tuple[WorldEngine, WorlditorPlayAPI]:
    """空库引擎（内核只播种一个空的默认世界，没有地图/地块/实体）+ 玩法包 API。"""
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine, WorlditorPlayAPI(engine, PLAY_ID)


def test_import_bundle_commits_everything(tmp_path):
    """一次导入：地图 + 地块 + 实体 + 世界归属全部落地，实体折进 core 组件。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            result = await api.import_bundle(
                _MAP, locations=_LOCS, entities=_ENTS, world_id="default"
            )
            assert result["map_id"] == "main"
            assert result["locations"] == 2
            assert result["entities"] == 2
            assert len(result["entity_ids"]) == 2
            assert engine.get_map("main") is not None
            assert engine.get_location("main", 0, 1).name == "商店"
            assert engine.map_world("main") == "default"
            by_name = {e.name: e for e in engine.list_entities("main")}
            assert set(by_name) == {"阿福", "货架"}
            fu = by_name["阿福"]
            assert fu.has_component("local:merchant")  # components 原样带上
            assert fu.component("local:merchant") == {"mood": "good"}
            assert fu.has_position()  # 坐标折进 core:position
            assert fu.component("core:position") == {
                "map_id": "main",
                "row": 0,
                "col": 0,
            }
            assert fu.component("core:info")["desc"] == "广场上的老商贩"
            # 归属落库（世界与地图的对应关系）
            assert engine.list_maps_by_folder("default") is not None
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_failure_writes_nothing(tmp_path):
    """第 3 个地块非法 → 整批回滚：地图、地块、实体一个都不落盘。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            bad = [*_LOCS, {"row": 5, "col": 5}]  # 没有 name
            before = engine.revision
            with pytest.raises(WorldError, match="第 3 个地块"):
                await api.import_bundle(
                    _MAP, locations=bad, entities=_ENTS, world_id="default"
                )
            assert engine.get_map("main") is None
            assert engine.list_locations() == []
            assert engine.list_entities(include_absent=True) == []
            assert engine.store.maps == {}
            assert engine.store.entities == {}
            # revision 也没动（校验先于写入，连事务都没开）
            assert engine.revision == before
            # 修好后同一批能正常导入（证明确实是"零落盘"，不是"卡住了"）
            assert (await api.import_bundle(_MAP, locations=_LOCS, entities=_ENTS))[
                "locations"
            ] == 2
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_rejects_existing_map(tmp_path):
    """地图已存在 → 报错且不覆盖（是否跳过由玩法包自己判断）。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            await api.import_bundle(_MAP, locations=_LOCS, entities=_ENTS)
            with pytest.raises(WorldError, match="地图已存在"):
                await api.import_bundle(_MAP, locations=_LOCS, entities=_ENTS)
            assert len(engine.list_locations()) == 2  # 原样
            assert len(engine.list_entities()) == 2
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_entity_tile_must_exist(tmp_path):
    """实体坐标必须落在本批地块或世上已有地块上；半截坐标直接拒绝。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            ghost = [{"row": 9, "col": 9, "name": "幽灵"}]
            with pytest.raises(WorldError, match="第 1 个实体的地块不存在"):
                await api.import_bundle(_MAP, locations=_LOCS, entities=ghost)
            half = [{"row": 0, "name": "半截"}]
            with pytest.raises(WorldError, match="半截"):
                await api.import_bundle(_MAP, locations=_LOCS, entities=half)
            assert engine.get_map("main") is None
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_absent_entity_is_allowed(tmp_path):
    """不给坐标 = 造一个不在世界上的实体（容器里的东西 / 待投放的 NPC）。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            result = await api.import_bundle(
                _MAP,
                locations=_LOCS,
                entities=[{"name": "备货的箱子", "components": {"local:box": {}}}],
            )
            assert result["entities"] == 1
            assert engine.list_entities() == []  # 不在世界上：默认查不到
            absent = engine.list_entities(include_absent=True)
            assert [e.name for e in absent] == ["备货的箱子"]
            assert not absent[0].has_position()
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_validates_text_schedule(tmp_path):
    """文案必须走 TextSchedule 结构；纯字符串报错（带行号）。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            with pytest.raises(WorldError, match="第 1 个地块非法"):
                await api.import_bundle(
                    _MAP,
                    locations=[
                        {"row": 0, "col": 0, "name": "广场", "description": "白天"}
                    ],
                )
            assert engine.get_map("main") is None
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_api_rejects_core_components(tmp_path):
    """玩法包不得写 core:（D33）——实体组件在 API 边界就被拒。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            with pytest.raises(WorldError, match="core:"):
                await api.import_bundle(
                    _MAP,
                    locations=_LOCS,
                    entities=[
                        {
                            "row": 0,
                            "col": 0,
                            "components": {"core:info": {"name": "偷写"}},
                        }
                    ],
                )
            assert engine.get_map("main") is None
        finally:
            await engine.terminate()

    _run(fn())


def test_import_bundle_emits_single_world_edited(tmp_path):
    """完成后只发一条 on_world_edited（不为每个实体补发 place_entity）。"""

    async def fn():
        engine, api = await _make(tmp_path)
        try:
            seen: list[dict] = []

            async def on_edited(api, what):
                seen.append(what)

            engine.register_world_event("on_world_edited", on_edited, play_id=PLAY_ID)
            await api.import_bundle(_MAP, locations=_LOCS, entities=_ENTS)
            assert [w["op"] for w in seen] == ["import_bundle"]
            assert seen[0]["map_id"] == "main"
            assert (seen[0]["locations"], seen[0]["entities"]) == (2, 2)
        finally:
            await engine.terminate()

    _run(fn())
