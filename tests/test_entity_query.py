"""D26 实体查询原语（query_entities）测试。

覆盖：组件 AND / exclude、kind 与预设组件都是组件、虚构组件、D21 世界激活语义、
世界/地图/坐标范围、limit、稳定排序、viewer 感知过滤、where、严格校验。
（D41：查询参数名仍是 ``tags=`` / ``exclude_tags=``，但筛的是**组件键**——
裸名按 D41 解析：唯一声明者 → 加前缀；无人声明 → ``local:``；多个声明者 → 报错。）
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from play_fixtures import install_demo_play  # noqa: E402
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


def _attach(engine: WorldEngine, play_id: str) -> WorlditorPlayAPI:
    """绑定一个"已加载"的玩法包 API（D26 组件活性 = 已加载 + 世界激活）。"""
    api = WorlditorPlayAPI(engine, play_id)
    engine.attach_play_api(play_id, api)
    return api


def _ids(entities) -> set[str]:
    return {e.id for e in entities}


def test_query_by_components(tmp_path):
    """组件查询：AND 语义、exclude_tags、kind 与预设组件都是组件（D41/D26）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            _attach(engine, "pkg_a")
            engine.register_entity_tag("poisoned", play_id="pkg_a", label="中毒")
            engine.register_entity_tag("undead", play_id="pkg_a", label="亡灵")
            wolf = await engine.place_entity("wolf", "default", 0, 0, tags=["poisoned"])
            ghost = await engine.place_entity(
                "ghost", "default", 0, 0, tags=["poisoned", "undead"]
            )
            dog = await engine.place_entity("wolf", "default", 1, 0)
            # kind 自己就是一条能力组件（D41：kind 是输入便利，落成同名组件键）
            assert wolf.has_component("local:wolf")
            assert wolf.has_component("pkg_a:poisoned")
            assert ghost.has_component("pkg_a:undead")
            assert _ids(engine.query_entities(tags=["wolf"])) == {wolf.id, dog.id}
            assert _ids(engine.query_entities(tags=["poisoned"])) == {
                wolf.id,
                ghost.id,
            }
            # AND：必须全部具备
            assert _ids(engine.query_entities(tags=["poisoned", "undead"])) == {
                ghost.id
            }
            assert engine.query_entities(tags=["poisoned", "absent"]) == []
            # exclude_tags
            assert _ids(
                engine.query_entities(tags=["poisoned"], exclude_tags=["undead"])
            ) == {wolf.id}
            # 类型预设（D18："类型 A = {A, C}"）→ D41 归**实体模板**：
            # 模板 = 一组组件的预设，套用即得那组能力组件
            engine.register_entity_template(
                "zombie",
                "僵尸",
                {
                    "name": "僵尸",
                    "components": {"pkg_a:undead": {}, "pkg_a:poisoned": {}},
                },
            )
            tmpl = next(
                t for t in engine.list_templates("entity") if t["id"] == "zombie"
            )
            zombie = await engine.place_entity(
                "zombie",
                "default",
                0,
                0,
                components=tmpl["data"]["components"],
            )
            assert zombie.has_component("pkg_a:undead")
            assert _ids(engine.query_entities(tags=["undead", "poisoned"])) == {
                ghost.id,
                zombie.id,
            }
            # 无声明者的纯数据组件（**虚构组件**，实例自带）照常匹配
            marked = await engine.place_entity(
                "thing", "default", 0, 0, tags=["my_marker"]
            )
            assert marked.has_component("local:my_marker")
            assert _ids(engine.query_entities(tags=["my_marker"])) == {marked.id}
        finally:
            await engine.terminate()

    _run(fn())


def test_query_respects_world_activation(tmp_path):
    """D21/D26：声明该组件的包在实体所在世界未激活 → 该组件不匹配。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            _attach(engine, "pkg_poison")
            engine.register_entity_tag("poisoned", play_id="pkg_poison", label="中毒")
            await engine.create_world("quiet", "静默世界", play_ids=["pkg_other"])
            await engine.assign_map("default", "quiet")
            entity = await engine.place_entity(
                "wolf", "default", 0, 0, tags=["poisoned", "marker"]
            )
            # 组件照常落在实体上（数据留下），只是能力在本世界不生效
            assert entity.has_component("pkg_poison:poisoned")
            # 能力面：该组件在该世界不活跃（D21）
            caps = engine.capabilities(entity)
            assert "pkg_poison:poisoned" in caps["inactive_components"]
            # 查询面：能力不存在 → 不匹配（与 available_actions 同源）
            assert engine.query_entities(tags=["poisoned"]) == []
            assert _ids(engine.query_entities(exclude_tags=["poisoned"])) == {entity.id}
            # 无声明者的纯数据组件（虚构组件）不受激活过滤影响
            assert _ids(engine.query_entities(tags=["marker"])) == {entity.id}
            # 世界激活后即可匹配
            await engine.update_world("quiet", play_ids=["pkg_poison"])
            assert _ids(engine.query_entities(tags=["poisoned"])) == {entity.id}
        finally:
            await engine.terminate()

    _run(fn())


def test_query_deactivated_play_component_does_not_match(tmp_path):
    """停用/真卸载语义：停用 → 声明的组件不匹配；真卸载 → 归属记忆清除，回到纯数据。

    走真实 PlayLoader（停用会清注册 + 解绑 API，而组件本身仍留在实体数据上）。
    """
    install_demo_play(tmp_path / "plays")

    async def fn():
        engine = await _engine(tmp_path)
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0"
        )
        await loader.load_all()
        try:
            merchant = await engine.place_entity("merchant", "default", 0, 0)
            # 组件键 = 行为包声明的共享键（world.json 的内容与行为包同用 local:）
            assert merchant.has_component("local:merchant")
            assert _ids(engine.query_entities(tags=["merchant"])) == {merchant.id}
            # 停用：能力没了 → 不匹配（实体数据照旧在）
            await loader.disable("worlditor_play_demo")
            assert engine.query_entities(tags=["merchant"]) == []
            assert engine.get_entity(merchant.id) is not None
            # 重新启用：又能匹配
            await loader.enable("worlditor_play_demo")
            assert _ids(engine.query_entities(tags=["merchant"])) == {merchant.id}
            # 真卸载（purge）：归属记忆清掉 → 组件回到"无声明者的纯数据"
            await loader.uninstall("worlditor_play_demo")
            assert _ids(engine.query_entities(tags=["local:merchant"])) == {merchant.id}
        finally:
            await engine.terminate()

    _run(fn())


def test_query_scope_and_order(tmp_path):
    """范围筛选（地图 / 世界 / 坐标）+ 稳定排序（map_id, row, col, id）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.create_map("iso", "孤岛")
            await engine.create_location("iso", 0, 0, "岸")
            await engine.create_map("home", "家园")
            await engine.create_location("home", 0, 0, "门厅")
            await engine.assign_map("home", "default")
            # 未归属地图按默认世界算（与 _world_for_activation 同源）
            far = await engine.place_entity("wolf", "iso", 0, 0)
            near = await engine.place_entity("wolf", "home", 0, 0)
            assert _ids(engine.query_entities(world_id="default")) == {far.id, near.id}
            await engine.create_world("w2", "第二世界", play_ids=[])
            await engine.assign_map("iso", "w2")
            assert _ids(engine.query_entities(world_id="default")) == {near.id}
            assert _ids(engine.query_entities(world_id="w2")) == {far.id}
            assert _ids(engine.query_entities(map_id="home")) == {near.id}
            # 坐标筛选（与 list_entities 同义）
            assert _ids(engine.query_entities(row=0, col=0)) == {far.id, near.id}
            assert engine.query_entities(map_id="home", row=9) == []
            # 稳定排序：同组件键时按 (map_id, row, col, id)
            listed = engine.query_entities(tags=["wolf"])
            assert listed == sorted(
                listed, key=lambda e: (e.map_id, e.row, e.col, e.id)
            )
            # limit 在排序后生效（取前 N 个，可预测）
            assert engine.query_entities(limit=1)[0].id == listed[0].id
        finally:
            await engine.terminate()

    _run(fn())


def test_query_viewer_perception(tmp_path):
    """viewer_id 感知过滤（G12）：隐身对普通 viewer 隐藏，真视/自己可见。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            spy = await engine.place_entity(
                "player",
                "default",
                0,
                0,
                name="潜行者",
                components={"core:perception": {"invisible": True}},
            )
            guard = await engine.place_entity("player", "default", 0, 0, name="守卫")
            seer = await engine.place_entity(
                "player",
                "default",
                0,
                0,
                name="先知",
                components={"core:perception": {"see_invisible": True}},
            )
            assert spy.id not in _ids(engine.query_entities(viewer_id=guard.id))
            assert spy.id in _ids(engine.query_entities(viewer_id=spy.id))
            assert spy.id in _ids(engine.query_entities(viewer_id=seer.id))
            assert spy.id in _ids(engine.query_entities())  # 机制层不过滤
            # 与 list_entities 同一套判定（GT12 单一判定点）
            assert _ids(engine.query_entities(viewer_id=guard.id)) == _ids(
                engine.list_entities(viewer_id=guard.id)
            )
        finally:
            await engine.terminate()

    _run(fn())


def test_query_where_and_limit(tmp_path):
    """where 谓词（进程内逃生口）+ limit。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            weak = await engine.place_entity(
                "wolf", "default", 0, 0, components={"local:stat": {"hp": 1}}
            )
            await engine.place_entity(
                "wolf", "default", 1, 0, components={"local:stat": {"hp": 9}}
            )
            found = engine.query_entities(
                where=lambda e: e.component("local:stat").get("hp", 0) < 5, limit=10
            )
            assert _ids(found) == {weak.id}
        finally:
            await engine.terminate()

    _run(fn())


def test_query_validation_is_strict(tmp_path):
    """严格校验：拼错的筛选条件要报错，而不是"悄悄查到空"（D23 精神）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            with pytest.raises(WorldError, match="标签数组"):
                engine.query_entities(tags="poisoned")
            with pytest.raises(WorldError, match="非空字符串"):
                engine.query_entities(tags=[""])
            with pytest.raises(WorldError, match="非空字符串"):
                engine.query_entities(exclude_tags=[1])
            with pytest.raises(WorldError, match="地图不存在"):
                engine.query_entities(map_id="nope")
            with pytest.raises(WorldError, match="世界不存在"):
                engine.query_entities(world_id="nope")
            with pytest.raises(WorldError, match="row"):
                engine.query_entities(row="0")
            with pytest.raises(WorldError, match="limit"):
                engine.query_entities(limit=0)
            with pytest.raises(WorldError, match="changed_since_tick"):
                engine.query_entities(changed_since_tick=-1)
            with pytest.raises(WorldError, match="where"):
                engine.query_entities(where="not-callable")
        finally:
            await engine.terminate()

    _run(fn())


def test_query_via_play_api(tmp_path):
    """玩法包 API 出口：query_entities（同一实现）与 current_tick（D28）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "worlditor_play_probe")
            wolf = await engine.place_entity("wolf", "default", 0, 0, tags=["hunter"])
            assert _ids(api.query_entities(map_id="default", tags=["hunter"])) == {
                wolf.id
            }
            assert api.current_tick() == engine.tick
            with pytest.raises(WorldError, match="世界不存在"):
                api.query_entities(world_id="nope")
        finally:
            await engine.terminate()

    _run(fn())
