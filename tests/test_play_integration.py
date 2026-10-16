"""玩法包加载器测试（DESIGN.md「发现加载流程」）。

覆盖：demo_play 加载与行为集成、社区玩法包发现、namespace 隔离、
异常隔离（坏包不阻断）、版本校验、teardown。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from play_fixtures import PLAY_ID, install_demo_play  # noqa: E402
from world_fixtures import install_demo_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine  # noqa: E402
from worlditor_mcp.world.play import PlayLoader  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402

SEED_LOCATION_COUNT = 41
# v2（D32）：玩法数据按组件分组；演示夹具包的玩家数据组件（见 play_fixtures.py）
_STAT = "local:stat"


def _run(coro):
    return asyncio.run(coro)


def make_loader(db_path: Path, plays_dir: Path) -> PlayLoader:
    engine = WorldEngine(WorldStore(db_path))
    return PlayLoader(
        engine,
        plays_dir=plays_dir,
        worlditor_version="0.3.0",
    )


def _write_play(root: Path, name: str, main_code: str, yaml_extra: str = "") -> Path:
    """构造一个社区玩法包目录。"""
    play_dir = root / name
    play_dir.mkdir(parents=True, exist_ok=True)
    (play_dir / "play.yaml").write_text(
        f"name: {name}\n"
        f"display_name: {name}\n"
        f"version: 0.1.0\n"
        f"author: test\n"
        f"requires:\n"
        f'  worlditor: ">=0.3.0"\n'
        f"  plays: []\n"
        f"{yaml_extra}",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(main_code, encoding="utf-8")
    return play_dir


# ---------- demo_play 加载与行为集成 ----------


def test_demo_play_loaded(tmp_path):
    """演示玩法包加载：注册表（组件/交互/事件）就位。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        plays = await loader.load_all()
        assert [p.play_id for p in plays] == [PLAY_ID]
        # v2 / D37：苹果与喇叭不再是"内核物品定义"，而是夹具包的**组件声明**
        # （D41：组件即能力/类型——名字 + 字段 schema + 归属都写在组件键上），
        # 所以它们和 merchant/sign/door 同处一个注册表
        assert set(engine._tag_specs) == {
            # merchant/sign/door = 与演示世界内容（world.json）共享的 local: 键
            "local:merchant",
            "local:sign",
            "local:door",
            # 货品标识是包自己的（apple/megaphone），落包命名空间
            f"{PLAY_ID}:apple",
            f"{PLAY_ID}:megaphone",
        }
        assert set(engine._interactions) >= {
            "talk",
            "trade",
            "read",
            "open",
            "eat",
            "bye",
        }
        # on_tick 带间隔订阅
        tick_bindings = engine._event_bindings["on_tick"]
        assert len(tick_bindings) == 1 and tick_bindings[0].interval == 5
        # v2 / D37：内核不再有物品定义与 items 表（那部分断言移入 test_v2_components）。
        # 这里改验证"**组件声明**随包加载进入注册表、且带归属"——它就是物品类型的落点。
        # D41：清单每条 = 一个组件（key/source/name/…，不再有 tag/kind/play_id）。
        kinds = {k["key"]: k for k in engine.list_kinds()}
        assert kinds[f"{PLAY_ID}:apple"]["source"] == PLAY_ID  # 夹具包声明了苹果组件
        assert kinds[f"{PLAY_ID}:apple"]["name"] == "apple"
        assert kinds[f"{PLAY_ID}:apple"]["label"] == "苹果"
        # 共享键：source 就是字面的 local（内容与行为在同一个组件上对接）
        assert kinds["local:merchant"]["source"] == "local"
        assert kinds["local:merchant"]["interactions"] == ["talk", "trade"]

    db_path = tmp_path / "world.db"
    loader = make_loader(db_path, tmp_path / "plays")
    engine = loader.engine
    _run(_async_main(engine, loader, fn))


async def _async_main(engine, loader, fn):
    await engine.initialize()
    try:
        return await fn(engine, loader)
    finally:
        await engine.terminate()


def test_demo_full_interaction_chain(tmp_path):
    """演示玩法包全链路：talk → trade → buy（命令式结算）→ eat（事件回精力）。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        # D41：没有 kind 可读——"是不是商贩" = 带不带 local:merchant 组件
        merchant = [
            e for e in engine.list_entities() if e.has_component("local:merchant")
        ][0]
        player = await engine.place_entity(
            "player",
            "default",
            0,
            0,
            name="小明",
            components={"local:stat": {"gold": 20}},
        )
        # talk
        result = await engine.interact(player.id, merchant.id, "talk")
        assert "阿福" in result.text
        assert result.ui is not None and result.ui.actions
        # trade → list
        result = await engine.interact(player.id, merchant.id, "trade")
        assert result.ui is not None and result.ui.kind == "list"
        # buy_apple：命令式结算（set_data 扣金 + kv 背包给苹果，D8 持有下沉）
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert engine.kv_get("worlditor_play_demo", "bag") == {"apple": 1}
        assert await engine.get_data(player.id, "gold", component=_STAT) == 15
        # 钱不够
        await engine.set_data(player.id, "gold", 1, component=_STAT)
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert "钱不够" in result.text
        assert engine.kv_get("worlditor_play_demo", "bag") == {"apple": 1}
        # buy_megaphone：命令式 API
        await engine.set_data(player.id, "gold", 20, component=_STAT)
        result = await engine.interact(player.id, merchant.id, "buy_megaphone")
        assert engine.kv_get("worlditor_play_demo", "bag") == {
            "apple": 1,
            "megaphone": 1,
        }
        assert await engine.get_data(player.id, "gold", component=_STAT) == 10
        # eat：物品标识经 args 传入（D37：无 item_id 槽位）+ 包自己发 item_used 事件回精力
        await engine.kv_set("worlditor_play_demo", "bag", {"apple": 2, "megaphone": 1})
        result = await engine.interact(
            player.id, player.id, "eat", args={"item": "apple"}
        )
        assert "咔嚓" in result.text
        assert engine.kv_get("worlditor_play_demo", "bag") == {
            "apple": 1,
            "megaphone": 1,
        }
        assert await engine.get_data(player.id, "energy", component=_STAT) == 1
        # read：kv 读写（namespace 隔离）
        sign = [e for e in engine.list_entities() if e.has_component("local:sign")][0]
        result = await engine.interact(player.id, sign.id, "read")
        assert "小镇公告" in result.text
        assert engine.kv_get("worlditor_play_demo", "bulletin_reads") == 1
        # open：门状态变更（v2：组件写；D34：开门不再解除阻挡——全都不阻挡了）
        door = [e for e in engine.list_entities() if e.has_component("local:door")][0]
        result = await engine.interact(player.id, door.id, "open")
        assert "吱呀" in result.text
        assert door.component("local:door") == {"open": True}
        result = await engine.interact(player.id, door.id, "open")
        assert "已经开着" in result.text

    _run(_play_scenario(tmp_path, fn, demo_world=True))


async def _play_scenario(tmp_path, fn, *, demo_world=False):
    """起引擎场景；``demo_world=True`` 先导入演示世界（v0.2.0 内核不内置世界内容）。"""
    db_path = tmp_path / "world.db"
    loader = make_loader(db_path, tmp_path / "plays")
    engine = loader.engine
    await engine.initialize()
    if demo_world:
        # 商贩·阿福 / 告示牌 / 木门 与 41 地块来自内置世界包（不再由内核播种）
        await install_demo_world(engine)
    try:
        return await fn(engine, loader)
    finally:
        await engine.terminate()


def test_demo_door_does_not_block_and_enter_forest(tmp_path):
    """D34：木门**不再阻挡**（阻挡机制整体移除）；开门只是数据写；进迷雾发 fog_enter。"""

    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        player = await engine.place_entity(None, "default", 2, 0, name="小明")
        # D45：内核不再按 kind="player" 造人，也不再有 `local:player` 标记组件。
        # 夹具包判"这是不是人"看**账户绑定**（D42）——所以这里显式认领。
        await engine.claim_avatar(player.id, "acct-test")
        door = [e for e in engine.list_entities() if e.has_component("local:door")][0]
        assert door.pos_key() == ("default", 3, 0)
        assert door.component("local:door") == {"open": False}
        # v2（D34）：所有实体都不阻挡——**没开门也能**直接走到门所在的地块
        await engine.move(player.id, "down")
        assert player.pos_key() == ("default", 3, 0)
        # 开门 = 一次普通的组件写（玩法数据自管），不再解除任何阻挡
        result = await engine.interact(player.id, door.id, "open")
        assert "吱呀" in result.text
        assert door.component("local:door") == {"open": True}
        # 继续南行 → 进入 (4,0) 迷雾森林 → on_entity_enter 触发 fog_enter 自定义事件
        await engine.move(player.id, "down")  # (4,0) 迷雾森林
        assert player.pos_key() == ("default", 4, 0)
        logs = await engine.store.list_world_log(limit=20)
        fog_logs = [row for row in logs if row["kind"] == "fog_enter"]
        assert any("雾" in str(row["data"]) for row in fog_logs)

    _run(_play_scenario(tmp_path, fn, demo_world=True))


# ---------- 发现 / namespace 隔离 / 异常隔离 / 版本 ----------


def test_discover_community_plays(tmp_path):
    """发现：plays/ 下 worlditor_play_* 社区玩法包（非前缀目录忽略）。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        (tmp_path / "plays" / "not_a_play").mkdir(parents=True, exist_ok=True)
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert PLAY_ID in ids
        assert "worlditor_play_hello" in ids
        assert "not_a_play" not in ids

    _write_play(
        tmp_path / "plays",
        "worlditor_play_hello",
        "def setup(api, context):\n    api.register_entity_kind('hello', label='你好')\n",
    )
    _run(_play_scenario(tmp_path, fn))


def test_namespace_isolation(tmp_path):
    """kv namespace 隔离：两个玩法包同 key 互不干扰。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        api_a = loader.plays[PLAY_ID].api
        api_b = loader.plays["worlditor_play_kv"].api
        await api_a.kv_set("counter", 1)
        await api_b.kv_set("counter", 99)
        assert api_a.kv_get("counter") == 1
        assert api_b.kv_get("counter") == 99

    _write_play(
        tmp_path / "plays",
        "worlditor_play_kv",
        "def setup(api, context):\n    pass\n",
    )
    _run(_play_scenario(tmp_path, fn))


def test_bad_play_isolated(tmp_path):
    """异常隔离：main.py 抛异常的玩法包被跳过，不阻断演示包与其他包。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        plays = await loader.load_all()
        ids = [p.play_id for p in plays]
        assert PLAY_ID in ids
        assert "worlditor_play_good" in ids
        assert "worlditor_play_broken" not in ids

    _write_play(
        tmp_path / "plays",
        "worlditor_play_broken",
        "raise RuntimeError('坏包')\n",
    )
    _write_play(
        tmp_path / "plays",
        "worlditor_play_good",
        "def setup(api, context):\n    api.register_entity_kind('good', label='好')\n",
    )
    _run(_play_scenario(tmp_path, fn))


def test_missing_play_yaml_skipped(tmp_path):
    """play.yaml 缺失的目录被跳过。"""

    async def fn(engine: WorldEngine, loader: PlayLoader):
        plays = await loader.load_all()
        assert all(p.play_id != "worlditor_play_noyaml" for p in plays)

    (tmp_path / "plays" / "worlditor_play_noyaml").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plays" / "worlditor_play_noyaml" / "main.py").write_text(
        "def setup(api, context):\n    pass\n", encoding="utf-8"
    )
    _run(_play_scenario(tmp_path, fn))


def test_version_requirement_checked(tmp_path):
    """requires.worlditor 不兼容 → 跳过（v4.0 只校验 worlditor 版本）。"""

    async def fn(engine: WorldEngine, loader: PlayLoader):
        plays = await loader.load_all()
        assert all(p.play_id != "worlditor_play_future" for p in plays)

    _write_play(
        tmp_path / "plays",
        "worlditor_play_future",
        "def setup(api, context):\n    pass\n",
        yaml_extra='  worlditor: ">=5.0.0"\n',
    )
    _run(_play_scenario(tmp_path, fn))


def test_unload_calls_teardown(tmp_path):
    """unload_all：调用 teardown(api)；api 引用解除。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        assert PLAY_ID in loader.plays
        await loader.unload_all()
        assert loader.plays == {}
        assert engine._play_apis.get(PLAY_ID) is None

    _run(_play_scenario(tmp_path, fn))


def test_version_ok_unit():
    """版本比较（spec.version_ok）。"""
    from worlditor_mcp.world.play.spec import version_ok

    assert version_ok("4.0.0", "*")
    assert version_ok("4.0.0", "")
    assert version_ok("4.0.0", ">=4.0.0")
    assert version_ok("4.0.1", ">=4.0.0")
    assert not version_ok("3.9.9", ">=4.0.0")
    assert version_ok("4.0.0", "==4.0.0")
    assert not version_ok("4.0.1", "==4.0.0")
    assert version_ok("4.5.0", "<5.0.0")
    assert version_ok("v4.0.0", ">=4.0.0")
    assert version_ok("4.0", ">=4.0.0")
    assert not version_ok("4.0.0-beta", ">=4.0.1")


# （插件时代 main.py 装配测试已由 tests/test_service.py 取代）
