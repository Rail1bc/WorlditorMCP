"""v4 存储层测试（v4store.py）：表结构、播种、CRUD、world_log 容量、v3 共存。"""

from __future__ import annotations

import asyncio
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from worlditor_mcp.world import ItemDef  # noqa: E402
from worlditor_mcp.world.store import (  # noqa: E402
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
    """v4 播种：v3 世界（41 地块）+ v4 实体/物品。"""

    async def fn():
        store = await _make_store(tmp_path / "world.db")
        try:
            assert len(store.loc_by_pos) == 41
            assert len(store.maps) == 1
            assert len(store.entities) == 3
            assert len(store.items) == 1
            assert "megaphone" in store.items
            assert "apple" not in store.items
            # 索引生效（不报错即可）
            cur = await store._conn.execute(
                "SELECT COUNT(*) AS n FROM entities WHERE map_id=? AND row=? AND col=?",
                ("default", 0, 0),
            )
            assert (await cur.fetchone())["n"] == 1
        finally:
            await store.close()

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


def test_item_save(tmp_path):
    """物品定义：save（定义随玩法包注册/刷新；内核无删除 API）。"""

    async def fn():
        store = await _make_store(tmp_path / "world.db")
        try:
            await store.save_item(ItemDef(id="sword_01", name="木剑"))
            assert "sword_01" in store.items
        finally:
            await store.close()

    _run(fn())
