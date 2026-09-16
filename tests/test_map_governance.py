"""地图治理（v0.4.0）：组织树排序 / 地图搬家与跨世界 / 复制另存 / 地图体检。

回归背景：v0.3.0 把「世界 → 组织树 → 地图」的归属做出来了，但治理能力只有
"建文件夹 + 改名 + 归属"，且 `world_maps` 没有排序列——

1. 前端只渲染两层文件夹，第三层在 UI 里根本看不见（页面 bug，本模块守内核侧）
2. 文件夹与地图没有**统一序号空间**，"同级排序"无从谈起
3. 地图不能跨世界搬家、不能复制另存
4. 死连接/出生点落空这类问题运行时是**静默剔除**的，没有任何提前告知通道

本模块守住内核语义（管理端 REST 只是转发）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from world_fixtures import seed_test_world

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import Entity
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path, *, db: str = "world.db") -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / db))
    await engine.initialize()
    return engine


async def _world_with_two_maps(engine: WorldEngine) -> None:
    """铺一个两世界的世界：world_a（两张图 + 两个文件夹）、world_b。"""
    await engine.create_world("world_a", "甲世界")
    await engine.create_world("world_b", "乙世界")
    await seed_test_world(engine, map_id="m1")
    await engine.create_map("m2", "第二张图", spawn_row=0, spawn_col=0)
    await engine.create_location("m2", 0, 0, "广场")
    await engine.create_location("m2", 0, 1, "东街")


# ---------- 组织树排序 ----------


def test_sort_space_is_shared_and_appends(tmp_path):
    """新条目排到末尾；文件夹与地图共用一个序号空间。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            f1 = await engine.create_folder("world_a", "第一层")
            await engine.assign_map("m1", "world_a", folder_id=f1.id)
            f2 = await engine.create_folder("world_a", "第二层")
            await engine.assign_map("m2", "world_a", folder_id=f2.id)

            # 世界根：先建的排前面
            assert engine.list_maps_by_folder("world_a", None) == []
            root_folders = engine.list_folders("world_a")
            assert [f.name for f in root_folders] == ["第一层", "第二层"]
            assert [f.sort for f in root_folders] == [0, 1]

            # 同一节点内：文件夹与地图插在一起也各占一个序号
            late = await engine.create_folder("world_a", "晚到的")
            assert late.sort == 2
            assert engine.store.map_sort["m1"] == 0
            assert engine.store.map_sort["m2"] == 0
        finally:
            await engine.terminate()

    _run(fn())


def test_reorder_tree_sets_order_and_keeps_unlisted_after(tmp_path):
    """批量重排：列出的按给定顺序占 0..n-1，未列出的跟在后面保持相对顺序。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            a = await engine.create_folder("world_a", "A")
            b = await engine.create_folder("world_a", "B")
            c = await engine.create_folder("world_a", "C")
            await engine.assign_map("m1", "world_a")

            await engine.reorder_tree(
                "world_a",
                None,
                [{"type": "folder", "id": c.id}, {"type": "map", "id": "m1"}],
            )
            assert engine.list_folders("world_a")[0].id == c.id
            assert engine.store.map_sort["m1"] == 1
            # 未列出的 A、B 排在后面，相对顺序不变（A→0 号位被挤到 2、3）
            rest = [f.id for f in engine.list_folders("world_a")[1:]]
            assert rest == [a.id, b.id]
        finally:
            await engine.terminate()

    _run(fn())


def test_reorder_rejects_item_outside_parent(tmp_path):
    """跨容器的条目报错（防止 UI 状态错乱时静默改错结构）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            a = await engine.create_folder("world_a", "A")
            inner = await engine.create_folder("world_a", "内层", parent_id=a.id)
            await engine.assign_map("m1", "world_a", folder_id=inner.id)
            try:
                await engine.reorder_tree(
                    "world_a", None, [{"type": "folder", "id": inner.id}]
                )
            except WorldError as e:
                assert "不在该组织节点下" in str(e)
            else:
                raise AssertionError("应当拒绝跨容器排序项")
            try:
                await engine.reorder_tree(
                    "world_a", None, [{"type": "map", "id": "m1"}]
                )
            except WorldError as e:
                assert "不在该组织节点下" in str(e)
            else:
                raise AssertionError("应当拒绝跨容器排序项")
        finally:
            await engine.terminate()

    _run(fn())


def test_sort_survives_reload(tmp_path):
    """排序落盘：重开引擎顺序不变（world_maps.sort 是持久列）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            await engine.create_map("m3", "第三张图")
            await engine.assign_map("m1", "world_a")
            await engine.assign_map("m2", "world_a")
            await engine.assign_map("m3", "world_a")
            await engine.reorder_tree(
                "world_a",
                None,
                [
                    {"type": "map", "id": "m3"},
                    {"type": "map", "id": "m1"},
                    {"type": "map", "id": "m2"},
                ],
            )
            assert engine.list_maps_by_folder("world_a", None) == ["m3", "m1", "m2"]
        finally:
            await engine.terminate()
        again = await _engine(tmp_path)
        try:
            assert again.list_maps_by_folder("world_a", None) == ["m3", "m1", "m2"]
        finally:
            await again.terminate()

    _run(fn())


# ---------- 地图搬家（含跨世界） ----------


def test_move_map_across_worlds_drops_old_folder(tmp_path):
    """跨世界搬家：旧组织节点不属于新世界，自动落到世界根。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            folder = await engine.create_folder("world_a", "甲组")
            await engine.assign_map("m1", "world_a", folder_id=folder.id)
            assert engine.store.map_folder["m1"] == folder.id

            await engine.move_map("m1", world_id="world_b")
            assert engine.map_world("m1") == "world_b"
            assert engine.store.map_folder["m1"] is None
        finally:
            await engine.terminate()

    _run(fn())


def test_move_map_to_root_and_unassign(tmp_path):
    """folder_id=None 回世界根；world_id=None 解除归属。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            folder = await engine.create_folder("world_a", "甲组")
            await engine.assign_map("m1", "world_a", folder_id=folder.id)
            await engine.move_map("m1", folder_id=None)
            assert engine.store.map_folder["m1"] is None
            assert engine.map_world("m1") == "world_a"

            await engine.move_map("m1", world_id=None)
            assert engine.map_world("m1") is None
            assert engine.store.map_sort.get("m1") is None
        finally:
            await engine.terminate()

    _run(fn())


def test_move_map_rejects_folder_of_other_world(tmp_path):
    """不能把地图放进别的世界的组织节点。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            folder = await engine.create_folder("world_b", "乙组")
            await engine.assign_map("m1", "world_a")
            try:
                await engine.move_map("m1", world_id="world_a", folder_id=folder.id)
            except WorldError as e:
                assert "不属于该世界" in str(e)
            else:
                raise AssertionError("应当拒绝跨世界的组织节点")
        finally:
            await engine.terminate()

    _run(fn())


def test_assign_map_keeps_position_within_same_folder(tmp_path):
    """同世界同节点重复归属保留原位；换节点排到末尾。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            await engine.assign_map("m1", "world_a")
            await engine.assign_map("m2", "world_a")
            assert engine.store.map_sort["m1"] == 0
            assert engine.store.map_sort["m2"] == 1
            await engine.assign_map("m1", "world_a")  # 重挂同节点
            assert engine.store.map_sort["m1"] == 0
            await engine.assign_map("m1", "world_a", folder_id=None)
            assert engine.store.map_sort["m1"] == 0  # 同容器（根）

            folder = await engine.create_folder("world_a", "甲组")
            assert folder.sort == 2  # 根里已有 m1（0）、m2（1）
            await engine.assign_map("m1", "world_a", folder_id=folder.id)
            assert engine.store.map_sort["m1"] == 0  # 新容器里第一个
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 地图复制另存 ----------


def test_copy_map_rewrites_same_map_targets(tmp_path):
    """副本内自洽：同图目标落到副本自己，跨图目标原样保留。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            await engine.assign_map("m1", "world_a")
            # m1 中央广场 → 东街（同图）+ 一条指向 m2 的跨图路径
            await engine.update_connection(
                "m1",
                0,
                1,
                "right",
                enabled=True,
                paths=[
                    {"targets": [{"map_id": "m2", "row": 0, "col": 1}]},
                ],
            )
            await engine.copy_map("m1", "m1_copy")
            assert engine.map_world("m1_copy") == "world_a"
            # 地块数一致
            src = [x for x in engine.list_locations() if x.map_id == "m1"]
            dst = [x for x in engine.list_locations() if x.map_id == "m1_copy"]
            assert len(src) == len(dst) == 5
            # 同图目标：指向副本自己（map_id 空 = 当前地图）
            east = engine.get_location("m1_copy", 0, 1)
            path = east.connections["right"].paths[0]
            assert path.targets[0].map_id == "m2"  # 跨图目标保留
            center = engine.get_location("m1_copy", 0, 0)
            up = center.connections["up"].paths[0]
            assert up.targets[0].map_id == ""  # 同图 → 副本自己
            assert (up.targets[0].row, up.targets[0].col) == (-1, 0)
        finally:
            await engine.terminate()

    _run(fn())


def test_copy_map_entities_optional_and_players_excluded(tmp_path):
    """实体可选带过去；身份化实体（玩家）永不复制。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            await engine.place_entity("merchant", "m1", 0, 0, name="商贩")
            await engine.place_entity("player", "m1", 0, 0, name="小明")

            await engine.copy_map("m1", "no_ent")
            assert list(engine.list_entities(map_id="no_ent")) == []

            await engine.copy_map("m1", "with_ent", with_entities=True)
            copied = engine.list_entities(map_id="with_ent")
            assert [e.name for e in copied] == ["商贩"]
            assert copied[0].id != engine.list_entities(map_id="m1")[0].id
        finally:
            await engine.terminate()

    _run(fn())


def test_copy_map_duplicate_id_rejected_and_name_default(tmp_path):
    """id 冲突报错；名称缺省为「原名（副本）」。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await _world_with_two_maps(engine)
            dup = await engine.copy_map("m1", "m1_copy")
            assert dup.name == "测试世界（副本）"
            try:
                await engine.copy_map("m1", "m1_copy")
            except WorldError as e:
                assert "已存在" in str(e)
            else:
                raise AssertionError("应当拒绝重复的地图 id")
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 地图体检 ----------


def test_lint_clean_map_has_no_errors(tmp_path):
    """十字形测试世界：无错误（允许"只能作为起点"这类提示）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await seed_test_world(engine)
            await engine.assign_map("default", "default")
            report = engine.lint_map("default")
            assert report["counts"]["error"] == 0
            assert report["map_id"] == "default"
            assert report["location_count"] == 5
        finally:
            await engine.terminate()

    _run(fn())


def test_lint_reports_dead_target(tmp_path):
    """死连接：运行时整条路径静默不展示，体检必须报出来。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await seed_test_world(engine)
            await engine.assign_map("default", "default")
            await engine.update_connection(
                "default",
                0,
                0,
                "left",
                enabled=True,
                paths=[{"targets": [{"row": 9, "col": 9}]}],
            )
            report = engine.lint_map("default")
            codes = [p["code"] for p in report["problems"]]
            assert "dead_target" in codes
            dead = next(p for p in report["problems"] if p["code"] == "dead_target")
            assert dead["level"] == "error"
            assert dead["where"]["direction"] == "left"
            # 死目标所在的方向没有任何可用出口 → 同时报孤立/无出口
            assert report["counts"]["error"] >= 1
        finally:
            await engine.terminate()

    _run(fn())


def test_lint_reports_spawn_missing_and_dangling_entity(tmp_path):
    """出生点落空 + 实体悬空（数据损坏）都是 error。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.create_map("broken", "坏图", spawn_row=7, spawn_col=7)
            await engine.create_location("broken", 0, 0, "孤岛")
            await engine.assign_map("broken", "default")
            # 手工塞一个坐标上没有地块的实体（模拟数据损坏）
            await engine.store.save_entity(
                Entity(
                    id="ghost",
                    map_id="broken",
                    row=3,
                    col=3,
                    kind="sign",
                    name="幽灵",
                )
            )
            report = engine.lint_map("broken")
            codes = {p["code"] for p in report["problems"]}
            assert "spawn_missing" in codes
            assert "dangling_entity" in codes
            # 单地块图：孤立按 warn 报（可能是刚建的图）
            assert "isolated_location" in codes
            assert report["counts"]["error"] == 2
        finally:
            await engine.terminate()

    _run(fn())


def test_lint_reports_no_world_and_empty_map(tmp_path):
    """未归属世界 + 空地图。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.create_map("orphan", "孤儿图", spawn_row=0, spawn_col=0)
            report = engine.lint_map("orphan")
            codes = {p["code"] for p in report["problems"]}
            assert "no_world" in codes
            assert "empty_map" in codes
            assert report["counts"]["error"] == 0  # 空图不报出生点落空（避免噪音）
        finally:
            await engine.terminate()

    _run(fn())


def test_lint_maps_sorted_by_severity(tmp_path):
    """总检按错误数降序，坏图排前面。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await seed_test_world(engine)
            await engine.assign_map("default", "default")
            await engine.create_map("broken", "坏图", spawn_row=7, spawn_col=7)
            await engine.create_location("broken", 0, 0, "孤岛")
            await engine.assign_map("broken", "default")
            report = engine.lint_maps()
            assert report["counts"]["maps"] == 2
            assert [r["map_id"] for r in report["maps"]][0] == "broken"
            assert report["counts"]["error"] >= 1
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 管理端 REST 接线（引擎语义已验证，这里守转发与参数名） ----------


async def _admin_scenario(tmp_path: Path, fn):
    import httpx

    from worlditor_mcp.admin import build_admin_app
    from worlditor_mcp.world.identity import IdentityService

    engine = await _engine(tmp_path)
    await _world_with_two_maps(engine)
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
            return await fn(client, headers)
    finally:
        await engine.terminate()


def test_admin_endpoints_wire_governance_ops(tmp_path):
    """REST：建文件夹→排序→搬家→复制→体检→删除，全链路走管理端口。"""

    async def fn(client, h):
        # 建文件夹（新增：默认排到末尾）
        r = await client.post(
            "/admin/worlds/world_a/folders", json={"name": "甲组"}, headers=h
        )
        assert r.status_code == 200, r.text
        folder = r.json()["data"]
        assert folder["sort"] == 0

        # 归属地图（带序号）
        for i, mid in enumerate(["m1", "m2"]):
            r = await client.post(
                "/admin/worlds/world_a/assign-map",
                json={"map_id": mid, "folder_id": folder["id"], "sort": i},
                headers=h,
            )
            assert r.status_code == 200, r.text

        # 重排（倒序）
        r = await client.post(
            "/admin/worlds/world_a/reorder",
            json={
                "parent_id": folder["id"],
                "items": [
                    {"type": "map", "id": "m2"},
                    {"type": "map", "id": "m1"},
                ],
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        worlds = (await client.get("/admin/worlds", headers=h)).json()["worlds"]
        wa = next(w for w in worlds if w["id"] == "world_a")
        order = sorted(
            [m for m in wa["maps"] if m["folder_id"] == folder["id"]],
            key=lambda m: m["sort"],
        )
        assert [m["id"] for m in order] == ["m2", "m1"]

        # 文件夹改名 + 改序号（PATCH 一个端点两件事）
        r = await client.patch(
            f"/admin/folders/{folder['id']}",
            json={"name": "甲组改", "sort": 5},
            headers=h,
        )
        assert r.status_code == 200, r.text

        # 复制另存（带实体开关；副本落在源地图同世界同节点）
        r = await client.post(
            "/admin/maps/m1/copy",
            json={"new_id": "m1_copy", "with_entities": True},
            headers=h,
        )
        assert r.status_code == 200, r.text
        detail = (await client.get("/admin/maps/m1_copy", headers=h)).json()
        assert detail["map"]["world_id"] == "world_a"
        assert len(detail["locations"]) == 5

        # 跨世界搬家（world_id 换掉，folder 自动回世界根）
        r = await client.post(
            "/admin/maps/m1_copy/move", json={"world_id": "world_b"}, headers=h
        )
        assert r.status_code == 200, r.text
        moved = (await client.get("/admin/maps/m1_copy", headers=h)).json()["map"]
        assert moved["world_id"] == "world_b"
        assert moved["folder_id"] is None

        # 解除归属
        r = await client.post(
            "/admin/maps/m1_copy/move", json={"world_id": None}, headers=h
        )
        assert r.status_code == 200, r.text
        assert (await client.get("/admin/maps/m1_copy", headers=h)).json()["map"][
            "world_id"
        ] is None

        # 体检（单张 + 全量）
        r = await client.get("/admin/lint?map_id=m2", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["maps"][0]["map_id"] == "m2"
        r = await client.get("/admin/lint", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["counts"]["maps"] == 3  # m1 / m2 / m1_copy

        # 删除地图
        r = await client.delete("/admin/maps/m1_copy", headers=h)
        assert r.status_code == 200, r.text
        assert "地图不存在" in (await client.get("/admin/maps/m1_copy", headers=h)).text

    _run(_admin_scenario(tmp_path, fn))


def test_admin_folders_list_carries_sort_and_map_meta(tmp_path):
    """侧栏/树需要的元数据：文件夹 sort、地图 folder_id + sort。"""

    async def fn(client, h):
        data = (await client.get("/admin/maps", headers=h)).json()["maps"]
        m1 = next(m for m in data if m["id"] == "m1")
        assert "folder_id" in m1 and "sort" in m1
        worlds = (await client.get("/admin/worlds", headers=h)).json()["worlds"]
        wa = next(w for w in worlds if w["id"] == "world_a")
        assert all("sort" in m for m in wa["maps"])

    _run(_admin_scenario(tmp_path, fn))
