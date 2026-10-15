"""实体组件与能力（D41：**能力 = 组件的存在**）。

回归背景：v0.4 之前 `entities.kind` 是**单值**且身兼三职——身份（IDENTITY_KINDS）、
行为声明（interactions）、字段 schema 归属；D18 把它拆成"类型 + 标签"两套声明，
但**能力仍存在两张表列里**（`kind` / `tags_json`），与 `components` 是两个平行世界。
D41 把两者折起来：**实体带了哪个组件，就具备哪条能力**。

本模块守住 D41 的语义：

1. 声明只有**一套**（`declare_component`；`register_entity_kind` / `register_entity_tag`
   是保留的旧名），组件名 = `source:name`——两个包各声明 `merchant` 是**两个组件共存**
2. 能力 = 实体的组件键；纯能力组件的数据是 `{}`（"空组件"与"没有这个组件"必须分得开）
3. `interactions` 多组件取**并集**；字段清单**按组件分组**，不跨组件摊平
4. **同一组件内同名字段重复声明 → 报错**；分类字段已删除（`categories` 只作选取分组）
5. "类型 = 一组组件的预设"归**实体模板**，声明 API 的 `tags=` 已作废
6. 能力面**逐个组件**按世界激活过滤；没有声明的组件 = **虚构组件**（允许、不贡献能力）
7. 规格级缓存随注册表变动失效
8. 实体落库只有组件（表 v11 / 4 列）
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from world_fixtures import schedule, seed_test_world

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import TagSpec, WorldTemplate, parse_names
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


async def _noop_handler(api, req):  # pragma: no cover - 仅用于注册动作
    from worlditor_mcp.world.model import InteractionResult

    return InteractionResult(text="ok")


# ---------- D41：一套声明 API ----------


def test_declare_component_and_old_names_are_equivalent(tmp_path):
    """`declare_component` 是唯一入口；`register_entity_kind` / `register_entity_tag` 等价。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            key = engine.declare_component("door", interactions=("open",), label="木门")
            assert key == "local:door"
            spec = engine._tag_specs["local:door"]
            assert isinstance(spec, TagSpec)
            assert (
                spec.key == "local:door"
                and spec.source == "local"
                and spec.name == "door"
            )

            listing = {k["key"]: k for k in engine.list_kinds()}
            door = listing["local:door"]
            assert door["label"] == "木门"
            assert door["interactions"] == ["open"]
            assert door["source"] == "local" and door["name"] == "door"
            # D41：声明只有一套 → 清单里没有"是否隐式 / 预设标签"这类旧概念
            assert "implicit" not in door and "preset_tags" not in door
            # D34：阻挡机制整体移除，能力面不再有 block_move
            assert "block_move" not in door

            # 旧名等价：同一个键、同样的规格
            engine.register_entity_kind("door", interactions=("open",), label="木门")
            engine.register_entity_tag("door", interactions=("open",), label="木门")
            again = engine.declare_component(
                "door", interactions=("open",), label="木门"
            )
            assert again == "local:door"

            door_entity = await engine.place_entity("door", "default", 0, 0)
            assert door_entity.name == "木门"  # 默认名仍取 label
            assert door_entity.has_component("local:door")
            assert door_entity.component("local:door") == {}  # 纯能力组件：无数据
            caps = engine.capabilities(door_entity)
            assert caps["interactions"] == ["open"]
            assert "block_move" not in caps
        finally:
            await engine.terminate()

    _run(fn())


def test_composition_player_plus_spawner(tmp_path):
    """组合：玩家组件 + 刷怪笼组件 → 两边能力同时生效（用户的核心设想）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag(
                "spawner",
                label="刷怪笼",
                interactions=("tune",),
                fields=[{"name": "mob", "type": "str", "default": "slime"}],
            )
            engine.register_interaction("tune", _noop_handler, label="设置生成物")
            player = await engine.place_entity(
                "player", "default", 0, 0, name="小明", tags=["spawner"]
            )
            caps = engine.capabilities(player)
            assert set(caps["components"]) == {
                "local:player",
                "local:spawner",
                "core:position",
                "core:info",
            }
            # player 没有注册过规格（D42：身份概念已删，player 只是个未声明的组件名）
            # → 只有 spawner 在贡献；D44：`local:` 未声明 = 虚构（不是"坏了"）
            assert caps["active_components"] == ["local:spawner"]
            assert caps["fictional_components"] == ["local:player"]
            assert caps["orphan_components"] == []
            assert "tune" in caps["interactions"]
            assert "tune" in engine.available_actions(player.id)
            assert {f["name"] for f in caps["fields"]["local:spawner"]} == {"mob"}
            # D42：**没有"身份"这回事**——带 player 组件不带任何特权，
            # 判据是账户绑定（这个实体没绑账户 → 普通实体，可以被 remove）
            assert player.is_account_bound() is False
        finally:
            await engine.terminate()

    _run(fn())


def test_type_presets_moved_to_templates(tmp_path):
    """D41：声明 API 不再收 `tags=`；"类型 = 一组组件的预设"归实体模板。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("a", label="能力甲")
            engine.register_entity_tag("b", label="能力乙")
            engine.register_entity_tag("c", label="公共能力", interactions=("ping",))
            engine.register_interaction("ping", _noop_handler, label="ping")

            with pytest.raises(WorldError, match="实体模板"):
                engine.register_entity_kind("A", tags=["c"], label="甲型")
            with pytest.raises(WorldError, match="实体模板"):
                engine.register_entity_type("A", tags=["c"], label="甲型")

            # 预设的正确落点：实体模板 = "照这个建一个实体"（一组组件）
            engine.register_entity_template(
                "type_a",
                "甲型",
                {"components": {"local:A": {}, "local:c": {}}},
            )
            tmpl = next(
                t for t in engine.list_templates("entity") if t["id"] == "type_a"
            )
            assert tmpl["data"]["components"] == {"local:A": {}, "local:c": {}}
            # 套用即得"类型 A = {A, c}"那组能力（c 的 ping 同时生效）
            a = await engine.place_entity(
                "A", "default", 0, 0, components=tmpl["data"]["components"]
            )
            assert engine.capabilities(a)["interactions"] == ["ping"]
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D41：并集与"不摊平" ----------


def test_interactions_union_across_components(tmp_path):
    """多组件的 interactions 取**并集**（D19 保留项在新模型下的形态）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("soft", interactions=("lean",), label="软")
            engine.register_entity_tag("hard", interactions=("smash",), label="硬")
            engine.register_interaction("lean", _noop_handler, label="倚靠")
            engine.register_interaction("smash", _noop_handler, label="砸")
            both = await engine.place_entity(
                "rock", "default", 0, 0, tags=["soft", "hard"]
            )
            # 并集：两个组件各贡献一个动作，互不覆盖
            assert engine.capabilities(both)["interactions"] == ["lean", "smash"]
            assert "lean" in engine.available_actions(both.id)
            assert "smash" in engine.available_actions(both.id)

            engine.register_entity_tag(
                "only_soft", interactions=("lean",), label="只软"
            )
            one = await engine.place_entity("rock", "default", 0, 1, tags=["only_soft"])
            assert engine.capabilities(one)["interactions"] == ["lean"]
        finally:
            await engine.terminate()

    _run(fn())


def test_fields_are_grouped_by_component(tmp_path):
    """D41：字段清单**按组件分组**——每个字段属于声明它的组件，不跨组件覆盖。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg")
            engine.attach_play_api("pkg", api)
            api.register_entity_kind(
                "base",
                fields=[{"name": "x", "type": "str", "default": "base"}],
                categories=("生物",),
            )
            api.register_entity_tag(
                "t1", fields=[{"name": "x", "type": "str", "default": "t1"}]
            )
            api.register_entity_tag("t2", fields=[{"name": "y", "type": "int"}])

            e = await engine.place_entity("base", "default", 0, 0, tags=["t1", "t2"])
            fields = engine.capabilities(e)["fields"]
            assert set(fields) == {"pkg:base", "pkg:t1", "pkg:t2"}
            # 同名不同组件互不覆盖（各报各的；旧模型里 t1 会覆盖 base）
            assert fields["pkg:base"][0]["default"] == "base"
            assert fields["pkg:t1"][0]["default"] == "t1"
            assert {f["name"] for f in fields["pkg:t2"]} == {"y"}

            # 单组件查询：只看该组件自己的声明
            assert engine.effective_fields("pkg:base")[0]["default"] == "base"
            assert engine.effective_fields("pkg:t1")[0]["default"] == "t1"
            # 多组件清单带组件归属（不摊平成一个 list 丢失来源）
            merged = engine.effective_fields_for(["pkg:base", "pkg:t1"])
            assert {f["component"] for f in merged} == {"pkg:base", "pkg:t1"}
            # 分类只是**选取分组**（D10），不再承载字段（D41 删了分类字段）
            assert engine.list_kinds(category="生物")[0]["key"] == "pkg:base"
            assert not hasattr(engine, "add_category_fields")
        finally:
            await engine.terminate()

    _run(fn())


def test_add_tag_fields_extends_one_component_only(tmp_path):
    """`add_tag_fields` = 给**一个组件**追加字段（跨包扩展的正当路径）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg")
            engine.attach_play_api("pkg", api)
            api.register_entity_kind("monster", fields=[{"name": "hp", "type": "int"}])
            api.register_entity_kind("slime", fields=[{"name": "goo", "type": "int"}])
            # 老写法：给 monster 追加字段（旧名 add_kind_fields 等价）
            api.add_kind_fields("monster", [{"name": "poison", "type": "bool"}])

            tagged = await engine.place_entity(
                "slime", "default", 0, 0, tags=["monster"]
            )
            plain = await engine.place_entity("slime", "default", 0, 1)
            # 带上 monster 组件 = 同时获得它自身的声明字段与追加字段
            assert {
                f["name"] for f in engine.capabilities(tagged)["fields"]["pkg:monster"]
            } == {
                "hp",
                "poison",
            }
            # 追加只影响那个组件：slime 自己的字段清单没被摊平进来
            assert {
                f["name"] for f in engine.capabilities(plain)["fields"]["pkg:slime"]
            } == {"goo"}

            # D41 唯一保留的字段规则：同一组件内同名字段声明两次 → 报错
            with pytest.raises(WorldError, match="重复声明"):
                api.add_tag_fields("monster", [{"name": "hp", "type": "int"}])
            with pytest.raises(WorldError, match="重复声明"):
                api.add_tag_fields("monster", [{"name": "poison", "type": "bool"}])
            with pytest.raises(WorldError, match="重复声明"):
                api.register_entity_tag("dup", fields=[{"name": "z"}, {"name": "z"}])
        finally:
            await engine.terminate()

    _run(fn())


def test_unregistered_component_is_fictional_and_harmless(tmp_path):
    """允许未声明组件（**虚构组件**，D41）：实体照常存在，不贡献任何能力。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity(
                "rock", "default", 0, 0, tags=["nobody_knows"]
            )
            caps = engine.capabilities(e)
            assert "local:rock" in caps["components"]
            assert "local:nobody_knows" in caps["components"]
            # 两个 local: 组件都没有声明 → 都算**虚构**（D44：本来就没有行为，不是坏了）
            assert caps["active_components"] == []
            assert set(caps["fictional_components"]) == {
                "local:rock",
                "local:nobody_knows",
            }
            assert caps["orphan_components"] == []
            assert caps["fields"] == {}
            assert caps["interactions"] == []
            assert "block_move" not in caps  # D34：阻挡机制已移除
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D42：身份概念已删，红线判据 = 账户绑定 ----------


def test_account_bound_is_the_red_line_not_components(tmp_path):
    """D42：**组件名**不决定保护——只有 `core:account` 决定。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            npc = await engine.place_entity("npc", "default", 0, 0, tags=["player"])
            assert npc.is_account_bound() is False
            player = await engine.place_entity("player", "default", 0, 1)
            assert player.is_account_bound() is False
            # 身份保护不看组件：没绑账户就是普通实体，可以被移除
            await engine.remove_entity(npc.id)
            assert engine.store.entities.get(npc.id) is None
            await engine.remove_entity(player.id)
            assert engine.store.entities.get(player.id) is None
            # 反过来：带 npc 组件、但绑了账户 → 拒绝移除
            bound = await engine.place_entity(
                "npc", "default", 1, 0, name="挂了账户的 NPC", user_id="acct_1"
            )
            assert bound.is_account_bound() is True
            with pytest.raises(WorldError, match="绑定了账户"):
                await engine.remove_entity(bound.id)
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D21：逐组件世界激活过滤 + 缓存 ----------


def test_component_capability_filtered_by_world_activation(tmp_path):
    """组件所属包在实体所在世界未激活 → 该组件不参与并集。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag(
                "spawner", interactions=("tune",), play_id="pkg_b"
            )
            # D44：**"有声明但包没加载"算孤儿**，不是"未启用"——所以要模拟"包已加载、
            # 只是这个世界没启用它"，得把 API 挂上（真实部署里由 PlayLoader 做）
            engine.attach_play_api("pkg_b", WorlditorPlayAPI(engine, "pkg_b"))
            await engine.create_world("w_a", "只有A", play_ids=["pkg_a"])
            await engine.create_world("w_b", "有B", play_ids=["pkg_b"])
            await engine.create_map("m_a", "甲图")
            await engine.create_location("m_a", 0, 0, "格")
            await engine.assign_map("m_a", "w_a")
            e = await engine.place_entity("slime", "m_a", 0, 0, tags=["spawner"])

            caps = engine.capabilities(e)
            assert "pkg_b:spawner" in caps["components"]
            assert caps["active_components"] == []  # pkg_b 不在 w_a
            assert caps["interactions"] == []
            assert caps["inactive_components"] == ["pkg_b:spawner"]

            await engine.assign_map("m_a", "w_b")
            caps = engine.capabilities(e)
            assert caps["active_components"] == ["pkg_b:spawner"]
            assert caps["interactions"] == ["tune"]
        finally:
            await engine.terminate()

    _run(fn())


def test_spec_cache_invalidated_when_component_declared_later(tmp_path):
    """规格级缓存：注册表变动后，先前算过的组件键集合必须重算。

    ⚠ D41 的**修正**：先手输 `late` 再装包声明 `late`，不再是"白捡"——`local:late`
    与 `pkg_x:late` 是两个不同的组件（同 `fps:hp` / `moba:hp`）。所以半个场景改成
    "声明**同一个键**"（`local:late` 由本包声明时就是它）。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity("slime", "default", 0, 0, tags=["late"])
            assert engine.capabilities(e)["interactions"] == []  # local:late 还没声明
            engine.register_entity_tag("late", interactions=("poke",))
            assert engine.capabilities(e)["interactions"] == ["poke"]  # 缓存已失效

            # 另一个来源的同名组件是**另一个组件**：不会把能力"接"到已有实体上
            engine.register_entity_tag("late", interactions=("poke",), play_id="pkg_x")
            # D44：pkg_x 没加载 → 它的组件算孤儿（不是"生效"），所以先把包挂上
            engine.attach_play_api("pkg_x", WorlditorPlayAPI(engine, "pkg_x"))
            assert engine.capabilities(e)["interactions"] == [
                "poke"
            ]  # 仍只有 local:late
            e2 = await engine.place_entity(
                "slime", "default", 0, 1, components={"pkg_x:late": {}}
            )
            assert engine.capabilities(e2)["interactions"] == ["poke"]
            assert engine.capabilities(e2)["active_components"] == ["pkg_x:late"]
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 持久化与解析 ----------


def test_components_persist_and_parse_rules(tmp_path):
    """组件落库并跨引擎重开保留；名字解析去重保序、丢弃非字符串。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity(
                "player", "default", 0, 0, name="小明", tags=["b", "a", "b", "", 7]
            )
            assert "local:b" in e.components and "local:a" in e.components
            assert e.to_dict()["components"] == e.components
            assert set(e.to_dict()) == {
                "id",
                "components",
                "last_active_ts",
                "revision",
                "changed_tick",
            }
        finally:
            await engine.terminate()
        again = WorldEngine(WorldStore(tmp_path / "world.db"))
        await again.initialize()
        try:
            stored = next(iter(again.store.entities.values()))
            assert "local:b" in stored.components and "local:a" in stored.components
            assert stored.to_dict()["components"] == stored.components
            # 顺序按输入（去重保序）：b 在前、a 在后
            order = list(stored.components)
            assert order.index("local:b") < order.index("local:a")
            # D41：在线状态只在内存，不落库
            assert stored.last_active_ts == 0.0
        finally:
            await again.terminate()

    _run(fn())


def test_parse_names_helper():
    assert parse_names("solo") == ["solo"]
    assert parse_names([" a ", "a", "", None, 3, "b"]) == ["a", "b"]
    assert parse_names(None) == []
    assert parse_names({"a": 1}) == []


def test_update_entity_replaces_components(tmp_path):
    """PATCH 语义：`components` 整体替换；加/摘单个能力走组件原语。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity("rock", "default", 0, 0, tags=["x"])
            assert e.has_component("local:x")
            await engine.update_entity(
                e.id, components={"local:y": {}, "local:z": {"n": 1}}
            )
            assert "local:x" not in e.components
            assert e.components["local:z"] == {"n": 1}
            with pytest.raises(WorldError, match="components 必须是对象"):
                await engine.update_entity(e.id, components="not-a-dict")

            # 单点增删：add_component 已存在报错，remove_component 是显式摘能力的唯一途径
            await engine.add_component(e.id, "local:x", {})
            assert e.has_component("local:x")
            assert await engine.remove_component(e.id, "local:x") is True
            assert not e.has_component("local:x")
        finally:
            await engine.terminate()

    _run(fn())


def test_tick_field_removed(tmp_path):
    """D25：register_entity_kind 的 tick 死字段已删除（写了从没被读过）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            with pytest.raises(TypeError):
                engine.register_entity_kind("x", tick=True)
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D22：模板（地块 + 实体统一） ----------


def test_location_template_relative_targets(tmp_path):
    """地块模板套用：同图目标按放置位置平移（dr/dc 相对偏移）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.save_template(
                WorldTemplate(
                    id="room",
                    name="小房间",
                    scope="location",
                    data={
                        "name": "客房",
                        "description": schedule("一间安静的客房。"),
                        "connections": {
                            "up": {
                                "enabled": True,
                                "paths": [
                                    {
                                        "label": schedule("往北"),
                                        "reveal_target": True,
                                        "targets": [{"dr": -1, "dc": 0, "weight": 2.0}],
                                    }
                                ],
                            }
                        },
                    },
                )
            )
            loc = await engine.apply_location_template("room", "default", 5, 5)
            assert (loc.map_id, loc.row, loc.col) == ("default", 5, 5)
            assert loc.name == "客房"
            path = loc.connections["up"].paths[0]
            assert path.targets[0].map_id == ""  # 同图
            assert (path.targets[0].row, path.targets[0].col) == (4, 5)  # 平移
            assert path.targets[0].weight == 2.0  # 权重保住（G24 不接受丢字段）
            assert path.label is not None
            assert "往北" in json.dumps(path.label.to_dict(), ensure_ascii=False)
            # 负载里存的是相对偏移（可移植），不是绝对坐标
            stored = engine.store.templates["room"].data
            assert stored["connections"]["up"]["paths"][0]["targets"][0]["dr"] == -1
        finally:
            await engine.terminate()

    _run(fn())


def test_location_template_keeps_cross_map_target(tmp_path):
    """跨图目标原样复制（不跟着放置位置平移）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.save_template(
                WorldTemplate(
                    id="portal",
                    name="传送房",
                    scope="location",
                    data={
                        "name": "传送点",
                        "connections": {
                            "right": {
                                "enabled": True,
                                "paths": [
                                    {
                                        "targets": [
                                            {"map_id": "elsewhere", "row": 7, "col": 8}
                                        ]
                                    }
                                ],
                            }
                        },
                    },
                )
            )
            loc = await engine.apply_location_template("portal", "default", 3, 3)
            t = loc.connections["right"].paths[0].targets[0]
            assert (t.map_id, t.row, t.col) == ("elsewhere", 7, 8)
        finally:
            await engine.terminate()

    _run(fn())


def test_location_template_refuses_occupied_cell(tmp_path):
    """目标格已有地块 → 拒绝（不覆盖用户内容）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.save_template(
                WorldTemplate(
                    id="t", name="T", scope="location", data={"name": "新地块"}
                )
            )
            with pytest.raises(WorldError, match="已有地块"):
                await engine.apply_location_template("t", "default", 0, 0)
        finally:
            await engine.terminate()

    _run(fn())


def test_entity_template_play_and_local_sources(tmp_path):
    """实体模板：玩法包注册（内存）+ 管理端本地（落库）合并；同名本地优先。

    D41：模板负载是 `{name, desc, components}`——**"类型 = 一组组件的预设"就落在这里**。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_template(
                "spawner_tmpl",
                "刷怪笼",
                {
                    "name": "刷怪笼",
                    "components": {
                        "local:spawner": {},
                        "local:spawn": {"mob": "slime"},
                    },
                },
                play_id="pkg_spawn",
            )
            await engine.save_template(
                WorldTemplate(
                    id="local_tmpl",
                    name="本地商贩",
                    scope="entity",
                    data={"name": "商贩", "components": {"local:merchant": {}}},
                )
            )
            listing = engine.list_templates("entity")
            sources = {t["id"]: t["source"] for t in listing}
            assert sources == {"spawner_tmpl": "play", "local_tmpl": "local"}
            play_tmpl = next(t for t in listing if t["id"] == "spawner_tmpl")
            assert play_tmpl["data"]["components"] == {
                "local:spawner": {},
                "local:spawn": {"mob": "slime"},
            }
            assert "kind" not in play_tmpl["data"] and "tags" not in play_tmpl["data"]
            # 地块模板不会被 scope 过滤漏出来
            assert engine.list_templates("location") == []

            # 同名覆盖：本地优先
            await engine.save_template(
                WorldTemplate(
                    id="spawner_tmpl",
                    name="本地刷怪笼",
                    scope="entity",
                    data={"name": "本地刷怪笼"},
                )
            )
            merged = {t["id"]: t for t in engine.list_templates("entity")}
            assert merged["spawner_tmpl"]["source"] == "local"

            # 卸载玩法包 → 注册的模板消失，本地模板留下
            engine.clear_play_registrations("pkg_spawn")
            assert {t["id"] for t in engine.list_templates("entity")} == {
                "spawner_tmpl",
                "local_tmpl",
            }
            assert {t["source"] for t in engine.list_templates("entity")} == {"local"}
        finally:
            await engine.terminate()

    _run(fn())


def test_entity_template_payload_validated(tmp_path):
    """实体模板：data 必须是对象、components 必须是对象、scope 必须合法。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            with pytest.raises(WorldError, match="对象"):
                engine.register_entity_template("bad", "坏负载", ["x"])
            with pytest.raises(WorldError, match="components"):
                engine.register_entity_template(
                    "bad", "坏数据", {"name": "x", "components": []}
                )
            with pytest.raises(WorldError, match="scope"):
                await engine.save_template(
                    WorldTemplate(id="t", name="T", data={}, scope="whatever")
                )
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 管理端接线（组件选择器 / 实体组件编辑 / 模板） ----------


async def _admin_scenario(tmp_path: Path, fn):
    import httpx

    from worlditor_mcp.admin import build_admin_app
    from worlditor_mcp.world.identity import IdentityService

    engine = await _engine(tmp_path)
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
    app = build_admin_app(identity, engine=engine)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin"
        ) as client:
            info = await identity.register_human(
                "admin1", "pass123", admin_key="sekret"
            )
            headers = {"Authorization": f"Bearer {info.token}"}
            return await fn(client, headers, engine)
    finally:
        await engine.terminate()


def test_admin_kinds_lists_components(tmp_path):
    """GET /admin/kinds：**一张组件清单**（D41：不再分"类型 / 标签"两区）。"""

    async def fn(client, h, engine):
        engine.register_entity_kind(
            "door", interactions=("open",), label="木门", play_id="pkg_a"
        )
        engine.register_entity_tag(
            "spawner", label="刷怪笼", interactions=("tune",), play_id="pkg_b"
        )
        engine.declare_component("A", label="甲型", play_id="pkg_a")

        data = (await client.get("/admin/kinds", headers=h)).json()
        assert "types" not in data and "tags" not in data  # 旧两区已删
        assert {k["key"] for k in data["kinds"]} == {
            "pkg_a:door",
            "pkg_a:A",
            "pkg_b:spawner",
        }
        spawner = next(k for k in data["kinds"] if k["key"] == "pkg_b:spawner")
        assert spawner["source"] == "pkg_b" and spawner["name"] == "spawner"
        assert spawner["label"] == "刷怪笼"
        door = next(k for k in data["kinds"] if k["key"] == "pkg_a:door")
        assert door["interactions"] == ["open"]
        # D34：能力面不再透出 block_move（阻挡机制整体移除）
        assert all("block_move" not in k for k in data["kinds"])
        # 分类过滤（D10：categories 只作选取分组）
        engine.register_entity_kind("slime", label="史莱姆", categories=("生物",))
        filtered = (await client.get("/admin/kinds?category=生物", headers=h)).json()
        assert {k["key"] for k in filtered["kinds"]} == {"local:slime"}

    _run(_admin_scenario(tmp_path, fn))


def test_admin_entity_components_create_and_patch(tmp_path):
    """实体增改带 components（编辑器的组件编辑落点，D41）。"""

    async def fn(client, h, engine):
        r = await client.post(
            "/admin/entities",
            json={
                "kind": "player",
                "map_id": "default",
                "row": 0,
                "col": 0,
                "name": "小明",
                "tags": ["spawner", "spawner", ""],
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        entity_id = r.json()["data"]["id"]
        assert "local:spawner" in r.json()["data"]["components"]
        assert "tags" not in r.json()["data"]  # D41：投影里没有 tags
        assert engine.store.entities[entity_id].has_component("local:spawner")

        # 编辑器的写回是**读改写**：整块替换时要把 core:* 一起带上，否则实体
        # 会被搬出世界（`core:position` 没了 = 不在任何地块，D36 的合法状态）
        entity = engine.store.entities[entity_id]
        comps = {**entity.components, "local:a": {}, "local:b": {"n": 1}}
        comps.pop("local:spawner", None)
        r = await client.patch(
            f"/admin/entities/{entity_id}",
            json={"components": comps},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert "local:a" in r.json()["data"]["components"]
        stored = engine.store.entities[entity_id]
        assert stored.components["local:b"] == {"n": 1}
        assert not stored.has_component("local:spawner")  # 显式摘掉的能力组件

        # 详情里带上组件与合并能力（编辑器展示用）
        detail = (await client.get("/admin/maps/default", headers=h)).json()
        row = next(e for e in detail["entities"] if e["id"] == entity_id)
        assert "local:a" in row["components"]
        assert set(row["capabilities"]) == {
            "components",
            "active_components",
            "inactive_components",
            "orphan_components",
            "fictional_components",
            "interactions",
            "fields",
        }
        assert set(row["capabilities"]["components"]) == set(row["components"])
        assert "local:a" in row["capabilities"]["fictional_components"]  # 未声明 = 虚构

    _run(_admin_scenario(tmp_path, fn))


def test_admin_template_scope_apply_and_entity_sources(tmp_path):
    """模板接口：scope 过滤 / 套用地块模板 / 实体模板两种来源。"""

    async def fn(client, h, engine):
        r = await client.post(
            "/admin/templates",
            json={
                "id": "room",
                "name": "小房间",
                "scope": "location",
                "data": {
                    "name": "客房",
                    "connections": {
                        "up": {
                            "enabled": True,
                            "paths": [{"targets": [{"dr": -1, "dc": 0}]}],
                        }
                    },
                },
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["scope"] == "location"

        lst = (await client.get("/admin/templates?scope=location", headers=h)).json()
        assert [t["id"] for t in lst["templates"]] == ["room"]
        assert (await client.get("/admin/templates?scope=entity", headers=h)).json()[
            "templates"
        ] == []

        # 套用到 (4, 4)：同图目标平移成 (3, 4)
        r = await client.post(
            "/admin/templates/apply",
            json={"template_id": "room", "map_id": "default", "row": 4, "col": 4},
            headers=h,
        )
        assert r.status_code == 200, r.text
        loc = engine.get_location("default", 4, 4)
        assert loc.name == "客房"
        assert (loc.connections["up"].paths[0].targets[0].row) == 3
        # 再次套用同一格 → 拒绝
        r = await client.post(
            "/admin/templates/apply",
            json={"template_id": "room", "map_id": "default", "row": 4, "col": 4},
            headers=h,
        )
        assert r.status_code == 400, r.text

        # 实体模板：包注册（内存）+ 本地（落库）合并，scope 过滤生效
        engine.register_entity_template(
            "spawner_tmpl",
            "刷怪笼",
            {"components": {"local:spawner": {}}},
            play_id="pkg_spawn",
        )
        r = await client.post(
            "/admin/templates",
            json={
                "id": "local",
                "name": "本地商贩",
                "scope": "entity",
                "data": {"name": "商贩", "components": {"local:merchant": {}}},
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        lst = (await client.get("/admin/templates?scope=entity", headers=h)).json()
        assert {t["source"] for t in lst["templates"]} == {"play", "local"}
        assert {t["id"] for t in lst["templates"]} == {"spawner_tmpl", "local"}

    _run(_admin_scenario(tmp_path, fn))


def test_admin_lint_world_filter(tmp_path):
    """lint 的世界过滤（X4：世界页只需要本世界的，别全量白算）。"""

    async def fn(client, h, engine):
        await engine.create_world("w_a", "甲世界")
        await engine.create_map("m_a", "甲图", spawn_row=9, spawn_col=9)
        await engine.create_location("m_a", 0, 0, "孤岛")
        await engine.assign_map("m_a", "w_a")
        await engine.assign_map("default", "default")

        data = (await client.get("/admin/lint?world_id=w_a", headers=h)).json()
        assert [m["map_id"] for m in data["maps"]] == ["m_a"]
        assert data["counts"]["error"] >= 1
        # 未归属世界的地图算在默认世界里（与激活过滤同源）
        await engine.create_map("orphan", "孤儿图")
        data = (await client.get("/admin/lint?world_id=default", headers=h)).json()
        assert {m["map_id"] for m in data["maps"]} == {"default", "orphan"}

    _run(_admin_scenario(tmp_path, fn))
