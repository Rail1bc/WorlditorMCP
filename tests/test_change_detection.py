"""D28 变更检测测试：revision / changed_tick 盖章、增量查询、重启续号、事件携带。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


def test_revision_stamped_on_write(tmp_path):
    """落库那一刻盖章：实体 revision == 全局 revision，且每次写都往上走。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            before = engine.revision
            wolf = await engine.place_entity("wolf", "default", 0, 0)
            # 盖章用的是"落库那一刻"的号：≥ 调用前的号、≤ 调用后的号
            assert before < wolf.revision <= engine.revision
            first = wolf.revision
            await engine.set_attrs(wolf.id, {"hp": 3})
            assert wolf.revision > first
            assert wolf.changed_tick == engine.tick
            # 落库行也带上（重启/别处读库都拿得到）
            raw = engine.store.entities[wolf.id]
            assert raw.revision == wolf.revision
        finally:
            await engine.terminate()

    _run(fn())


def test_batch_write_shares_one_revision(tmp_path):
    """批量写（copy_map 一类）一个变更号盖整批，不逐行跳号。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            a = await engine.place_entity("wolf", "default", 0, 0)
            b = await engine.place_entity("wolf", "default", 1, 0)
            await engine.store.save_entities([a, b])
            assert a.revision == b.revision == engine.revision
        finally:
            await engine.terminate()

    _run(fn())


def test_no_write_no_revision_bump(tmp_path):
    """没写库就不动号：幂等删除、空 patch 都不推进（不然"变了"会变成噪声）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            wolf = await engine.place_entity("wolf", "default", 0, 0)
            await engine.set_data(wolf.id, "hp", 3)
            before = engine.revision
            assert await engine.remove_data(wolf.id, "absent") is False
            await engine.set_attrs(wolf.id, {})
            await engine.set_state(wolf.id, {})
            assert engine.revision == before
        finally:
            await engine.terminate()

    _run(fn())


def test_tick_window_advances_without_subscribers(tmp_path):
    """tick 窗口每轮 +1（哪怕一个 on_tick 订阅者都没有）——它是时间轴，不能停。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            before = engine.tick
            await engine._tick_once()
            await engine._tick_once()
            assert engine.tick == before + 2
        finally:
            await engine.terminate()

    _run(fn())


def test_changed_since_cursors(tmp_path):
    """两个游标：tick（窗口粒度，宁可多报）/ revision（精确，既不多报也不漏报）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            a = await engine.place_entity("wolf", "default", 0, 0)
            b = await engine.place_entity("wolf", "default", 1, 0)
            cursor_rev = engine.revision  # 精确游标：此刻已看到的版本
            seen_tick = engine.tick
            await engine._tick_once()  # 开新窗口
            await engine.set_attrs(b.id, {"hp": 1})
            assert {
                e.id for e in engine.query_entities(changed_since_revision=cursor_rev)
            } == {b.id}
            # tick 游标是"≥ 窗口"：同窗口内更早的变更会一起被带出来（多报安全、不漏报）
            assert {
                e.id for e in engine.query_entities(changed_since_tick=seen_tick)
            } == {a.id, b.id}
            # 同一窗口内的第二次变更：tick 游标会重复报（多报安全），revision 不重复
            now_tick = engine.tick
            now_rev = engine.revision
            await engine.set_attrs(a.id, {"hp": 2})
            assert {
                e.id for e in engine.query_entities(changed_since_tick=now_tick)
            } == {
                a.id,
                b.id,
            }
            assert {
                e.id for e in engine.query_entities(changed_since_revision=now_rev)
            } == {a.id}
        finally:
            await engine.terminate()

    _run(fn())


def test_revision_survives_restart(tmp_path):
    """重启续号：变更号不回退，实体戳保留，新写继续上涨。"""

    async def fn():
        engine = await _engine(tmp_path)
        wolf = await engine.place_entity("wolf", "default", 0, 0)
        await engine.set_attrs(wolf.id, {"hp": 9})
        entity_rev = wolf.revision
        rev_before = engine.revision
        # 结构性变更（不动实体）也要算进去：拷贝一张地图（含实体）后立刻退出
        await engine.create_map("m2", "二图")
        rev_before = engine.revision
        assert rev_before > entity_rev
        await engine.terminate()

        engine2 = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine2.initialize()
        try:
            assert engine2.revision >= rev_before  # 绝不回退
            assert engine2.get_entity(wolf.id).revision == entity_rev
            await engine2.set_attrs(wolf.id, {"hp": 10})
            assert engine2.get_entity(wolf.id).revision > rev_before
            # 游标语义：按刚读到的号查，老实体不会被当成"刚改过"（漏报是唯一不可接受的）
            cursor = engine2.revision
            assert engine2.query_entities(changed_since_revision=cursor) == []
        finally:
            await engine2.terminate()

    _run(fn())


def test_event_payload_carries_revision_and_tick(tmp_path):
    """SSE payload 带全局 revision/tick（客户端缓存失效的坐标）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            wolf = await engine.place_entity("wolf", "default", 0, 0)
            queue = engine.subscribe()
            await engine.set_attrs(wolf.id, {"hp": 1})
            payload = queue.get_nowait()
            assert payload["event"] == "on_entity_changed"
            assert payload["revision"] == engine.revision
            assert payload["tick"] == engine.tick
            assert payload["entity"]["revision"] == wolf.revision
            assert payload["changed"] == {"attrs": {"hp": 1}}
        finally:
            await engine.terminate()

    _run(fn())


def test_entity_dict_carries_revision(tmp_path):
    """实体序列化带上两字段（/state、场景、日志、工具返回都自动获得）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            wolf = await engine.place_entity("wolf", "default", 0, 0)
            data = wolf.to_dict()
            assert data["revision"] == wolf.revision
            assert data["changed_tick"] == wolf.changed_tick
        finally:
            await engine.terminate()

    _run(fn())
