"""玩法包加载器测试（DESIGN.md「发现加载流程」）。

覆盖：demo_play 加载与行为集成、社区玩法包发现、namespace 隔离、
异常隔离（坏包不阻断）、版本校验、teardown。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from play_fixtures import PLAY_ID, install_demo_play  # noqa: E402

from worlditor_mcp.world.engine import (  # noqa: E402
    WorldEngine,
    WorldError,
)
from worlditor_mcp.world.play import PlayLoader  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402

SEED_LOCATION_COUNT = 41


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
    """演示玩法包加载：注册表（kind/interaction/event）就位。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        plays = await loader.load_all()
        assert [p.play_id for p in plays] == [PLAY_ID]
        assert set(engine._kind_specs) == {"merchant", "sign", "door"}
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
        # 物品落库（flush 后持久化；喇叭 = 内核定义 D13，苹果归 items 包）
        await engine.terminate()
        engine2 = WorldEngine(WorldStore(db_path))
        await engine2.initialize()
        try:
            assert "megaphone" in engine2.store.items
        finally:
            await engine2.terminate()

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
    """演示玩法包全链路：talk → trade → buy（effects 结算）→ eat（事件回血）。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        merchant = [e for e in engine.list_entities() if e.kind == "merchant"][0]
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"gold": 20}
        )
        # talk
        result = await engine.interact(player.id, merchant.id, "talk")
        assert "阿福" in result.text
        assert result.ui is not None and result.ui.actions
        # trade → list
        result = await engine.interact(player.id, merchant.id, "trade")
        assert result.ui is not None and result.ui.kind == "list"
        # buy_apple：命令式结算（set_attrs 扣金 + kv 背包给苹果，D8 持有下沉）
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert engine.kv_get("worlditor_play_demo", "bag") == {"apple": 1}
        assert engine.get_attrs(player.id)["gold"] == 15
        # 钱不够
        await engine.set_attrs(player.id, {"gold": 1})
        result = await engine.interact(player.id, merchant.id, "buy_apple")
        assert "钱不够" in result.text
        assert engine.kv_get("worlditor_play_demo", "bag") == {"apple": 1}
        # buy_megaphone：命令式 API
        await engine.set_attrs(player.id, {"gold": 20})
        result = await engine.interact(player.id, merchant.id, "buy_megaphone")
        assert engine.kv_get("worlditor_play_demo", "bag") == {
            "apple": 1,
            "megaphone": 1,
        }
        assert engine.get_attrs(player.id)["gold"] == 10
        # eat：use 交互 + on_item_used 回血（energy +1）
        await engine.kv_set("worlditor_play_demo", "bag", {"apple": 2, "megaphone": 1})
        result = await engine.interact(player.id, player.id, "eat", item_id="apple")
        assert "咔嚓" in result.text
        assert engine.kv_get("worlditor_play_demo", "bag") == {
            "apple": 1,
            "megaphone": 1,
        }
        assert engine.get_attrs(player.id).get("energy") == 1
        # read：kv 读写（namespace 隔离）
        sign = [e for e in engine.list_entities() if e.kind == "sign"][0]
        result = await engine.interact(player.id, sign.id, "read")
        assert "小镇公告" in result.text
        assert engine.kv_get("worlditor_play_demo", "bulletin_reads") == 1
        # open：门状态变更
        door = [e for e in engine.list_entities() if e.kind == "door"][0]
        result = await engine.interact(player.id, door.id, "open")
        assert "吱呀" in result.text
        assert door.state.get("open") is True
        assert door.state.get("block_move") is False
        result = await engine.interact(player.id, door.id, "open")
        assert "已经开着" in result.text

    _run(_play_scenario(tmp_path, fn))


async def _play_scenario(tmp_path, fn):
    db_path = tmp_path / "world.db"
    loader = make_loader(db_path, tmp_path / "plays")
    engine = loader.engine
    await engine.initialize()
    try:
        return await fn(engine, loader)
    finally:
        await engine.terminate()


def test_demo_door_blocks_and_enter_forest(tmp_path):
    """演示玩法包门阻挡 + 进入迷雾提示（on_entity_enter 事件 → fog_enter 自定义事件）。"""
    install_demo_play(tmp_path / "plays")

    async def fn(engine: WorldEngine, loader: PlayLoader):
        await loader.load_all()
        player = await engine.place_entity("player", "default", 2, 0, name="小明")
        # 木门挡路（demo 注册 kind=door block_move）
        with pytest.raises(WorldError, match="挡住了"):
            await engine.move(player.id, "down")
        # 开门后可通行；进入 (4,0) 迷雾 → on_entity_enter 触发 fog_enter 事件
        door = [e for e in engine.list_entities() if e.kind == "door"][0]
        await engine.interact(player.id, door.id, "open")
        await engine.move(player.id, "down")  # (3,0)
        await engine.move(player.id, "down")  # (4,0) 迷雾森林
        assert player.pos_key() == ("default", 4, 0)
        logs = await engine.store.list_world_log(limit=20)
        fog_logs = [row for row in logs if row["kind"] == "fog_enter"]
        assert any("雾" in str(row["data"]) for row in fog_logs)

    _run(_play_scenario(tmp_path, fn))


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


def test_plugin_alias_registration(tmp_path):
    """AstrBot 真实环境（插件以 data.plugins.* 加载，顶层名缺失）下，
    PlayLoader 把插件包注册顶层别名，玩法包按文档路径导入可用（同一模块对象）。"""

    top = "worlditor_mcp"
    fake_root = "data.plugins." + top
    # 先确保目标子模块已加载（真实环境由 main 链加载 data.plugins.*.world.play）
    import importlib

    importlib.import_module(top + ".world.play")
    # 模拟宿主：把当前包以 data.plugins.* 名注册（同一模块对象）
    sys.modules[fake_root] = sys.modules[top]
    for k, mod in list(sys.modules.items()):
        if k.startswith(top + "."):
            sys.modules[fake_root + k[len(top) :]] = mod
    # 临时移除顶层别名（真实环境只有 data.plugins.* 形式）
    saved = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == top or k.startswith(top + ".")
    }
    for k in saved:
        del sys.modules[k]
    try:
        loader = make_loader(tmp_path / "world.db", tmp_path / "plays")
        loader.register_plugin_aliases()
        # 顶层名已注册且指向同一模块对象（无双份加载）
        assert sys.modules[top] is sys.modules[fake_root]
        assert (
            sys.modules[top + ".world.play"] is sys.modules[fake_root + ".world.play"]
        )
        # 按文档路径导入 == 真实包路径导入（同一类对象）
        top_api = importlib.import_module(top + ".world.play")
        real_api = importlib.import_module(fake_root + ".world.play")
        assert top_api.PlayLoader is real_api.PlayLoader
    finally:
        sys.modules.update(saved)
        for k in list(sys.modules):
            if k.startswith(fake_root):
                del sys.modules[k]


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
