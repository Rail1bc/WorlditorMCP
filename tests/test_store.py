"""v4 存储层测试（v4store.py）：表结构、播种、CRUD、world_log 容量、v3 共存。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from world_fixtures import install_demo_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine  # noqa: E402
from worlditor_mcp.world.store import (  # noqa: E402
    DEFAULT_WORLD_ID,
    WORLD_LOG_LIMIT,
    WorldStore,  # noqa: E402
)


def _run(coro):
    return asyncio.run(coro)


async def _make_store(db_path: Path) -> WorldStore:
    store = WorldStore(db_path)
    await store.initialize()
    return store


def test_seed_tables(tmp_path):
    """v4 播种（v0.2.0）：空库只建「默认世界」容器——0 地图/0 地块/0 实体。"""

    async def fn():
        store = await _make_store(tmp_path / "world.db")
        try:
            # 内核不再内置世界内容（旧的 41 地块演示世界已移入内置世界包）
            assert len(store.maps) == 0
            assert len(store.loc_by_pos) == 0
            assert len(store.entities) == 0
            # 只播种「默认世界」这一结构性容器
            assert list(store.worlds) == [DEFAULT_WORLD_ID]
            assert store.worlds[DEFAULT_WORLD_ID].name == "默认世界"
            # v2：原 items 表与 item 断言已随 D37 移除（见 tests/test_v2_components.py）
            assert not hasattr(store, "items")
            # 按位置查实体：**v10 起位置在 components_json 里**（core:position），
            # SQL 侧得用 json_extract——这正是"全部数据进 JSON 后手查变难"的代价，
            # 但内存侧（引擎 API）不受影响，位置筛选照旧
            cur = await store._conn.execute(
                "SELECT COUNT(*) AS n FROM entities "
                "WHERE json_extract(components_json, '$.\"core:position\".map_id') = ? "
                "AND json_extract(components_json, '$.\"core:position\".row') = ? "
                "AND json_extract(components_json, '$.\"core:position\".col') = ?",
                ("default", 0, 0),
            )
            assert (await cur.fetchone())["n"] == 0
        finally:
            await store.close()

        # 世界内容改由内置世界包导入：演示世界 → 41 地块 + 3 静态实体
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await install_demo_world(engine)
            assert len(engine.store.maps) == 1
            assert len(engine.store.loc_by_pos) == 41
            assert len(engine.store.entities) == 3
            # 按位置查实体可用（同 test_seed_tables：位置在 JSON 里，走 json_extract）
            cur = await engine.store._conn.execute(
                "SELECT COUNT(*) AS n FROM entities "
                "WHERE json_extract(components_json, '$.\"core:position\".map_id') = ? "
                "AND json_extract(components_json, '$.\"core:position\".row') = ? "
                "AND json_extract(components_json, '$.\"core:position\".col') = ?",
                ("default", 0, 0),
            )
            assert (await cur.fetchone())["n"] == 1
        finally:
            await engine.terminate()

    _run(fn())


def test_play_data_kv(tmp_path):
    """玩法 KV：namespace 隔离、JSON 往返。"""

    async def fn():
        store = await _make_store(tmp_path / "world.db")
        try:
            await store.set_play_kv("ns1", "k", {"a": [1, 2, "x"]})
            await store.set_play_kv("ns2", "k", "other")
            assert store.play_data[("ns1", "k")] == {"a": [1, 2, "x"]}
            assert store.play_data[("ns2", "k")] == "other"
        finally:
            await store.close()

    _run(fn())


def test_world_log_capacity(tmp_path):
    """world_log 容量：超 5000 自动清理最旧。"""

    async def fn():
        store = await _make_store(tmp_path / "world.db")
        try:
            for i in range(WORLD_LOG_LIMIT + 50):
                await store.append_world_log(float(i), None, "on_say", {"n": i})
            logs = await store.list_world_log(limit=10**6)
            assert len(logs) == WORLD_LOG_LIMIT
            assert logs[0]["data"]["n"] == WORLD_LOG_LIMIT + 49  # 最新保留
            assert logs[-1]["data"]["n"] == 50  # 最旧 50 条已清
        finally:
            await store.close()

    _run(fn())


def test_legacy_shape_without_version_record_is_refused(tmp_path):
    """v2 版本闸的第二道：**没有 schema_version 记录**的老库/手造库也要被明确拒绝。

    只靠"版本值不对"那一道，这种库会一路走到 ``_load_all`` 撞出裸 ``IndexError``
    （一屏栈、没有"删哪个文件"的指引），违背 D13 的承诺。这里的库是**混合形态**：
    ``entities`` 有 ``components_json`` 但缺 v0.5/v0.6 那三列，``world_maps`` 缺 ``sort``
    ——确认报的是 ``IncompatibleDataError``、**把真缺的列一次报全**、
    且**不误报已有的列**。
    """
    import sqlite3

    from worlditor_mcp.world.errors import IncompatibleDataError

    db = tmp_path / "world.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE world_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, map_id TEXT NOT NULL, row INTEGER NOT NULL,
            col INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
            components_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE world_maps (map_id TEXT PRIMARY KEY, world_id TEXT NOT NULL);
        """
    )
    conn.commit()
    conn.close()

    async def fn():
        store = WorldStore(db)
        try:
            await store.initialize()
            pytest.fail("旧形态库竟然启动成功")
        except IncompatibleDataError as exc:
            msg = str(exc)
            assert "world.db" in msg  # 指明该删哪个文件
            # 真缺的列一次报全（不只在第一处停下）
            assert "world_maps.sort" in msg
            assert "entities.tags_json" in msg
            assert "entities.revision" in msg
            # 已有的列不误报
            assert "entities.components_json" not in msg
        finally:
            await store.close()

    _run(fn())
