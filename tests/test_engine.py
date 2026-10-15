"""v4 世界引擎单元测试（DESIGN.md 契约）。

以 namespace package 加载插件（与 test_engine.py 相同模式）；时钟与 PRNG
注入保证确定性；每个测试 ``asyncio.run`` 起单循环（aiosqlite 连接绑定循环）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from world_fixtures import install_demo_world, seed_test_world  # noqa: E402

from worlditor_mcp.world import (  # noqa: E402
    InteractionRequest,
    InteractionResult,
)
from worlditor_mcp.world.engine import (  # noqa: E402
    WorldEngine,
    WorldError,
)
from worlditor_mcp.world.play.api import WorlditorPlayAPI  # noqa: E402
from worlditor_mcp.world.store import (  # noqa: E402
    WorldStore,
)

SH_TZ = ZoneInfo("Asia/Shanghai")
# 演示世界包（worlditor_play_demo_world）导入后的规模：41 地块 + 3 实体
SEED_LOCATION_COUNT = 41
SEED_ENTITY_COUNT = 3  # 商贩·阿福 / 告示牌 / 木门


class FakeClock:
    """可变时钟：tick/冷却测试用。"""

    def __init__(self, ts: float = 1750000000.0) -> None:
        self.ts = ts

    def __call__(self) -> datetime:
        return datetime.fromtimestamp(self.ts, tz=SH_TZ)

    def advance(self, seconds: float) -> None:
        self.ts += seconds


def fixed_clock(hour: int, minute: int = 0):
    return lambda: datetime(2026, 8, 13, hour, minute, tzinfo=SH_TZ)


def _run(coro):
    return asyncio.run(coro)


def make_engine(db_path: Path, clock=None, rand=None) -> WorldEngine:
    return WorldEngine(WorldStore(db_path), clock=clock or fixed_clock(12), rand=rand)


async def _scenario(tmp_path: Path, fn, *, clock=None, rand=None):
    engine = make_engine(tmp_path / "world.db", clock=clock, rand=rand)
    await engine.initialize()
    try:
        return await fn(engine, clock)
    finally:
        await engine.terminate()


# ---------- 播种与基础状态 ----------


def test_seed_world(tmp_path):
    """v0.2.0：内核只建空容器；41 地块 + 3 实体由内置演示世界包导入。"""

    async def fn(engine: WorldEngine, clock=None):
        # 内核不再内置世界内容（v2/D37 起也不再有物品）：初始化后 0 地图、0 地块、0 实体
        assert engine.store.maps == {}
        assert engine.list_locations() == []
        assert engine.list_entities() == []
        assert not hasattr(engine.store, "items")
        # 世界内容来自世界包（worlditor_play_demo_world）
        await install_demo_world(engine)
        assert len(engine.list_locations()) == SEED_LOCATION_COUNT
        assert len(engine.list_entities()) == SEED_ENTITY_COUNT
        abilities = {
            key
            for e in engine.list_entities()
            for key in e.components
            if key.startswith("local:")
        }
        assert abilities == {"local:merchant", "local:sign", "local:door"}
        plaza = engine.list_entities(row=0, col=0)
        assert any(e.has_component("local:merchant") for e in plaza)
        door = [e for e in engine.list_entities() if e.has_component("local:door")][0]
        assert door.component("local:door").get("open") is False

    _run(_scenario(tmp_path, fn))


def test_seed_is_idempotent(tmp_path):
    """重复初始化 + 重复导入世界包不重复播种（幂等）。"""

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)
        await engine.terminate()
        engine2 = make_engine(tmp_path / "world.db")
        await engine2.initialize()
        try:
            # 再导入一次：地图已存在 → 整体跳过，地块/实体不翻倍
            await install_demo_world(engine2)
            assert len(engine2.list_locations()) == SEED_LOCATION_COUNT
            assert len(engine2.list_entities()) == SEED_ENTITY_COUNT
        finally:
            await engine2.terminate()

    _run(_scenario(tmp_path, fn))


# ---------- 实体放置 / 移除（B8：地图编辑内容） ----------


def test_place_entity(tmp_path):
    """放置实体：uuid id、name 缺省取 kind label、地块必须存在。"""

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)  # (1,0) / (1,2) 等演示地块
        engine.register_entity_kind("workshop", label="工坊")
        e = await engine.place_entity("workshop", "default", 1, 0, desc="叮叮当当。")
        assert len(e.id) == 32 and all(c in "0123456789abcdef" for c in e.id)
        assert e.name == "工坊"
        assert e.pos_key() == ("default", 1, 0)
        assert engine.get_entity(e.id) is e
        with pytest.raises(WorldError, match="地块不存在"):
            await engine.place_entity("workshop", "default", 99, 99)
        with pytest.raises(WorldError, match="不能为空"):
            await engine.place_entity("", "default", 1, 2)

    _run(_scenario(tmp_path, fn))


def test_remove_entity(tmp_path):
    """移除实体：实体消失 + on_entity_removed 事件；**绑定了账户**的实体拒绝（D14 / D42）。"""

    async def fn(engine: WorldEngine, clock=None):
        await seed_test_world(engine)  # 中央广场 (0,0)
        removed = []
        engine.register_world_event(
            "on_entity_removed", lambda api, e: removed.append(e.id)
        )
        npc = await engine.place_entity("wolf", "default", 0, 0, name="狼")
        await engine.remove_entity(npc.id)
        assert engine.get_entity(npc.id) is None
        assert removed == [npc.id]
        with pytest.raises(WorldError, match="实体不存在"):
            await engine.remove_entity(npc.id)
        # D42：判据是**账户绑定**（core:account），不是 kind——
        # 所以 kind=player 但没绑账户的实体**可以**被移除
        loose = await engine.place_entity("player", "default", 0, 0, name="野玩家")
        await engine.remove_entity(loose.id)
        assert engine.get_entity(loose.id) is None
        # 绑了账户的（不管 kind 叫什么）拒绝移除
        bound = await engine.place_entity(
            "player", "default", 0, 0, name="小明", user_id="acct_1"
        )
        with pytest.raises(WorldError, match="绑定了账户"):
            await engine.remove_entity(bound.id)
        assert engine.get_entity(bound.id) is not None
        # 内核受控通道（账户注销）能删，且只接受绑账户的实体
        stray = await engine.place_entity("wolf", "default", 0, 1, name="另一只狼")
        with pytest.raises(WorldError, match="只支持绑定了账户"):
            await engine.delete_account_entity(stray.id)
        await engine.delete_account_entity(bound.id)
        assert engine.get_entity(bound.id) is None

    _run(_scenario(tmp_path, fn))


# ---------- 移动（路径 + 阻挡 + 传送） ----------


def test_move_identity_entity(tmp_path):
    """路径移动（v3 语义）：广场 (0,0) 向北到步行街南街口。

    D42：**不再限"只有玩家能走"**（身份概念已删）——`kind="door"` 的实体同样能走；
    "谁能移动"归能力（组件声明 / override / disable，D11）。
    """

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)  # 广场 (0,0) 北上是步行街·南街口
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        scene = await engine.move(player.id, "up")
        assert (scene.map_id, scene.row, scene.col) == ("default", -1, 0)
        assert scene.location.name == "步行街·南街口"
        # 非玩家实体也能走（D42 前这里会报"只有玩家/agent 实体可以按路径移动"）
        door = [e for e in engine.list_entities() if e.has_component("local:door")][0]
        await engine.move_entity(door.id, "default", 0, 0)
        assert (await engine.move(door.id, "up")).location.name == "步行街·南街口"
        # 方向非法
        with pytest.raises(WorldError, match="方向"):
            await engine.move(player.id, "north")

    _run(_scenario(tmp_path, fn))


def test_move_not_blocked_by_door(tmp_path):
    """阻挡机制已移除：木门（`local:door` 组件）不再挡路，也不需要"开门"才能通过。"""

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)  # 木门在 (3,0)
        engine.register_entity_kind("door", interactions=("open",))
        door = [e for e in engine.list_entities() if e.has_component("local:door")][0]
        # block_move 已从能力面（capabilities / list_kinds）整体消失
        assert "block_move" not in engine.capabilities(door)
        kinds = {k["key"]: k for k in engine.list_kinds()}
        assert "block_move" not in kinds["local:door"]
        player = await engine.place_entity("player", "default", 2, 0, name="小明")
        # (2,0) 老路 → 南 (3,0) 林间路口（木门在此）：门不挡路，直接走过去
        scene = await engine.move(player.id, "down")
        assert (scene.row, scene.col) == (3, 0)
        assert door.component("local:door") == {"open": False}  # 门依然关着

    _run(_scenario(tmp_path, fn))


def test_move_entity_teleport(tmp_path):
    """move_entity：直接坐标（行为驱动），触发 on_entity_move/on_entity_enter。"""

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)  # 告示牌在 (-2,0)
        moves = []
        engine.register_world_event(
            "on_entity_move", lambda api, e, f, t: moves.append((e.id, f, t))
        )
        sign = [e for e in engine.list_entities() if e.has_component("local:sign")][0]
        await engine.move_entity(sign.id, "default", 0, 0)
        assert sign.pos_key() == ("default", 0, 0)
        assert moves[-1][2] == ("default", 0, 0)
        with pytest.raises(WorldError, match="地块不存在"):
            await engine.move_entity(sign.id, "default", 50, 50)

    _run(_scenario(tmp_path, fn))


# ---------- 组件 / 字段 ----------


def test_component_and_field_patch(tmp_path):
    """set_component 整块写 + set_data 字段写；on_entity_changed 事件；实体不存在报错。"""

    async def fn(engine: WorldEngine, clock=None):
        await seed_test_world(engine)  # 中央广场 (0,0)
        changed = []
        engine.register_world_event(
            "on_entity_changed", lambda api, e, c: changed.append((e.id, c))
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        comp = "local:stat"
        await engine.set_component(player.id, comp, {"gold": 10})
        # set_component 是**整体替换**："合并写"要调用方自己把旧值并进来
        await engine.set_component(
            player.id,
            comp,
            {**(engine.get_component(player.id, comp) or {}), "gold": 8, "level": 2},
        )
        assert engine.get_component(player.id, comp) == {"gold": 8, "level": 2}
        # set_data 是组件内的单字段合并写（组件不存在则隐式建出）
        await engine.set_data(player.id, "hungry", True, component="local:vital")
        assert engine.get_component(player.id, "local:vital") == {"hungry": True}
        assert await engine.get_data(player.id, component="local:vital") == {
            "hungry": True
        }
        assert len(changed) == 3
        with pytest.raises(WorldError, match="实体不存在"):
            engine.get_component("missing", comp)

    _run(_scenario(tmp_path, fn))


# ---------- 交互（A1：effects 内核结算） ----------


def _demo_registry(engine: WorldEngine) -> None:
    engine.register_entity_kind(
        "merchant", interactions=("talk", "trade"), label="商贩"
    )
    engine.register_entity_kind("sign", interactions=("read",), label="告示牌")
    engine.register_interaction(
        "talk", _talk_handler, label="打招呼", play_id="test_play"
    )
    engine.register_interaction(
        "trade", _trade_handler, label="看看货", play_id="test_play"
    )
    engine.register_interaction(
        "read", _read_handler, label="阅读", play_id="test_play"
    )
    engine.register_interaction("buy", _buy_handler, label="买", play_id="test_play")


async def _talk_handler(api, req: InteractionRequest) -> InteractionResult:
    return InteractionResult(
        text=f"你好，我是{req.target.name}！",
        ui=None,
    )


async def _trade_handler(api, req: InteractionRequest) -> InteractionResult:
    # D12：命令式——handler 直接调原语（api.set_data / api.kv_set）
    await api.set_data(req.entity_id, "gold", -5, component="local:stat")
    await api.kv_set("bag", {"apple": 1})
    return InteractionResult(text="货单：苹果 5 金。")


async def _read_handler(api, req: InteractionRequest) -> InteractionResult:
    return InteractionResult(text="告示牌上写着：明日集市。")


async def _buy_handler(api, req: InteractionRequest) -> InteractionResult:
    return InteractionResult(text="买完了。")


def test_interact_flow_command_mode(tmp_path):
    """交互全流程（D12 命令式）：可用动作（C3）→ handler 直接调原语生效。"""

    async def fn(engine: WorldEngine, clock=None):
        from worlditor_mcp.world.play.api import WorlditorPlayAPI

        await install_demo_world(engine)  # 商贩·阿福在 (0,0)，(1,0) 老路可放机器人
        engine.attach_play_api("test_play", WorlditorPlayAPI(engine, "test_play"))
        _demo_registry(engine)
        merchant = [
            e for e in engine.list_entities() if e.has_component("local:merchant")
        ][0]
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        # 可用动作 = kind 声明 ∪ 全局注册（C3）：merchant 声明 talk/trade，
        # 全局注册的 read/buy 对任何目标也可用
        actions = engine.available_actions(merchant.id)
        assert "talk" in actions and "trade" in actions
        assert "read" in actions and "buy" in actions

        result = await engine.interact(player.id, merchant.id, "talk")
        assert result.text == "你好，我是商贩·阿福！"
        # 命令式原语调用即时生效（无 effects 结算）
        result2 = await engine.interact(player.id, merchant.id, "trade")
        assert engine.kv_get("test_play", "bag") == {"apple": 1}
        assert engine.get_component(player.id, "local:stat") == {"gold": -5}
        assert result2.text == "货单：苹果 5 金。"
        # 未声明且未注册的动作
        with pytest.raises(WorldError, match="没有"):
            await engine.interact(player.id, merchant.id, "fly")
        # 声明但未实现的动作
        engine.register_entity_kind("robot", interactions=("beep",))
        robot = await engine.place_entity("robot", "default", 1, 0, name="小机器人")
        with pytest.raises(WorldError, match="尚未实现"):
            await engine.interact(player.id, robot.id, "beep")

    _run(_scenario(tmp_path, fn))


def test_interact_carries_play_owned_item_id_in_args(tmp_path):
    """D37：物品标识由玩法包放进 ``args``——内核不解释内容，也不再代发事件。"""

    async def fn(engine: WorldEngine, clock=None):
        # handler 需要 api：挂一个真实 WorlditorPlayAPI 实例（模拟 PlayLoader 绑定）
        from worlditor_mcp.world.play.api import WorlditorPlayAPI

        await seed_test_world(engine)  # 中央广场 (0,0)
        engine.attach_play_api("test_play", WorlditorPlayAPI(engine, "test_play"))
        engine.register_interaction(
            "eat", _eat_handler, label="吃", play_id="test_play"
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await engine.kv_set("test_play", "bag", {"apple": 2})
        # 物品标识经 args 传入（原 item_id 槽位已随 D37 删除）
        result = await engine.interact(
            player.id, player.id, "eat", args={"item": "apple"}
        )
        assert "好吃" in result.text
        assert engine.kv_get("test_play", "bag") == {"apple": 1}
        # 内核事件 on_item_used 已删除（D37）→ 事件表里没有它
        from worlditor_mcp.world.model import WORLD_EVENTS

        assert "on_item_used" not in WORLD_EVENTS
        # 没带物品标识时走 handler 自己的兜底（内核不补默认值）
        result2 = await engine.interact(player.id, player.id, "eat")
        assert "没有可吃的" in result2.text

    _run(_scenario(tmp_path, fn))


async def _eat_handler(api, req: InteractionRequest) -> InteractionResult:
    item_id = str((req.args or {}).get("item") or "")
    bag = api.kv_get("bag", {})
    if not item_id or not isinstance(bag, dict) or bag.get(item_id, 0) < 1:
        return InteractionResult(text="没有可吃的。")
    bag[item_id] -= 1
    await api.kv_set("bag", bag)
    return InteractionResult(text="咔嚓，好吃！")


def test_interact_handler_error_isolated(tmp_path):
    """handler 异常 → 转为可展示的 WorldError（不拖垮内核）。"""

    async def boom(api, req):
        raise RuntimeError("玩法包炸了")

    async def fn(engine: WorldEngine, clock=None):
        await seed_test_world(engine)  # 中央广场 (0,0)
        engine.register_interaction("boom", boom, label="自爆")
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        with pytest.raises(WorldError, match="交互执行出错"):
            await engine.interact(player.id, player.id, "boom")
        # 内核仍可用
        engine.register_interaction("ping", lambda api, req: _talk_handler(api, req))
        result = await engine.interact(player.id, player.id, "ping")
        assert result.text

    _run(_scenario(tmp_path, fn))


def test_interact_command_reentrant(tmp_path):
    """D12 命令式：handler 内直接调 move_entity 等原语（可重入锁不死锁）。"""

    async def fn(engine: WorldEngine, clock=None):
        from worlditor_mcp.world.play.api import WorlditorPlayAPI

        engine.attach_play_api("test_play", WorlditorPlayAPI(engine, "test_play"))
        await install_demo_world(engine)  # 传送目标 (5,1) 迷雾深处
        engine.register_entity_kind("teleporter", interactions=("activate",))
        engine.register_interaction(
            "activate",
            lambda api, req: _activate_handler(api, req),
            label="激活",
            play_id="test_play",
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        pod = await engine.place_entity("teleporter", "default", 1, 0, name="传送台")
        result = await engine.interact(player.id, pod.id, "activate")
        assert player.pos_key() == ("default", 5, 1)  # 命令式 move_entity 生效
        assert "嗡嗡" in result.text

    _run(_scenario(tmp_path, fn))


async def _activate_handler(api, req: InteractionRequest) -> InteractionResult:
    # D12 命令式：直接调原语 + 自定义事件
    await api.move_entity(req.entity_id, "default", 5, 1)
    await api.emit("teleport_flash", {"entity_id": req.entity_id}, log=True)
    return InteractionResult(text="传送台嗡嗡作响，你被传送到了迷雾深处。")


# ---------- 事件总线 / 世界日志 ----------


def test_events_and_world_log(tmp_path):
    """事件总线分发（含 handler 异常隔离）+ world_log 写入。"""

    async def fn(engine: WorldEngine, clock=None):
        await seed_test_world(engine)  # 中央广场 (0,0) 北上是北门
        seen = []
        engine.register_world_event("my_say", _bad_event_handler)
        engine.register_world_event(
            "my_say", lambda api, text: seen.append(("say", text))
        )
        engine.register_world_event(
            "on_interact",
            lambda api, req, result: seen.append(("interact", req.action)),
        )
        engine.register_world_event(
            "on_entity_move",
            lambda api, e, f, t: seen.append(("move", e.id, f[0], f[1], f[2])),
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        await engine.emit("my_say", "hello", log=True)
        await engine.move(player.id, "up")
        assert ("say", "hello") in seen
        assert ("move", player.id, "default", 0, 0) in seen
        # world_log：自定义事件/移动已写入
        logs = await engine.store.list_world_log(limit=50)
        kinds = {log["kind"] for log in logs}
        assert "my_say" in kinds and "on_entity_move" in kinds
        assert all(log["data"].get("event") for log in logs)

    _run(_scenario(tmp_path, fn))


async def _bad_event_handler(api, *args):
    raise RuntimeError("事件 handler 炸了")


def test_world_log_capacity(tmp_path):
    """world_log 上限 5000 条（B3）：超限写入自动清理最旧。"""

    async def fn(engine: WorldEngine, clock=None):
        for i in range(5050):
            await engine.emit("msg_loop", f"msg-{i}", log=True)
        logs = await engine.store.list_world_log(limit=99999)
        assert len(logs) <= 5000
        assert logs[0]["data"]["values"][0] == "msg-5049"  # 最新保留
        # 最旧 50 条（msg-0..msg-49）已被清理
        oldest = {log["data"]["values"][0] for log in logs[-10:]}
        assert "msg-49" not in oldest and "msg-4" not in oldest

    _run(_scenario(tmp_path, fn))


# ---------- on_tick 调度（A3） ----------


def test_tick_schedule_intervals(tmp_path):
    """on_tick：各自间隔 + dt 语义 + 异常隔离（手动驱动 _tick_once）。"""

    async def fn(engine: WorldEngine, clock: FakeClock):
        runs = []
        engine.register_world_event(
            "on_tick", _tick_handler_factory(runs, "slow"), interval=3
        )
        engine.register_world_event(
            "on_tick", _tick_handler_factory(runs, "fast"), interval=1
        )
        engine.register_world_event("on_tick", _bad_tick_handler, interval=1)
        # t=1000（首次）：所有 handler 到期（last_run=0），dt = 各自 interval
        await engine._tick_once()
        assert runs == [("slow", 3.0), ("fast", 1.0)]
        # t=1001：fast 恰好 1s（>= interval）到期；slow 未到期
        clock.advance(1)
        await engine._tick_once()
        assert runs == [("slow", 3.0), ("fast", 1.0), ("fast", 1.0)]
        # t=1004：slow 到期 dt=4；fast 到期 dt=3
        clock.advance(3)
        await engine._tick_once()
        assert runs == [
            ("slow", 3.0),
            ("fast", 1.0),
            ("fast", 1.0),
            ("slow", 4.0),
            ("fast", 3.0),
        ]

    _run(_scenario(tmp_path, fn, clock=FakeClock(1000.0)))


def _tick_handler_factory(runs: list, tag: str):
    async def handler(api, dt: float):
        runs.append((tag, dt))

    return handler


async def _bad_tick_handler(api, dt: float):
    raise RuntimeError("tick 炸了")


# ---------- 地图编辑（B8：删除地块级联删实体） ----------


def test_delete_location_cascade(tmp_path):
    """删除地块：级联删其上实体 + 全图引用清理；**有绑定了账户的实体在场**拒绝（D42）。"""

    async def fn(engine: WorldEngine, clock=None):
        await install_demo_world(engine)  # 告示牌 + 广场 (0,0) / (-1,0) / (1,0)
        sign = [e for e in engine.list_entities() if e.has_component("local:sign")][0]
        # 把告示牌移到步行街南街口 (-1,0) 然后删除该地块
        await engine.move_entity(sign.id, "default", -1, 0)
        await engine.delete_location("default", -1, 0)
        assert engine.get_entity(sign.id) is None
        assert engine.get_location("default", -1, 0) is None
        # 引用清理：广场 (0,0) 的北向路径应已移除
        plaza = engine.get_location("default", 0, 0)
        assert plaza.connections["up"].paths == []
        # 有**绑定了账户**的实体在场拒绝（D42：判据是 core:account，不是 kind）
        player = await engine.place_entity(
            "player", "default", 1, 0, name="小明", user_id="acct_1"
        )
        with pytest.raises(WorldError, match="无法删除"):
            await engine.delete_location("default", 1, 0)
        await engine.move_entity(
            player.id, "default", 0, 0
        )  # 绑账户的实体移走（不可被 remove）
        await engine.delete_location("default", 1, 0)
        # 反面对照：kind=player 但**没绑账户**的实体不挡删地块（D42 前会白挡）
        await engine.create_location("default", 5, 5, "空地")
        loose = await engine.place_entity("player", "default", 5, 5, name="野玩家")
        await engine.delete_location("default", 5, 5)
        assert engine.get_entity(loose.id) is None

    _run(_scenario(tmp_path, fn))


def test_item_type_declaration_replaces_item_def(tmp_path):
    """D37：物品**类型**改由组件声明表达——声明即出现在类型清单里，带字段 schema 与归属。"""

    async def fn(engine: WorldEngine, clock=None):
        from worlditor_mcp.world.play.api import WorlditorPlayAPI

        api = WorlditorPlayAPI(engine, "worlditor_play_items")
        # 原 register_item_def(ItemDef(id="sword_01", …, fields=[…])) 的等价写法
        api.register_entity_tag(
            "sword_01",
            label="木剑",
            fields=[{"name": "atk", "label": "攻击", "type": "int", "default": 1}],
        )
        row = next(
            k for k in api.list_kinds() if k["key"] == "worlditor_play_items:sword_01"
        )
        assert row["label"] == "木剑"
        assert [f["name"] for f in row["fields"]] == ["atk"]
        assert row["source"] == "worlditor_play_items"  # 归属仍在（卸载可清）
        # 名字为空要报错（原物品定义的同一条校验，这里由组件名校验承担）
        with pytest.raises(WorldError):
            api.register_entity_tag("")

    _run(_scenario(tmp_path, fn))


# ---------- 界面扩展（B9：ui_hook before/after/replace） ----------


def test_apply_ui_hooks_positions(tmp_path):
    """ui_hook 三位置：before 插入 / after 追加 / replace 重写（递归展开）。"""

    from worlditor_mcp.world.model import UiBlock

    async def fn(engine: WorldEngine, clock=None):
        # before / after
        engine.register_ui_hook(
            "text",
            "before",
            _hook_provider([UiBlock(kind="text", text="[前置]")]),
            play_id="p1",
        )
        engine.register_ui_hook(
            "text",
            "after",
            _hook_provider([UiBlock(kind="text", text="[后置]")]),
            play_id="p1",
        )
        out = await engine.apply_ui_hooks(UiBlock(kind="text", text="正文"))
        assert [b.text for b in out.blocks] == ["[前置]", "[后置]"]
        assert out.text == "正文"
        # replace：整体替换（provider 返回 custom 块）
        engine.register_ui_hook(
            "text",
            "replace",
            _hook_provider(
                [UiBlock(kind="custom", text="", data={"fallback_text": "自定义界面"})]
            ),
            play_id="p1",
        )
        out = await engine.apply_ui_hooks(UiBlock(kind="text", text="正文"))
        assert out.kind == "custom"
        # 嵌套：子块先递归展开
        engine.register_ui_hook(
            "list",
            "before",
            _hook_provider([UiBlock(kind="text", text="[列表头]")]),
            play_id="p1",
        )
        parent = UiBlock(kind="menu", blocks=[UiBlock(kind="list", text="条目")])
        out = await engine.apply_ui_hooks(parent)
        assert out.blocks[0].kind == "list"
        assert out.blocks[0].blocks[0].text == "[列表头]"
        # provider 异常隔离（不破坏渲染）
        engine.register_ui_hook(
            "menu", "after", _hook_provider(None, boom=True), play_id="p1"
        )
        out = await engine.apply_ui_hooks(UiBlock(kind="menu"))
        assert out is not None

    _run(_scenario(tmp_path, fn))


def test_interact_result_applies_ui_hooks(tmp_path):
    """G18 接线：interact 结果在返回前应用 ui_hook（交互弹窗注入，端到端）。"""

    from worlditor_mcp.world.model import InteractionResult, UiBlock
    from worlditor_mcp.world.play.api import WorlditorPlayAPI

    async def fn(engine: WorldEngine, clock=None):
        await seed_test_world(engine)  # 中央广场 (0,0) / 东街 (0,1)
        api = WorlditorPlayAPI(engine, "pkg_a")
        engine.attach_play_api("pkg_a", api)

        async def say_hi(api, req):
            return InteractionResult(text="你好", ui=UiBlock(kind="text", text="你好"))

        api.register_interaction("hi", say_hi, label="打招呼")
        engine.register_ui_hook(
            "text",
            "before",
            _hook_provider([UiBlock(kind="text", text="[注入]")]),
            play_id="p1",
        )
        player = await engine.place_entity("player", "default", 0, 0, name="小明")
        npc = await engine.place_entity("npc", "default", 0, 1, name="NPC")
        result = await engine.interact(player.id, npc.id, "hi")
        assert result.text == "你好"
        assert [b.text for b in result.ui.blocks] == ["[注入]"]
        assert result.ui.text == "你好"  # 主块未被替换

    _run(_scenario(tmp_path, fn))


def _hook_provider(blocks: list | None, *, boom: bool = False):
    async def provider(api, block):
        if boom:
            raise RuntimeError("hook 炸了")
        return blocks or []

    return provider


# ---------- 内核协议组件的受控入口（v2 / D33） ----------


def test_set_perception_is_the_only_play_door(tmp_path):
    """玩法包写不了 ``core:``，但"让实体隐身"经 ``set_perception`` 这个窄口仍可用。

    这是 D33 与"能力不丢失"的平衡点：规则不放宽（``core:`` 仍只有内核能直写），
    正当能力走内核拥有的受控入口（与 D20"NPC 升格必须经身份服务"同一做法）。
    """

    async def fn(engine, _clock):
        await seed_test_world(engine)
        api = WorlditorPlayAPI(engine, "worlditor_play_probe")
        viewer = await engine.place_entity("player", "default", 0, 0, name="看客")
        ghost = await engine.place_entity("npc", "default", 0, 0, name="幽灵")

        # 直写 core: 被玩法包 API 拒绝
        with pytest.raises(WorldError, match="内核保留"):
            await api.set_data(ghost.id, "invisible", True, component="core:perception")

        # 受控入口：隐身 → 普通 viewer 看不到
        await api.set_perception(ghost.id, {"invisible": True})
        seen = [
            e.id for e in engine.list_entities("default", 0, 0, viewer_id=viewer.id)
        ]
        assert ghost.id not in seen
        assert viewer.id in seen  # 自己永远看得到自己

        # 真视 → 看得到
        await api.set_perception(viewer.id, {"see_invisible": True})
        seen = [
            e.id for e in engine.list_entities("default", 0, 0, viewer_id=viewer.id)
        ]
        assert ghost.id in seen

        # 复原：invisible 置 False 后普通观察者也看得到
        await api.set_perception(ghost.id, {"invisible": False})
        seen = [e.id for e in engine.list_entities("default", 0, 0)]
        assert ghost.id in seen

        # 白名单：只收 invisible / see_invisible，且必须是布尔
        with pytest.raises(WorldError, match="感知只支持"):
            await api.set_perception(ghost.id, {"hp": 1})
        with pytest.raises(WorldError, match="必须是布尔值"):
            await api.set_perception(ghost.id, {"invisible": "yes"})
        with pytest.raises(WorldError, match="patch 必须是对象"):
            await api.set_perception(ghost.id, ["invisible"])
        # 空 patch = 什么都不做（幂等，不落盘）——不报错
        before = engine.revision
        await api.set_perception(ghost.id, {})
        assert engine.revision == before

    _run(_scenario(tmp_path, fn))
