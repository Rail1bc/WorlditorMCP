"""实体模型 v2 的**结构性守卫**（D32–D37）：信封 / 内核保留命名空间 / 已移除面。

为什么单开一个文件：这些断言守的是"**内核不该有的东西真的不在**"（移除面）与
"组件信封的规则"，它们不属于任何单点功能，散落在业务测试里迟早被顺手删掉。
`.uitools/` 里那份等价的冒烟脚本**不入库**，所以这里固化为 CI 覆盖。

对应决策：D32（实体 = id + 组件）/ D33（信封与 core: 保留）/ D34（阻挡移除）/
D37（内核移除物品）。见 DESIGN §12。
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import (  # noqa: E402
    OVERRIDABLE_PRIMITIVES,
    WorldEngine,
    WorldError,
)
from worlditor_mcp.world.errors import IncompatibleDataError  # noqa: E402
from worlditor_mcp.world.model import (  # noqa: E402
    CORE_ACCOUNT,
    CORE_INFO,
    CORE_PERCEPTION,
    CORE_POSITION,
    WORLD_EVENTS,
    Entity,
    InteractionRequest,
    is_core_component,
    parse_components,
    split_component_key,
)
from worlditor_mcp.world.play.api import WorlditorPlayAPI  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ---------- 组件信封（D33） ----------

_INVALID_KEYS = [
    "box",  # 没有冒号——信封必填，无例外
    "local:",  # 缺名字
    ":box",  # 缺来源
    "a:b:c",  # name 里又有冒号（字符集不允许）
    "local:含中文",  # 非法字符
    "",  # 空
    "local:has space",  # 空格
]


def test_component_key_envelope():
    """组件名 = ``source:name``：合法形态通过，非法形态**报错**（不静默兜底）。"""
    for key in _INVALID_KEYS:
        with pytest.raises(WorldError):
            split_component_key(key)
    for key in ("core:perception", "local:stat", "worlditor_play_x:merchant", "a:b"):
        assert split_component_key(key) == tuple(key.split(":", 1))
    # 信封判定的边界：只有 `core:` 前缀算内核保留
    assert is_core_component("core:perception") is True
    assert is_core_component("corestate") is False
    assert is_core_component("local:core") is False
    assert is_core_component(None) is False

    # 容错解析（存储/传输路径）：非法键与非对象值被丢弃，合法条目保留
    assert parse_components({"ok:x": {"a": 1}, "bad": {"b": 2}, "ok:y": "非对象"}) == {
        "ok:x": {"a": 1}
    }
    assert parse_components("不是 dict") == {}


def test_play_api_cannot_write_core_but_engine_can(tmp_path):
    """``core:`` 是内核保留命名空间：玩法包写入报错，引擎层放行（D33）。"""

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            e = await engine.place_entity("thing", "default", 0, 0, name="箱子")
            api = WorlditorPlayAPI(engine, "worlditor_play_probe")

            with pytest.raises(WorldError, match="内核保留"):
                await api.set_data(e.id, "x", 1, component=CORE_PERCEPTION)
            with pytest.raises(WorldError, match="内核保留"):
                await api.add_component(e.id, "core:x", {})
            with pytest.raises(WorldError, match="内核保留"):
                await api.set_component(e.id, "core:x", {})
            with pytest.raises(WorldError, match="内核保留"):
                await api.remove_component(e.id, CORE_PERCEPTION)

            # 引擎层（内核自己 / 管理端）可以写
            await engine.set_data(e.id, "invisible", True, component=CORE_PERCEPTION)
            assert engine.get_component(e.id, CORE_PERCEPTION) == {"invisible": True}
            # 读不受限
            assert api.get_component(e.id, CORE_PERCEPTION) == {"invisible": True}
            assert CORE_PERCEPTION in api.list_components(e.id)

            # 规则不放宽、能力不丢失（§12.2）：`core:` 直写照样拒绝，但"本来就是玩法包
            # 正当能力"的协议字段走**窄口受控入口**——两个：感知、位置（离开世界）。
            # 少一个就是把玩法包的能力吃掉：位置一旦可选，"下线"却是单向门。
            assert hasattr(api, "set_perception") and hasattr(api, "clear_position")
            assert hasattr(engine, "set_perception") and hasattr(
                engine, "clear_position"
            )
            for banned in (CORE_POSITION, CORE_PERCEPTION):
                with pytest.raises(WorldError, match="内核保留"):
                    await api.set_component(e.id, banned, {})
        finally:
            await engine.terminate()

    _run(fn())


def test_component_write_primitives_are_dispatchable():
    """组件写入进分派表（可覆盖/禁用），只读的不进（D26 口径）。"""
    for name in ("add_component", "set_component", "remove_component"):
        assert name in OVERRIDABLE_PRIMITIVES
    for name in ("get_component", "list_components"):
        assert name not in OVERRIDABLE_PRIMITIVES


# ---------- D41-a：组件声明与裸名解析 ----------


def test_d41_component_keys_resolve_and_coexist(tmp_path):
    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        await seed_test_world(engine)
        try:
            engine.register_entity_tag("merchant", play_id="pkg_a")
            merchant = await engine.place_entity("merchant", "default", 0, 0)
            assert merchant.kind == "pkg_a:merchant"
            assert engine.entity_tags(merchant) == ["pkg_a:merchant"]

            engine.register_entity_tag("merchant", play_id="pkg_b")
            with pytest.raises(WorldError, match="多个声明者"):
                await engine.place_entity("merchant", "default", 0, 1)
            qualified = await engine.place_entity("pkg_b:merchant", "default", 0, 1)
            assert qualified.kind == "pkg_b:merchant"
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 已移除面（D34 / D37 / D42）：防止静默回归 ----------


def test_identity_concept_is_gone():
    """D42：内核**没有"身份"这个概念**——相关符号与闸门全部不存在。

    红线没有消失，只是换了判据：**绑定了账户的实体（`core:account`）不可被移除**。
    这条守卫盯的是"身份"这个名字有没有偷偷长回来（它承载过 `kind == "player"`）。
    """
    import worlditor_mcp.world.model as model_mod

    for gone in ("IDENTITY_KINDS",):
        assert not hasattr(model_mod, gone), f"{gone} 应已随 D42 移除"
    assert not hasattr(Entity, "is_identity"), "is_identity 应已换名 is_account_bound"
    assert hasattr(Entity, "is_account_bound")
    assert not hasattr(WorldEngine, "delete_identity_entity"), (
        "应已换名 delete_account_entity"
    )
    assert hasattr(WorldEngine, "delete_account_entity")


def test_play_cannot_write_other_plays_namespace(tmp_path):
    """D43：组件命名空间即写入边界——写**别人的** `<play_id>:` 报错。

    `core:` 的保护从第 1 期就有（D33）；D43 把同一条道理推广到玩法包之间：
    包名写在键里就该是真规则，不能只是"命名约定"。`local:` **暂不收紧**（D43）。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            e = await engine.place_entity("thing", "default", 0, 0, name="箱子")
            api = WorlditorPlayAPI(engine, "worlditor_play_probe")

            # 别人的命名空间 → 拒（四条写入路径都要拦）
            for call in (
                api.set_data(e.id, "x", 1, component="worlditor_play_other:stat"),
                api.add_component(e.id, "worlditor_play_other:stat", {}),
                api.set_component(e.id, "worlditor_play_other:stat", {}),
                api.remove_component(e.id, "worlditor_play_other:stat"),
                api.place_entity(
                    "thing", components={"worlditor_play_other:stat": {"x": 1}}
                ),
            ):
                with pytest.raises(WorldError, match="别的玩法包"):
                    await call

            # 自己的命名空间 → 放行
            await api.set_data(e.id, "hp", 3, component="worlditor_play_probe:stat")
            assert engine.get_component(e.id, "worlditor_play_probe:stat") == {"hp": 3}
            # local: 暂不收紧（夹具与文档例子都在写它）→ 放行
            await api.set_data(e.id, "gold", 1, component="local:stat")
            assert engine.get_component(e.id, "local:stat") == {"gold": 1}
            # core: 一如既往拒（D33 不变）
            with pytest.raises(WorldError, match="内核保留"):
                await api.set_component(e.id, CORE_INFO, {"name": "x"})
        finally:
            await engine.terminate()

    _run(fn())


def test_blocking_mechanism_is_gone():
    """D34：阻挡机制整体移除——所有实体都不阻挡，相关符号不存在。"""
    import worlditor_mcp.world.engine as engine_mod
    import worlditor_mcp.world.model as model_mod

    for gone in ("_is_blocking", "_blocker_at"):
        assert not hasattr(WorldEngine, gone), f"{gone} 应已随 D34 移除"
    for gone in ("STATE_BLOCK_MOVE", "CORE_STATE"):
        assert not hasattr(model_mod, gone), f"{gone} 应已随 D34 移除"
    assert not hasattr(model_mod.TagSpec, "block_move")
    assert not hasattr(engine_mod, "STATE_BLOCK_MOVE")
    # 注册入口不再接受 block_move（传了就该报 TypeError，而不是被静默忽略）
    assert (
        "block_move"
        not in inspect.signature(WorldEngine.register_entity_kind).parameters
    )
    assert (
        "block_move"
        not in inspect.signature(WorldEngine.register_entity_tag).parameters
    )


def test_items_are_gone_from_kernel(tmp_path):
    """D37：内核移除物品——表、内存表、API、事件、交互槽位都不该还在。"""
    import worlditor_mcp.world as world_pkg
    import worlditor_mcp.world.model as model_mod

    # 符号面
    assert not hasattr(world_pkg, "ItemDef")
    for gone in ("ItemDef", "item_db_row", "item_from_row"):
        assert not hasattr(model_mod, gone), f"{gone} 应已随 D37 移除"
    for gone in (
        "register_item_def",
        "save_item_def",
        "add_item_fields",
        "get_item_def",
        "list_item_defs",
        "delete_item_def",
        "flush_item_defs",
    ):
        assert not hasattr(WorldEngine, gone), f"引擎 {gone} 应已随 D37 移除"
        assert not hasattr(WorlditorPlayAPI, gone), f"玩法包 API {gone} 应已随 D37 移除"

    # 事件面：内核事件 7 个，不再有 on_item_used
    assert "on_item_used" not in WORLD_EVENTS
    assert len(WORLD_EVENTS) == 7

    # 交互面：item_id 槽位已删（物品标识放 args）
    assert "item_id" not in InteractionRequest.__dataclass_fields__
    assert "item_id" not in inspect.signature(WorldEngine.interact).parameters
    assert "item_id" not in inspect.signature(WorlditorPlayAPI.interact).parameters

    # 存储面：新库**不建 items 表**
    async def fn():
        db = tmp_path / "world.db"
        engine = WorldEngine(WorldStore(db))
        await engine.initialize()
        try:
            assert not hasattr(engine.store, "items")
            tables = {
                row[0]
                for row in sqlite3.connect(db).execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "items" not in tables
        finally:
            await engine.terminate()

    _run(fn())


def test_item_type_is_now_a_component_declaration(tmp_path):
    """D37 的替代路径**真的可用**：物品类型 = 组件声明（名字 + 字段 schema + 归属）。

    这条守住"下沉"不是"删掉了事"——玩法包声明一个组件类型，它就该出现在
    类型清单里并带字段 schema，与原来的物品定义等价可用。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            api = WorlditorPlayAPI(engine, "worlditor_play_food")
            api.register_entity_tag(
                "apple",
                label="苹果",
                fields=[{"name": "heal", "label": "回复", "type": "int", "default": 3}],
            )
            row = next(
                k for k in api.list_kinds() if k["tag"] == "worlditor_play_food:apple"
            )
            assert row["label"] == "苹果"
            assert [f["name"] for f in row["fields"]] == ["heal"]
            assert row["play_id"] == "worlditor_play_food"  # 归属仍在（卸载可清）
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 名字 / 描述 / 账户绑定也是组件（D32 §12.4） ----------


def test_info_and_account_are_components(tmp_path):
    """``name`` / ``desc`` / ``user_id`` 是 ``core:info`` / ``core:account``，不是特权字段。

    守住三件事：① 线上投影（``to_dict``）不在顶层给它们；② 落库表没有那三列；
    ③ ``name`` 缺失时兜底 ``id`` 前 8 位（§12.4 的缺失语义）。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            e = await engine.place_entity(
                "npc", "default", 0, 0, name="阿福", desc="胖商贩", user_id="acct_1"
            )
            assert engine.get_component(e.id, CORE_INFO) == {
                "name": "阿福",
                "desc": "胖商贩",
            }
            assert engine.get_component(e.id, CORE_ACCOUNT) == {"user_id": "acct_1"}
            assert e.name == "阿福" and e.desc == "胖商贩" and e.user_id == "acct_1"

            top = e.to_dict()
            for gone in ("name", "desc", "user_id", "map_id", "row", "col"):
                assert gone not in top, f"to_dict 顶层不该再有 {gone}（它在组件里）"
            assert engine.get_component(e.id, CORE_POSITION) == {
                "map_id": "default",
                "row": 0,
                "col": 0,
            }

            # 缺 core:info → name 兜底 id 前 8 位、desc 空
            bare = Entity(id="0123456789abcdef", kind="npc")
            assert bare.name == "01234567"
            assert bare.desc == ""
            assert bare.user_id is None
            assert bare.pos_key() is None  # 也没有位置 = 不在世界上

            # 改名不碰同一组件下的其它键（不静默丢数据）
            await engine.set_data(e.id, "extra", "keep", component=CORE_INFO)
            await engine.update_entity(e.id, name="阿福二世")
            assert engine.get_component(e.id, CORE_INFO) == {
                "name": "阿福二世",
                "desc": "胖商贩",
                "extra": "keep",
            }

            # 落库表没有那三列
            tables = {
                row[0]
                for row in sqlite3.connect(tmp_path / "world.db").execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "entities" in tables
            cols = {
                r[1]
                for r in sqlite3.connect(tmp_path / "world.db").execute(
                    "PRAGMA table_info(entities)"
                )
            }
            for gone in (
                "name",
                "desc",
                "user_id",
                "map_id",
                "row",
                "col",
                "attrs_json",
                "state_json",
            ):
                assert gone not in cols, f"entities 表不该再有 {gone} 列（v10 形态）"
        finally:
            await engine.terminate()

    _run(fn())


async def _columns(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_schema_gate_agrees_with_ddl(tmp_path):
    """版本闸的清单必须与本版本 DDL **自洽**——否则闸本身就成了新的静默缺陷。

    要守三条（都是"闸与 DDL 互相矛盾"这类人工很难发现的问题）：
    1. 每个「需要的列」在**全新库**里真的存在（否则新库一启动就被自己拒绝）；
    2. 每个「不该存在的列」在全新库里**确实不在**（否则新库同样被自己拒绝）；
    3. 两个清单**不重叠**（同一列既要求存在又要求不存在 = 无解）。

    真实经历：实体列形态改了两次（v8 换容器、v9 去掉 name/desc/user_id），
    "查缺列"与"查多余列"是分两次补上的，每次都得手工核对 DDL 才敢下结论——
    这条守卫就是为那次手工核对留下的。
    """
    from worlditor_mcp.world.store import (
        _FORBIDDEN_COLUMNS,
        _REQUIRED_COLUMNS,
        SCHEMA_VERSION,
    )

    for table in set(_REQUIRED_COLUMNS) & set(_FORBIDDEN_COLUMNS):
        overlap = set(_REQUIRED_COLUMNS[table]) & set(_FORBIDDEN_COLUMNS[table])
        assert not overlap, f"{table} 的列同时出现在两个清单里：{overlap}"

    async def fn():
        db = tmp_path / "world.db"
        store = WorldStore(db)
        await store.initialize()
        try:
            assert store.world_meta.get("schema_version") == SCHEMA_VERSION
            for table, columns in _REQUIRED_COLUMNS.items():
                actual = await _columns(db, table)
                for col in columns:
                    assert col in actual, (
                        f"{table}.{col} 在需要清单里，但新库没有这一列"
                    )
            for table, columns in _FORBIDDEN_COLUMNS.items():
                actual = await _columns(db, table)
                for col in columns:
                    assert col not in actual, (
                        f"{table}.{col} 在不该存在清单里，但新库 DDL 却建了它"
                        f"——闸会把全新库也拒掉"
                    )
        finally:
            await store.close()

    _run(fn())


def test_stale_entity_columns_are_refused(tmp_path):
    """带 v9 之前那三列的库要被**拒绝**，而不是"载入成功但名字被静默丢掉"。

    这是版本闸的第二半：只查"需要的列在不在"查不出**多出来的旧列**，
    而多出来的旧列意味着数据还在老位置——载入会成功，名字/描述/账户绑定直接消失。
    """

    db = tmp_path / "world.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE world_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, map_id TEXT NOT NULL, row INTEGER NOT NULL,
            col INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
            desc TEXT NOT NULL DEFAULT '', user_id TEXT,
            components_json TEXT NOT NULL DEFAULT '{}',
            last_active_ts REAL NOT NULL DEFAULT 0,
            tags_json TEXT NOT NULL DEFAULT '[]',
            revision INTEGER NOT NULL DEFAULT 0,
            changed_tick INTEGER NOT NULL DEFAULT 0);
        """
    )
    conn.commit()
    conn.close()

    async def fn():
        engine = WorldEngine(WorldStore(db))
        with pytest.raises(IncompatibleDataError) as ei:
            await engine.initialize()
        msg = str(ei.value)
        assert "world.db" in msg
        assert "entities.name" in msg and "entities.desc" in msg
        assert "entities.user_id" in msg
        # v10：位置三列同属"旧形态"——消息里要一次报全
        assert "entities.map_id" in msg and "entities.row" in msg
        assert "entities.col" in msg
        await engine.terminate()

    _run(fn())


# ---------- D36：不在世界上（位置是可选的 core:position） ----------


def test_place_entity_without_position(tmp_path):
    """**不给坐标 = 造一个不在世界上的实体**，不是"默认放到 (0,0)"。

    这是 D36 落地后新增的能力（1d），也是"仅靠内核就能治理实体"这句话真正成立的前提：
    位置既然是可选组件，就必须有一条**不写位置**的创建路径。若只有"必须给坐标"这一条路，
    "位置可缺失"就只剩内核内部状态能造出来，编辑器/玩法包永远造不出这类实体。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            box = await engine.place_entity("thing", name="箱子")
            assert not box.has_position()
            assert box.pos_key() is None
            # 三个派生 property 一律 None——**不是** "" / 0（空值兜底会把缺失变成静默错误）
            assert box.map_id is None and box.row is None and box.col is None
            assert CORE_POSITION not in box.components, "不给坐标就不该写 core:position"
            assert box.name == "箱子", "名字仍走 core:info（位置与名字是两件事）"

            # 不进默认列表、也不匹配任何按位置的筛选
            assert box.id not in {e.id for e in engine.list_entities()}
            assert box.id not in {e.id for e in engine.list_entities(map_id="default")}
            assert box.id not in {e.id for e in engine.list_entities(row=0, col=0)}
            # include_absent=True 才拿得到
            assert box.id in {e.id for e in engine.list_entities(include_absent=True)}
            assert box.id in {e.id for e in engine.query_entities(include_absent=True)}
            assert box.id not in {e.id for e in engine.query_entities()}

            # "必须在场"的路径要显式失败，而不是拿 None 继续算
            with pytest.raises(WorldError, match="不在任何地块"):
                box.require_position()
            # move 对不在场实体报错（D42 起不再限身份，所以随便什么 kind 都行）
            # 方向只认 up/right/down/left（"north" 会被方向校验先拦下）
            ghost = await engine.place_entity("player", name="掉线的小明")
            with pytest.raises(WorldError, match="不在任何地块"):
                await engine.move(ghost.id, "right")

            # 放进世界（显式动作）之后一切照旧。**用 move_entity（玩法包的原语）而不是
            # 直接 set_position**——它才是"把不在场的东西放回场上"的那条真实路径
            await engine.move_entity(box.id, "default", 1, 0)
            assert box.pos_key() == ("default", 1, 0)
            assert box.id in {e.id for e in engine.list_entities()}

            # 再拿出来 = 离开世界（下线 / 收进容器）。**必须有一条玩法包走得通的路**：
            # `core:` 是内核保留命名空间（D33），没有这条受控入口的话，"不在世界上"
            # 就是一道单向门——造得出、送不回去
            await engine.clear_position(box.id)
            assert box.pos_key() is None
            assert engine.get_component(box.id, CORE_POSITION) is None
            assert box.id not in {e.id for e in engine.list_entities()}
            # 实体本身还在（不是 remove_entity：组件/名字都保留）
            assert box.name == "箱子"
            await engine.clear_position(box.id)  # 幂等：本来就不在世界上 = 无操作
        finally:
            await engine.terminate()

    _run(fn())


def test_position_args_are_all_or_nothing(tmp_path):
    """位置三参数**要么全给、要么全不给**——半截坐标会被兜底成 `""` / `0`。

    "忘给一个"如果被静默补成 0，实体会**出现在世界里一个没人指定过的格子上**，
    而且看起来完全正常。这与 `Entity.from_dict` 折顶层三键的规则是同一条。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            for args in (("default", 0, None), ("default", None, 0), (None, 0, 0)):
                with pytest.raises(WorldError, match="半截"):
                    await engine.place_entity("thing", *args)
            # 全给但仍要过地图/地块校验（宽松不等于不校验）
            with pytest.raises(WorldError, match="地块不存在"):
                await engine.place_entity("thing", "default", 99, 99)
            with pytest.raises(WorldError, match="地图不存在"):
                await engine.place_entity("thing", "no_such_map", 0, 0)
        finally:
            await engine.terminate()

    _run(fn())


def test_absent_entities_survive_restart(tmp_path):
    """ "不在世界上"要能落库、能重启回来——否则它只是个内存里的中间态。"""

    db = tmp_path / "world.db"

    async def first():
        engine = WorldEngine(WorldStore(db))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            box = await engine.place_entity("thing", name="箱子")
            return box.id
        finally:
            await engine.terminate()

    box_id = _run(first())

    async def second():
        engine = WorldEngine(WorldStore(db))
        await engine.initialize()
        try:
            got = engine.get_entity(box_id)
            assert got is not None and got.pos_key() is None
            assert got.name == "箱子"
        finally:
            await engine.terminate()

    _run(second())
