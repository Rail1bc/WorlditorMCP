"""世界与组织测试（D15）：worlds/folders/maps 归属 + play_data 双层隔离。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import World, WorldFolder
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.store import DEFAULT_WORLD_ID, WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


def test_default_world_seeded(tmp_path):
    """空库播种：默认世界 + 种子地图归属。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            world = engine.get_world(DEFAULT_WORLD_ID)
            assert world is not None and world.name == "默认世界"
            assert world.play_ids == []  # 空 = 全部激活
            assert engine.map_world("default") == DEFAULT_WORLD_ID
            assert engine.entity_world(engine.list_entities()[0].id) == DEFAULT_WORLD_ID
        finally:
            await engine.terminate()

    _run(fn())


def test_world_crud_and_activation(tmp_path):
    """世界 CRUD + 激活集合更新。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            world = await engine.create_world(
                "pvp", "竞技世界", desc="战斗", play_ids=["worlditor_play_fight"]
            )
            assert isinstance(world, World)
            assert engine.get_world("pvp").play_ids == ["worlditor_play_fight"]
            # 更新激活集合
            await engine.update_world("pvp", play_ids=[])
            assert engine.get_world("pvp").play_ids == []
            assert {w.id for w in engine.list_worlds()} == {DEFAULT_WORLD_ID, "pvp"}
            # 重复创建报错
            with pytest.raises(WorldError, match="已存在"):
                await engine.create_world("pvp", "again")
            # 空世界可删
            await engine.delete_world("pvp")
            assert engine.get_world("pvp") is None
        finally:
            await engine.terminate()

    _run(fn())


def test_delete_world_guarded(tmp_path):
    """删除仍有地图归属的世界 → 拒绝。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.create_world("w2", "二")
            # 把种子地图归属到 w2（覆盖默认归属）
            await engine.assign_map("default", "w2")
            with pytest.raises(WorldError, match="仍有地图"):
                await engine.delete_world("w2")
            # 移走后可删
            await engine.unassign_map("default")
            await engine.delete_world("w2")
            assert engine.map_world("default") is None  # 地图保留但无归属
        finally:
            await engine.terminate()

    _run(fn())


def test_folders_tree(tmp_path):
    """组织树：创建/移动/防环/非空删除保护/地图挂载。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            root = await engine.create_folder(DEFAULT_WORLD_ID, "新手村")
            sub = await engine.create_folder(
                DEFAULT_WORLD_ID, "副本", parent_id=root.id, sort=1
            )
            assert isinstance(root, WorldFolder)
            # 地图挂到子文件夹
            await engine.assign_map("default", DEFAULT_WORLD_ID, folder_id=sub.id)
            assert engine.list_maps_by_folder(DEFAULT_WORLD_ID, sub.id) == ["default"]
            assert engine.list_maps_by_folder(DEFAULT_WORLD_ID) == []  # 世界根无地图
            # 防环：root 不能移到 sub 下
            with pytest.raises(WorldError, match="后代"):
                await engine.move_folder(root.id, sub.id)
            # 非空拒绝：sub 有地图；root 有子文件夹
            with pytest.raises(WorldError, match="仍有地图"):
                await engine.delete_folder(sub.id)
            with pytest.raises(WorldError, match="子文件夹"):
                await engine.delete_folder(root.id)
            # 移动地图到世界根后 sub 可删；root 随之清空可删
            await engine.move_map_folder("default", None)
            await engine.delete_folder(sub.id)
            await engine.delete_folder(root.id)
            # 跨世界父节点拒绝
            await engine.create_world("w3", "三")
            with pytest.raises(WorldError, match="父文件夹"):
                await engine.create_folder("w3", "x", parent_id=root.id)
            await engine.delete_world("w3")
            assert engine.list_folders(DEFAULT_WORLD_ID) == []
        finally:
            await engine.terminate()

    _run(fn())


def test_play_kv_world_isolation(tmp_path):
    """play_data 双层隔离：同玩法包不同世界各自状态。"""

    async def fn():
        engine = await _engine(tmp_path)
        loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
        await loader.load_all()
        try:
            from worlditor_mcp.world.play.api import WorlditorPlayAPI

            pkg = WorlditorPlayAPI(engine, "test_pkg")
            await pkg.kv_set("counter", 1)
            await pkg.kv_set("counter", 10, world_id=DEFAULT_WORLD_ID)
            await pkg.kv_set("counter", 99, world_id="other")
            assert pkg.kv_get("counter") == 1  # 全局
            assert pkg.kv_get("counter", world_id=DEFAULT_WORLD_ID) == 10
            assert pkg.kv_get("counter", world_id="other") == 99
            # 双层 = (world, play) 隔离：不同包同世界互不干扰
            pkg2 = WorlditorPlayAPI(engine, "test_pkg2")
            assert pkg2.kv_get("counter", world_id=DEFAULT_WORLD_ID) is None
        finally:
            await engine.terminate()

    _run(fn())
