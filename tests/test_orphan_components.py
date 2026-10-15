"""组件四象限诊断与孤儿清理（D44 / G48）。

背景：D41 之后**能力 = 组件的存在**，而组件会**留在实体上**——卸载一个玩法包
只是撤掉它的注册（声明 / 动作 / 字段），实体上的组件一个字节都不动。于是要能回答
两个问题：

1. **"这个组件为什么没效果？"** —— 四象限（D44）：
   - `active`：声明在，且该实体所在世界启用了声明者（或声明者无归属）；
   - `inactive`：声明在、包已加载，但这个世界没启用它（启用即恢复）；
   - `orphan`：**声明它的包不在了**——停用 / 加载失败 / 已被卸载（规格可能还在，
     也可能已经随真卸载被清掉）；
   - `fictional`：`local:` 且查无声明——**本来就没有行为，不是坏了**。

2. **"永久孤儿怎么办？"** —— 清理（D44 / G48）：**只有"包真不在了"才能清**，
   停用与加载失败都不行（启用 / 修好即恢复）；`local:` **永不可清**（读不出归属，
   可能是人手写的数据）；必须管理员手动 + **先 dry-run**；粒度按 source 或 keys，
   **不支持按实体挑**；清理是**双重不可逆**（数据没了 + 该实体的能力也没了）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from world_fixtures import seed_test_world

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.model import CORE_POSITION
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


# 真实 PlayLoader 只发现 `worlditor_play_` 前缀的目录（loader 的命名规则）
PLAY_ID = "worlditor_play_duel"


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    return engine


def _attach(engine: WorldEngine, play_id: str) -> WorlditorPlayAPI:
    """模拟"包已加载"（真加载走 PlayLoader；这里只关心引擎看见的状态）。"""
    api = WorlditorPlayAPI(engine, play_id)
    engine.attach_play_api(play_id, api)
    return api


def _package_state(mapping: dict[str, str]):
    """包状态解析器（管理端会用 PlayLoader 的 list_plays 结果构造它）。"""
    return lambda source: mapping.get(source, "uninstalled")


# ---------- 四象限 ----------


def test_quadrants_distinguish_inactive_orphan_and_fictional(tmp_path):
    """四象限互不混淆：启用 / 未启用 / 包不在了 / 从来没有行为。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            # a：已加载 + 世界启用 → active；b：已加载 + 世界没启用 → inactive
            engine.declare_component("cap_a", play_id="pkg_a")
            engine.declare_component("cap_b", play_id="pkg_b")
            _attach(engine, "pkg_a")
            _attach(engine, "pkg_b")
            # c：声明在、但包没加载（停用 / 加载失败）→ orphan
            engine.declare_component("cap_c", play_id="pkg_c")
            # d：包已被真卸载——规格都没了，只剩实体上的键 → orphan
            await engine.create_world("w_a", "只有A", play_ids=["pkg_a"])
            await engine.create_map("m_a", "甲图")
            await engine.create_location("m_a", 0, 0, "格")
            await engine.assign_map("m_a", "w_a")

            e = await engine.place_entity(
                None,
                "m_a",
                0,
                0,
                components={
                    "pkg_a:cap_a": {},
                    "pkg_b:cap_b": {},
                    "pkg_c:cap_c": {},
                    "pkg_gone:cap": {},
                    "local:mine": {"note": 1},
                },
            )
            caps = engine.capabilities(e)
            assert caps["active_components"] == ["pkg_a:cap_a"]
            assert caps["inactive_components"] == ["pkg_b:cap_b"]
            assert set(caps["orphan_components"]) == {"pkg_c:cap_c", "pkg_gone:cap"}
            assert caps["fictional_components"] == ["local:mine"]
            # 只有 active 贡献动作 / 字段
            assert engine.component_origin("pkg_a:cap_a", "w_a") == "active"
            assert engine.component_origin("pkg_b:cap_b", "w_a") == "inactive"
            assert engine.component_origin("pkg_c:cap_c", "w_a") == "orphan"
            assert engine.component_origin("pkg_gone:cap", "w_a") == "orphan"
            assert engine.component_origin("local:mine", "w_a") == "fictional"

            # 把世界改成启用 b：b 从 inactive 变 active
            await engine.update_world("w_a", play_ids=["pkg_a", "pkg_b"])
            assert engine.capabilities(e)["active_components"] == [
                "pkg_a:cap_a",
                "pkg_b:cap_b",
            ]
        finally:
            await engine.terminate()

    _run(fn())


def test_disabled_package_components_are_orphan_not_unknown(tmp_path):
    """停用（规格保留）→ 组件算**孤儿**（包没加载），不是"未声明"，也不是"未启用"。

    这条同时守住 C8：停用**不删规格**——否则 `capabilities()` 会把它误报成
    "从来没有声明过"，与 query 的解释对不上。
    """

    async def fn():
        engine = await _engine(tmp_path)
        try:
            api = _attach(engine, "pkg_b")
            engine.declare_component("duel", interactions=("fight",), play_id="pkg_b")
            e = await engine.place_entity(
                None, "default", 0, 0, components={"pkg_b:duel": {}}
            )
            assert engine.capabilities(e)["interactions"] == ["fight"]

            engine.clear_play_registrations("pkg_b")  # 停用：不 purge
            engine.detach_play_api("pkg_b")
            caps = engine.capabilities(e)
            assert caps["active_components"] == []
            assert caps["orphan_components"] == ["pkg_b:duel"]
            assert caps["fictional_components"] == []
            # 规格还在（C8）→ 重新启用即恢复
            _attach(engine, "pkg_b")
            assert api is not None
            assert engine.capabilities(e)["interactions"] == ["fight"]
        finally:
            await engine.terminate()

    _run(fn())


def test_query_still_matches_uninstalled_components(tmp_path):
    """真卸载后组件回到"无声明"→ query 照常匹配（D26 的既定语义）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.declare_component("late", interactions=("poke",), play_id="pkg_x")
            _attach(engine, "pkg_x")
            e = await engine.place_entity("slime", "default", 0, 0, tags=["late"])
            assert {x.id for x in engine.query_entities(tags=["pkg_x:late"])} == {e.id}
            engine.clear_play_registrations("pkg_x", purge=True)
            engine.detach_play_api("pkg_x")
            # 规格没了 = 没有声明者 → "组件即数据"照常匹配
            assert {x.id for x in engine.query_entities(tags=["pkg_x:late"])} == {e.id}
            assert engine.capabilities(e)["orphan_components"] == ["pkg_x:late"]
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 诊断报告（按 source 聚合） ----------


def test_diagnose_components_groups_by_source(tmp_path):
    """报告按 source 分组：keys / count / sample / package / purgeable。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.declare_component("stat", play_id="pkg_gone")
            _attach(engine, "pkg_live")
            engine.declare_component("wolf", play_id="pkg_live")
            for row in range(4):
                await engine.place_entity(
                    None,
                    components={"pkg_gone:stat": {"hp": row}, "pkg_live:wolf": {}},
                )
            await engine.place_entity(None, components={"local:note": {"x": 1}})
            engine.clear_play_registrations("pkg_gone", purge=True)  # 包被卸载

            report = {
                row["source"]: row
                for row in engine.diagnose_components(
                    _package_state({"pkg_live": "loaded"})
                )
            }
            gone = report["pkg_gone"]
            assert gone["state"] == "orphan" and gone["package"] == "uninstalled"
            assert gone["purgeable"] is True
            assert gone["keys"] == ["pkg_gone:stat"]
            assert gone["count"] == 4 and len(gone["sample"]) == 3

            live = report["pkg_live"]
            assert live["state"] == "active" and live["purgeable"] is False
            mine = report["local"]
            assert mine["state"] == "fictional" and mine["purgeable"] is False
            # core: 不进报告（内核协议数据不是能力）
            assert "core" not in report
        finally:
            await engine.terminate()

    _run(fn())


def test_diagnose_marks_disabled_and_load_failed_not_purgeable(tmp_path):
    """停用 / 加载失败：**都不许清**（包还在，启用 / 修好即恢复）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.declare_component("duel", play_id="pkg_off")
            await engine.place_entity(None, components={"pkg_off:duel": {}})
            for package, state in (
                ("disabled", "disabled"),
                ("load_failed", "load_failed"),
            ):
                report = engine.diagnose_components(
                    _package_state({"pkg_off": package})
                )
                row = next(r for r in report if r["source"] == "pkg_off")
                assert row["state"] == "orphan"
                assert row["package"] == state
                assert row["purgeable"] is False  # 包还在 → 界面不给按钮、服务端也拒
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 清理原语 ----------


def test_purge_requires_really_uninstalled_package(tmp_path):
    """服务端强制：停用 / 加载失败 → 拒绝；`local:` 永不可清。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.declare_component("duel", play_id="pkg_off")
            e = await engine.place_entity(
                None,
                "default",
                0,
                0,
                components={"pkg_off:duel": {}, "local:note": {"x": 1}},
            )
            for state in ("disabled", "load_failed", "loaded"):
                with pytest.raises(WorldError, match="还在"):
                    await engine.purge_components(
                        "pkg_off",
                        dry_run=False,
                        package_state=_package_state({"pkg_off": state}),
                    )
            with pytest.raises(WorldError, match="local"):
                await engine.purge_components(
                    "local", dry_run=False, package_state=_package_state({})
                )
            # 拒绝之后实体数据一个字节都没动
            assert e.has_component("pkg_off:duel") and e.has_component("local:note")
        finally:
            await engine.terminate()

    _run(fn())


def test_purge_dry_run_then_delete_and_emit(tmp_path):
    """先 dry-run 看影响面，再真删；只删指定 source 的键，落库并广播事件。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            engine.declare_component("stat", play_id="pkg_gone")
            keep = await engine.place_entity(None, "default", 0, 0)
            target = await engine.place_entity(
                None,
                "default",
                1,
                0,
                components={
                    "pkg_gone:stat": {"hp": 1},
                    "pkg_gone:extra": {},
                    "local:note": {"x": 1},
                },
            )
            engine.clear_play_registrations("pkg_gone", purge=True)
            events: list[dict] = []
            engine.register_world_event(
                "on_world_edited", lambda api, data: events.append(data)
            )

            # dry-run（默认）：只报影响面，不动数据
            preview = await engine.purge_components(
                "pkg_gone", package_state=_package_state({})
            )
            assert preview["dry_run"] is True and preview["purged"] is False
            assert preview["keys"] == ["pkg_gone:extra", "pkg_gone:stat"]
            assert preview["count"] == 1 and preview["entities"] == [target.id]
            assert target.has_component("pkg_gone:stat")

            # keys 子集：只清一个
            await engine.purge_components(
                "pkg_gone",
                keys=["pkg_gone:stat"],
                dry_run=False,
                package_state=_package_state({}),
            )
            assert not target.has_component("pkg_gone:stat")
            assert target.has_component("pkg_gone:extra")  # 没点名的留下
            assert target.has_component("local:note")  # local: 永远不碰
            assert events[-1] == {
                "op": "purge_components",
                "source": "pkg_gone",
                "keys": ["pkg_gone:stat"],
                "entities": 1,
            }

            # 全清：剩下的 extra 一起走
            await engine.purge_components(
                "pkg_gone", dry_run=False, package_state=_package_state({})
            )
            assert not target.has_component("pkg_gone:extra")
            assert keep.components.get(CORE_POSITION)  # 无关实体没被动过

            # 跨重启仍在（落库走 save_entities）
        finally:
            await engine.terminate()
        again = WorldEngine(WorldStore(tmp_path / "world.db"))
        await again.initialize()
        try:
            stored = again.store.entities[target.id]
            assert not any(k.startswith("pkg_gone:") for k in stored.components)
            assert stored.has_component("local:note")
        finally:
            await again.terminate()

    _run(fn())


def test_purge_rejects_keys_from_other_source(tmp_path):
    """keys 子集必须属于该 source——否则等于绕开"按来源清"的约束。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await engine.place_entity(
                None,
                "default",
                0,
                0,
                components={"pkg_gone:stat": {}, "other:thing": {}},
            )
            with pytest.raises(WorldError, match="不属于"):
                await engine.purge_components(
                    "pkg_gone",
                    keys=["other:thing"],
                    dry_run=False,
                    package_state=_package_state({}),
                )
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 真实 PlayLoader 全链路（停用 → 卸载 → 清理） ----------


def _install_play(plays_root: Path, play_id: str) -> Path:
    # 目录名必须以 `worlditor_play_` 开头（loader 的发现规则）
    assert play_id.startswith("worlditor_play_")
    play_dir = plays_root / play_id
    play_dir.mkdir(parents=True, exist_ok=True)
    (play_dir / "play.yaml").write_text(
        f"name: {play_id}\n"
        "display_name: 四象限测试包\n"
        "version: 0.1.0\n"
        "author: test\n"
        "requires:\n"
        '  worlditor: ">=0.3.0"\n'
        "  plays: []\n",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(
        "def setup(api, context):\n"
        '    api.declare_component("duel", interactions=("fight",), label="决斗")\n',
        encoding="utf-8",
    )
    return play_dir


def test_loader_full_chain_disable_then_uninstall(tmp_path):
    """走真实 PlayLoader：停用**不可清**，卸载后可清（判定先看目录在不在）。"""

    async def fn():
        engine = await _engine(tmp_path)
        loader = PlayLoader(
            engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0"
        )
        _install_play(tmp_path / "plays", PLAY_ID)
        await loader.load_all()
        try:
            e = await engine.place_entity(
                None, "default", 0, 0, components={f"{PLAY_ID}:duel": {}}
            )
            assert engine.capabilities(e)["interactions"] == ["fight"]

            # 停用：包目录还在 → state=orphan 但 package=disabled、不可清
            await loader.disable(PLAY_ID)
            report = {
                row["source"]: row
                for row in engine.diagnose_components(
                    lambda s: next(
                        (p["status"] for p in loader.list_plays() if p["play_id"] == s),
                        "uninstalled",
                    )
                )
            }
            row = report[PLAY_ID]
            assert row["package"] == "disabled" and row["purgeable"] is False
            with pytest.raises(WorldError, match="还在"):
                await engine.purge_components(
                    PLAY_ID,
                    dry_run=False,
                    package_state=lambda s: "disabled",
                )
            assert e.has_component(f"{PLAY_ID}:duel")  # 一个字节没动

            # 卸载（删目录）：这才可清
            await loader.uninstall(PLAY_ID)
            package = next(
                (p["status"] for p in loader.list_plays() if p["play_id"] == PLAY_ID),
                "uninstalled",
            )
            assert package == "uninstalled"  # 目录没了 → list_plays 里也不再有它
            purged = await engine.purge_components(
                PLAY_ID, dry_run=False, package_state=lambda s: "uninstalled"
            )
            assert purged["purged"] is True and purged["count"] == 1
            assert not e.has_component(f"{PLAY_ID}:duel")
        finally:
            await engine.terminate()

    _run(fn())


# ---------- 管理端端点（服务端强制，不靠界面藏按钮） ----------


async def _admin_scenario(tmp_path: Path, fn):
    import httpx

    from worlditor_mcp.admin import build_admin_app
    from worlditor_mcp.world.identity import IdentityService

    engine = await _engine(tmp_path)
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays", worlditor_version="0.3.0")
    identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
    app = build_admin_app(identity, engine=engine, loader=loader)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin"
        ) as client:
            info = await identity.register_human(
                "admin1", "pass123", admin_key="sekret"
            )
            headers = {"Authorization": f"Bearer {info.token}"}
            return await fn(client, headers, engine, loader)
    finally:
        await engine.terminate()


def test_admin_orphan_endpoints(tmp_path):
    """GET 诊断按行给清理资格；POST purge 默认 dry-run，非孤儿一律 400。"""

    async def fn(client, h, engine, loader):
        _install_play(tmp_path / "plays", PLAY_ID)
        await loader.load_all()
        e = await engine.place_entity(
            None,
            "default",
            0,
            0,
            components={f"{PLAY_ID}:duel": {}, "local:note": {"x": 1}},
        )
        # 加载中：包在 → 不可清
        data = (await client.get("/admin/orphan-components", headers=h)).json()
        rows = {r["source"]: r for r in data["components"]}
        assert rows[PLAY_ID]["package"] == "loaded"
        assert rows[PLAY_ID]["purgeable"] is False
        assert rows["local"]["state"] == "fictional"
        assert rows["local"]["purgeable"] is False

        # 停用：**目录还在** → 仍不可清（400），且数据没动
        await loader.disable(PLAY_ID)
        r = await client.post(
            "/admin/orphan-components/purge",
            json={"source": PLAY_ID, "dry_run": False},
            headers=h,
        )
        assert r.status_code == 400, r.text
        assert e.has_component(f"{PLAY_ID}:duel")

        # local: 永不可清
        r = await client.post(
            "/admin/orphan-components/purge",
            json={"source": "local", "dry_run": False},
            headers=h,
        )
        assert r.status_code == 400, r.text

        # 卸载（目录没了）→ dry-run 先看影响面，再真删
        await loader.uninstall(PLAY_ID)
        preview = (
            await client.post(
                "/admin/orphan-components/purge", json={"source": PLAY_ID}, headers=h
            )
        ).json()["data"]
        assert preview["dry_run"] is True and preview["purged"] is False
        assert preview["keys"] == [f"{PLAY_ID}:duel"] and preview["count"] == 1
        assert e.has_component(f"{PLAY_ID}:duel")  # dry-run 不动数据

        done = (
            await client.post(
                "/admin/orphan-components/purge",
                json={"source": PLAY_ID, "dry_run": False},
                headers=h,
            )
        ).json()["data"]
        assert done["purged"] is True and done["count"] == 1
        assert not e.has_component(f"{PLAY_ID}:duel")
        assert e.has_component("local:note")  # local: 没被牵连

    _run(_admin_scenario(tmp_path, fn))
