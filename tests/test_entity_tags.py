"""实体标签体系（v0.5 / D18–D21 / D25）：能力由标签承载，类型退化为预设标志位。

回归背景：v0.4 之前 `entities.kind` 是**单值**且身兼三职——身份（IDENTITY_KINDS）、
行为声明（block_move/interactions）、字段 schema 归属——"组合"在库层面存不下。
本模块守住 D18–D21 的语义：

1. `register_entity_kind` = 语法糖，注册一条**隐式同名标签**（旧包/旧测试零改动）
2. 实例 `tags[]` 与类型预设标签一起参与能力**并集**（"玩家 + 刷怪笼"成立）
3. `block_move` 任一为真即阻挡；`interactions` 并集；字段顺序 = 标签序 → 分类最后
4. 身份判定**只看基底 kind**（标签里写 player 不算数）
5. 能力面**逐标签**按世界激活过滤；未注册标签无能力贡献但实体照常存在
6. 规格级缓存随注册表变动失效
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from world_fixtures import seed_test_world

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import TagSpec, WorldTemplate, parse_tags
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


# ---------- D18：kind = 隐式同名标签 ----------


def test_kind_registration_is_implicit_tag(tmp_path):
    """register_entity_kind 写出来的是 implicit=True 的标签；能力照旧生效。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_kind(
                "door", block_move=True, interactions=("open",), label="木门"
            )
            spec = engine._tag_specs["door"]
            assert isinstance(spec, TagSpec) and spec.implicit is True
            listing = engine.list_kinds()
            door = next(k for k in listing if k["tag"] == "door")
            assert door["implicit"] is True
            assert door["block_move"] is True
            assert door["interactions"] == ["open"]
            assert door["label"] == "木门"

            # 老写法：只给 kind，能力与 v0.4 完全一致
            door_entity = await engine.place_entity("door", "default", 0, 0)
            assert door_entity.name == "木门"  # 默认名仍取 label
            assert engine.capabilities(door_entity)["block_move"] is True
        finally:
            await engine.terminate()

    _run(fn())


def test_explicit_tag_registration_marks_non_implicit(tmp_path):
    """register_entity_tag 注册的标签 implicit=False，可与类型区分展示。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("spawner", label="刷怪笼", block_move=True)
            listing = {k["tag"]: k for k in engine.list_kinds()}
            assert listing["spawner"]["implicit"] is False
            assert listing["spawner"]["label"] == "刷怪笼"
        finally:
            await engine.terminate()

    _run(fn())


def test_composition_player_plus_spawner(tmp_path):
    """组合：玩家基底 + 刷怪笼标签 → 两边能力同时生效（用户的核心设想）。"""

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
            assert caps["tags"] == ["player", "spawner"]
            # player 没有注册过规格（身份由基底 kind 表达，D20）→ 只有 spawner 在贡献
            assert caps["active_tags"] == ["spawner"]
            assert caps["unknown_tags"] == ["player"]
            assert "tune" in caps["interactions"]
            assert "tune" in engine.available_actions(player.id)
            assert {f["name"] for f in caps["fields"]} == {"mob"}
            # 身份仍是玩家（D20：只看基底 kind）
            assert player.is_identity() is True
        finally:
            await engine.terminate()

    _run(fn())


def test_type_preset_tags(tmp_path):
    """类型 = 标签预设："类型 A = {A, C}"、"类型 B = {B, C}"（用户原话）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("a", label="能力甲")
            engine.register_entity_tag("b", label="能力乙")
            engine.register_entity_tag("c", label="公共能力", interactions=("ping",))
            engine.register_interaction("ping", _noop_handler, label="ping")
            # 类型 A 自带 A、C；类型 B 自带 B、C（用户原话："A 有 A 和 C，B 有 B 和 C"）
            engine.register_entity_type("A", tags=["c"], label="甲型")
            engine.register_entity_type("B", tags=["c"], label="乙型")

            a = await engine.place_entity("A", "default", 0, 0)
            b = await engine.place_entity("B", "default", 0, 1)
            assert engine.entity_tags(a) == ["A", "c"]
            assert engine.entity_tags(b) == ["B", "c"]
            # 公共能力 c 同时作用于两种类型
            assert engine.capabilities(a)["interactions"] == ["ping"]
            assert engine.capabilities(b)["interactions"] == ["ping"]
            # list_kinds 暴露预设标签，编辑器可据此展示"选 A 即得 A+C"
            listing = {k["tag"]: k for k in engine.list_kinds()}
            assert listing["A"]["preset_tags"] == ["c"]
            assert listing["B"]["preset_tags"] == ["c"]
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D19：并集与冲突规则 ----------


def test_block_move_any_true_wins_and_state_overrides(tmp_path):
    """block_move：任一标签为真即阻挡；state["block_move"] 仍是最高的动态覆盖。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("soft", block_move=False, label="软")
            engine.register_entity_tag("hard", block_move=True, label="硬")
            both = await engine.place_entity(
                "rock", "default", 0, 0, tags=["soft", "hard"]
            )
            assert engine.capabilities(both)["block_move"] is True
            assert engine._is_blocking(both) is True

            # 玩法包动态改 state 可以推翻静态声明（门开/关的老语义）
            await engine.set_state(both.id, {"block_move": False})
            assert engine._is_blocking(both) is False
        finally:
            await engine.terminate()

    _run(fn())


def test_fields_merge_order_tags_then_category(tmp_path):
    """字段覆盖顺序：隐式 kind 标签 → 实例 tags（数组序）→ 分类字段（最后）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg")
            engine.attach_play_api("pkg", api)
            api.register_entity_kind(
                "base",
                fields=[{"name": "x", "type": "str", "default": "kind"}],
                categories=("生物",),
            )
            api.register_entity_tag(
                "t1", fields=[{"name": "x", "type": "str", "default": "t1"}]
            )
            api.register_entity_tag(
                "t2", fields=[{"name": "x", "type": "str", "default": "t2"}]
            )
            api.add_category_fields(
                "生物", [{"name": "x", "type": "str", "default": "cat"}]
            )
            api.add_category_fields("生物", [{"name": "aggro", "type": "bool"}])

            e = await engine.place_entity("base", "default", 0, 0, tags=["t1", "t2"])
            fields = {f["name"]: f for f in engine.capabilities(e)["fields"]}
            assert fields["aggro"]["type"] == "bool"  # 分类字段仍在
            # 分类字段最后应用 → 覆盖标签字段
            assert fields["x"]["default"] == "cat"
            # 换顺序：实例标签在分类之后无法覆盖（顺序语义稳定可复现）
            assert (
                engine.effective_fields_for(["base", "t1", "t2"])[0]["default"] == "cat"
            )

            # 单个标签查询（老 API）行为不变
            assert engine.effective_fields("base")[0]["default"] == "cat"
            assert engine.effective_fields("t1")[0]["default"] == "t1"
        finally:
            await engine.terminate()

    _run(fn())


def test_add_tag_fields_applies_to_entities_carrying_the_tag(tmp_path):
    """D18 语义扩张：add_tag_fields 影响**所有带该标签的实体**，不再只看 kind 相等。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = WorlditorPlayAPI(engine, "pkg")
            engine.attach_play_api("pkg", api)
            api.register_entity_kind("monster", fields=[{"name": "hp", "type": "int"}])
            api.register_entity_kind("slime", fields=[{"name": "goo", "type": "int"}])
            # 老写法：给 monster 追加字段
            api.add_kind_fields("monster", [{"name": "poison", "type": "bool"}])

            tagged = await engine.place_entity(
                "slime", "default", 0, 0, tags=["monster"]
            )
            plain = await engine.place_entity("slime", "default", 0, 1)
            # 挂上 monster 标签 = 同时获得 monster 自身的声明字段与追加字段（并集）
            assert {f["name"] for f in engine.capabilities(tagged)["fields"]} == {
                "goo",
                "hp",
                "poison",
            }
            assert {f["name"] for f in engine.capabilities(plain)["fields"]} == {"goo"}
        finally:
            await engine.terminate()

    _run(fn())


def test_unregistered_tag_is_harmless(tmp_path):
    """允许未注册标签：实体照常存在，标签不贡献能力（编辑器可手输）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity(
                "rock", "default", 0, 0, tags=["nobody_knows"]
            )
            caps = engine.capabilities(e)
            assert caps["tags"] == ["rock", "nobody_knows"]
            assert caps["active_tags"] == []  # rock 未注册、nobody_knows 未注册
            assert caps["block_move"] is False
            assert caps["fields"] == []
            assert engine.capabilities(e)["interactions"] == []
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D20：身份只看基底 kind ----------


def test_identity_ignores_tags(tmp_path):
    """标签里写 player 不改变身份；基底 kind=player 才是身份化实体（D20）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            npc = await engine.place_entity("npc", "default", 0, 0, tags=["player"])
            assert npc.is_identity() is False
            player = await engine.place_entity(
                "player", "default", 0, 1, tags=["stone"]
            )
            assert player.is_identity() is True
            # 身份保护不看标签：kind=npc 的实体照样可被玩法包移除
            await engine.remove_entity(npc.id)
            assert engine.store.entities.get(npc.id) is None
            # 反之 kind=player 即便挂了别的标签也拒绝移除
            with pytest.raises(WorldError, match="身份化实体"):
                await engine.remove_entity(player.id)
        finally:
            await engine.terminate()

    _run(fn())


# ---------- D21：逐标签世界激活过滤 + 缓存 ----------


def test_tag_capability_filtered_by_world_activation(tmp_path):
    """标签所属包在实体所在世界未激活 → 该标签不参与并集。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_tag("spawner", block_move=True, play_id="pkg_b")
            await engine.create_world("w_a", "只有A", play_ids=["pkg_a"])
            await engine.create_world("w_b", "有B", play_ids=["pkg_b"])
            await engine.create_map("m_a", "甲图")
            await engine.create_location("m_a", 0, 0, "格")
            await engine.assign_map("m_a", "w_a")
            e = await engine.place_entity("slime", "m_a", 0, 0, tags=["spawner"])

            caps = engine.capabilities(e)
            assert caps["tags"] == ["slime", "spawner"]
            assert caps["active_tags"] == []  # pkg_b 不在 w_a
            assert caps["block_move"] is False

            await engine.assign_map("m_a", "w_b")
            caps = engine.capabilities(e)
            assert caps["active_tags"] == ["spawner"]
            assert caps["block_move"] is True
        finally:
            await engine.terminate()

    _run(fn())


def test_spec_cache_invalidated_when_tag_registered_later(tmp_path):
    """规格级缓存：注册表变动后，先前算过的 (kind, tags) 必须重算。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity("slime", "default", 0, 0, tags=["late"])
            assert engine.capabilities(e)["block_move"] is False  # late 还没注册
            engine.register_entity_tag("late", block_move=True)
            assert engine.capabilities(e)["block_move"] is True  # 缓存已失效
            # 卸载包后回到未注册状态，能力随之消失
            engine.register_entity_tag("late2", block_move=True, play_id="pkg_x")
            e2 = await engine.place_entity("slime", "default", 0, 1, tags=["late2"])
            assert engine.capabilities(e2)["block_move"] is True
            engine.clear_play_registrations("pkg_x")
            assert engine.capabilities(e2)["block_move"] is False
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 持久化与解析 ----------


def test_tags_persist_and_parse_rules(tmp_path):
    """标签落库并跨引擎重开保留；解析去重保序、丢弃非字符串。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity(
                "player", "default", 0, 0, name="小明", tags=["b", "a", "b", "", 7]
            )
            assert e.tags == ["b", "a"]
        finally:
            await engine.terminate()
        again = WorldEngine(WorldStore(tmp_path / "world.db"))
        await again.initialize()
        try:
            stored = next(iter(again.store.entities.values()))
            assert stored.tags == ["b", "a"]
            assert stored.to_dict()["tags"] == ["b", "a"]
        finally:
            await again.terminate()

    _run(fn())


def test_parse_tags_helper():
    assert parse_tags("solo") == ["solo"]
    assert parse_tags([" a ", "a", "", None, 3, "b"]) == ["a", "b"]
    assert parse_tags(None) == []
    assert parse_tags({"a": 1}) == []


def test_update_entity_replaces_tags(tmp_path):
    """PATCH 语义：tags 整体替换（同 attrs/state）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            e = await engine.place_entity("rock", "default", 0, 0, tags=["x"])
            await engine.update_entity(e.id, tags=["y", "z"])
            assert e.tags == ["y", "z"]
            await engine.update_entity(e.id, tags=None)
            assert e.tags == []
            with pytest.raises(WorldError, match="tags 必须是标签数组"):
                await engine.update_entity(e.id, tags="not-a-list")
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
                        "description": "一间安静的客房。",
                        "connections": {
                            "up": {
                                "enabled": True,
                                "paths": [
                                    {
                                        "label": "往北",
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
    """实体模板：玩法包注册（内存）+ 管理端本地（落库）合并；同名本地优先。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.register_entity_template(
                "spawner_tmpl",
                "刷怪笼",
                {"kind": "spawner", "tags": ["strong"], "attrs": {"mob": "slime"}},
                play_id="pkg_spawn",
            )
            await engine.save_template(
                WorldTemplate(
                    id="local_tmpl",
                    name="本地商贩",
                    scope="entity",
                    data={"kind": "merchant", "name": "商贩"},
                )
            )
            listing = engine.list_templates("entity")
            sources = {t["id"]: t["source"] for t in listing}
            assert sources == {"spawner_tmpl": "play", "local_tmpl": "local"}
            play_tmpl = next(t for t in listing if t["id"] == "spawner_tmpl")
            assert play_tmpl["data"]["tags"] == ["strong"]
            assert play_tmpl["data"]["attrs"] == {"mob": "slime"}
            # 地块模板不会被 scope 过滤漏出来
            assert engine.list_templates("location") == []

            # 同名覆盖：本地优先
            await engine.save_template(
                WorldTemplate(
                    id="spawner_tmpl",
                    name="本地刷怪笼",
                    scope="entity",
                    data={"kind": "spawner"},
                )
            )
            merged = {t["id"]: t for t in engine.list_templates("entity")}
            assert merged["spawner_tmpl"]["source"] == "local"

            # 卸载玩法包 → 注册的模板消失，本地模板留下
            engine.clear_play_registrations("pkg_spawn")
            left = [t["id"] for t in engine.list_templates("entity")]
            assert left == ["spawner_tmpl", "local_tmpl"]
            assert {t["source"] for t in engine.list_templates("entity")} == {"local"}
        finally:
            await engine.terminate()

    _run(fn())


def test_entity_template_payload_validated(tmp_path):
    """实体模板必须给 kind；attrs/state 必须是对象；scope 必须合法。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            with pytest.raises(WorldError, match="kind"):
                engine.register_entity_template("bad", "无类型", {"tags": ["x"]})
            with pytest.raises(WorldError, match="attrs"):
                engine.register_entity_template(
                    "bad", "坏数据", {"kind": "x", "attrs": []}
                )
            with pytest.raises(WorldError, match="scope"):
                await engine.save_template(
                    WorldTemplate(id="t", name="T", data={}, scope="whatever")
                )
        finally:
            await engine.terminate()

    _run(fn())


async def _noop_handler(api, req):  # pragma: no cover - 仅用于注册动作
    from worlditor_mcp.world.model import InteractionResult

    return InteractionResult(text="ok")


# ---------- 管理端接线（编辑器下拉/标签勾选/模板的数据源） ----------


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


def test_admin_kinds_lists_types_and_tags(tmp_path):
    """GET /admin/kinds：类型与标签分列，带来源包、是否隐式、预设标签。"""

    async def fn(client, h, engine):
        engine.register_entity_kind(
            "door", block_move=True, label="木门", play_id="pkg_a"
        )
        engine.register_entity_tag(
            "spawner", label="刷怪笼", interactions=("tune",), play_id="pkg_b"
        )
        engine.register_entity_type(
            "A", tags=["spawner"], label="甲型", play_id="pkg_a"
        )

        data = (await client.get("/admin/kinds", headers=h)).json()
        assert {k["tag"] for k in data["types"]} == {"door", "A"}
        assert {k["tag"] for k in data["tags"]} == {"spawner"}
        spawner = next(k for k in data["tags"] if k["tag"] == "spawner")
        assert spawner["play_id"] == "pkg_b"
        assert spawner["implicit"] is False
        assert spawner["label"] == "刷怪笼"
        a_type = next(k for k in data["types"] if k["tag"] == "A")
        assert a_type["preset_tags"] == ["spawner"]
        # 分类过滤（D10）
        engine.register_entity_kind("slime", label="史莱姆", categories=("生物",))
        filtered = (await client.get("/admin/kinds?category=生物", headers=h)).json()
        assert {k["tag"] for k in filtered["kinds"]} == {"slime"}

    _run(_admin_scenario(tmp_path, fn))


def test_admin_entity_tags_create_and_patch(tmp_path):
    """实体增改带 tags（编辑器标签勾选的落点）。"""

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
        assert r.json()["data"]["tags"] == ["spawner"]  # 去重去空

        r = await client.patch(
            f"/admin/entities/{entity_id}", json={"tags": ["a", "b"]}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["tags"] == ["a", "b"]
        assert engine.store.entities[entity_id].tags == ["a", "b"]

        # 详情里带上标签与合并能力（编辑器展示用）
        detail = (await client.get("/admin/maps/default", headers=h)).json()
        row = next(e for e in detail["entities"] if e["id"] == entity_id)
        assert row["tags"] == ["a", "b"]

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
            "spawner_tmpl", "刷怪笼", {"kind": "spawner"}, play_id="pkg_spawn"
        )
        r = await client.post(
            "/admin/templates",
            json={
                "id": "local",
                "name": "本地商贩",
                "scope": "entity",
                "data": {"kind": "merchant"},
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
