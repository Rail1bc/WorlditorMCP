"""worlditor_play_items 内置包测试（D8 持有下沉 + M3 跨包服务真实用例）。

覆盖：物品定义注册、bag_add/take/count/get 服务（含跨包调用）、堆叠/容量、
world_bag/world_use 工具（use 与交互联动扣减）、视图注册。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.play import PlayLoader
from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.store import WorldStore

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "worlditor_mcp" / "builtin_plays"
ITEMS_ID = "worlditor_play_items"


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _scenario(db_path, fn):
    engine = WorldEngine(WorldStore(db_path))
    loader = PlayLoader(
        engine,
        plays_dir=db_path.parent / "plays",
        builtin_dir=BUILTIN_DIR,
        worlditor_version="0.1.0",
    )

    async def main():
        await engine.initialize()
        try:
            return await fn(engine, loader)
        finally:
            await engine.terminate()

    return main()


async def _call_as(player_id: str, coro_factory):
    """以 player 身份调用（注入 _caller_entity，模拟 MCP ctx 身份）。"""
    from worlditor_mcp.world.mcp import _caller_entity

    token = _caller_entity.set(player_id)
    try:
        return await coro_factory()
    finally:
        _caller_entity.reset(token)


# ---------- 加载与注册 ----------


def test_items_play_loaded(tmp_path):
    """内置包加载：物品定义 / 4 服务 / 2 工具 / 视图就位。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        assert items is not None
        # 物品定义（D13：苹果/面包归 items 包）
        assert "apple" in engine.store.items
        assert "bread" in engine.store.items
        assert engine.store.items["apple"].use_action == "eat"
        # 服务
        services = {(s["play_id"], s["name"]) for s in engine.list_services()}
        assert services >= {
            (ITEMS_ID, "bag_add"),
            (ITEMS_ID, "bag_take"),
            (ITEMS_ID, "bag_count"),
            (ITEMS_ID, "bag_get"),
        }
        # 工具
        tools = {t["name"] for t in engine.list_tools()}
        assert {"world_bag", "world_use"} <= tools
        # 视图
        views = {v["key"]: v for v in engine.list_views()}
        assert views["items"]["provider"]["url"] == (f"/plays/{ITEMS_ID}/web/bag.js")

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 背包服务（含跨包调用） ----------


def test_bag_add_take_count(tmp_path):
    """bag_add/take/count：增删查；不足报错。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        api = items.api
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 0
        )
        await api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=3
        )
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )
        await api.call_service(
            ITEMS_ID, "bag_take", entity_id=player.id, item_id="apple", count=1
        )
        assert (
            await api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 2
        )
        # 不足 → WorldError
        with pytest.raises(WorldError, match="不足"):
            await api.call_service(
                ITEMS_ID, "bag_take", entity_id=player.id, item_id="apple", count=99
            )
        # 未注册物品
        with pytest.raises(WorldError, match="物品不存在"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="nope", count=1
            )
        # 非法 count
        with pytest.raises(WorldError, match="正整数"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=0
            )

    _run(_scenario(tmp_path / "world.db", fn))


def test_bag_cross_play(tmp_path):
    """跨包真实用例：另一个玩法包（pkg_b）调 items 服务发物品。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        api_b = WorlditorPlayAPI(engine, "pkg_b")
        engine.attach_play_api("pkg_b", api_b)
        # pkg_b 发礼包（出生礼包场景）
        await api_b.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=3
        )
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 3
        )

    _run(_scenario(tmp_path / "world.db", fn))


def test_bag_stack_and_capacity(tmp_path):
    """堆叠上限 99 + 格子容量 20。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        api = items.api
        # 150 个苹果 → 2 格（99 + 51）
        await api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=150
        )
        bag = await api.call_service(ITEMS_ID, "bag_get", entity_id=player.id)
        assert len(bag["slots"]) == 2
        assert bag["slots"][0]["count"] == 99
        assert bag["slots"][1]["count"] == 51
        # 20 种物品 → 满
        for i in range(18):
            item_id = f"apple{i}"
            engine.store.items[item_id] = engine.store.items["apple"]  # 直接登记定义
        for i in range(18):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id=f"apple{i}", count=1
            )
        with pytest.raises(WorldError, match="已满"):
            await api.call_service(
                ITEMS_ID, "bag_add", entity_id=player.id, item_id="bread", count=1
            )

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 工具 ----------


def test_world_bag_tool(tmp_path):
    """world_bag：我的背包（工具经服务通道读）。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=2
        )

        async def call():
            return await items.module._world_bag(items.api, None)  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert result["used"] == 1
        assert result["slots"][0]["name"] == "苹果"
        assert result["slots"][0]["count"] == 2

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_use_tool(tmp_path):
    """world_use：交互联动——注册 eat 交互 → 使用苹果 → 交互执行 + 扣 1。"""

    async def fn(engine, loader):
        from worlditor_mcp.world.model import InteractionResult

        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        used = []

        async def _eat(api, req):
            used.append(req.item_id)
            return InteractionResult(text="咔嚓，好吃！")

        engine.register_interaction("eat", _eat, label="吃")
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=2
        )

        async def call():
            return await items.module._world_use(items.api, None, item_id="apple")  # noqa: SLF001

        result = await _call_as(player.id, call)
        assert used == ["apple"]  # 交互被执行
        assert "text" in result
        assert (
            await items.api.call_service(
                ITEMS_ID, "bag_count", entity_id=player.id, item_id="apple"
            )
            == 1
        )
        # 再吃一个 → 0；继续吃 → 报错（没有苹果）
        await _call_as(player.id, call)
        with pytest.raises(WorldError, match="没有"):
            await _call_as(player.id, call)

    _run(_scenario(tmp_path / "world.db", fn))


def test_world_use_unknown_item(tmp_path):
    """world_use：未注册物品 / 不可使用物品 → WorldError。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        items = next(p for p in plays if p.play_id == ITEMS_ID)
        player = await engine.place_entity(
            "player", "default", 0, 0, name="小明", attrs={"starter_granted": True}
        )
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="apple", count=1
        )

        async def call(item_id):
            return await items.module._world_use(items.api, None, item_id=item_id)  # noqa: SLF001

        with pytest.raises(WorldError, match="物品不存在"):
            await _call_as(player.id, lambda: call("nope"))
        # 喇叭不可使用（use_action 为空）
        await items.api.call_service(
            ITEMS_ID, "bag_add", entity_id=player.id, item_id="megaphone", count=1
        )
        with pytest.raises(WorldError, match="不能使用"):
            await _call_as(player.id, lambda: call("megaphone"))

    _run(_scenario(tmp_path / "world.db", fn))


# ---------- 物品管理页（v0.1.12 管理页协议） ----------


def test_items_admin_page_actions(tmp_path):
    """物品管理页：注册清单 + list/create/update/delete + 落库。"""

    async def fn(engine, loader):
        plays = await loader.load_all()
        assert any(p.play_id == ITEMS_ID for p in plays)
        # 注册清单：items 包注册了「物品管理」页
        pages = [p for p in engine.list_admin_pages() if p["play_id"] == ITEMS_ID]
        assert pages and pages[0]["key"] == "items"
        assert set(pages[0]["actions"]) == {"list", "create", "update", "delete"}
        assert pages[0]["component_url"] == f"/plays/{ITEMS_ID}/web/admin-items.js"
        # create
        created = await engine.call_admin_page_action(
            ITEMS_ID,
            "items",
            "create",
            id="knife",
            name="小刀",
            desc="锋利的小刀",
            stackable=False,
        )
        assert created["id"] == "knife"
        assert engine.store.items["knife"].stackable is False
        # update（部分字段）
        await engine.call_admin_page_action(
            ITEMS_ID,
            "items",
            "update",
            id="knife",
            name="匕首",
            use_action="slash",
            attrs={"dmg": 3},
        )
        it = engine.store.items["knife"]
        assert it.name == "匕首"
        assert it.use_action == "slash"
        assert it.attrs == {"dmg": 3}
        assert it.desc == "锋利的小刀"  # 未提供字段不变
        # list
        data = await engine.call_admin_page_action(ITEMS_ID, "items", "list")
        assert any(i["id"] == "knife" for i in data["items"])
        # delete
        await engine.call_admin_page_action(ITEMS_ID, "items", "delete", id="knife")
        assert "knife" not in engine.store.items
        # 校验错误：创建已有 / 删除不存在
        with pytest.raises(WorldError, match="已存在"):
            await engine.call_admin_page_action(
                ITEMS_ID, "items", "create", id="apple", name="苹果2"
            )
        with pytest.raises(WorldError, match="不存在"):
            await engine.call_admin_page_action(ITEMS_ID, "items", "delete", id="ghost")

    _run(_scenario(tmp_path / "world.db", fn))


def test_items_admin_create_persisted(tmp_path):
    """物品管理页创建的定义落库（flush_item_defs 生效；重启后仍在）。"""

    async def fn(engine, loader):
        await loader.load_all()
        await engine.call_admin_page_action(
            ITEMS_ID,
            "items",
            "create",
            id="elixir",
            name="回血药水",
            desc="瞬间恢复",
            attrs={"heal": 50},
        )
        # WAL 模式下另一连接可直接验证落库
        import sqlite3

        conn = sqlite3.connect(tmp_path / "world.db")
        try:
            row = conn.execute(
                "SELECT name, attrs_json FROM items WHERE id='elixir'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "回血药水"
        assert "heal" in row[1]

    async def main():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        loader = PlayLoader(
            engine,
            plays_dir=tmp_path / "plays",
            builtin_dir=BUILTIN_DIR,
            worlditor_version="0.1.0",
        )
        await engine.initialize()
        try:
            return await fn(engine, loader)
        except Exception:
            await engine.terminate()
            raise

    _run(main())


# ---------- 视图/管理页组件协议（防回归，v0.1.14） ----------


def test_web_component_protocol_guarded():
    """内置包 web 组件协议（防回归）：IIFE 形态 + MCP 会话管理。

    组件经 new Function("Vue","UiBlock", code) 加载（body = return (code)(Vue,
    UiBlock)）——文件必须 IIFE 形参风格；内嵌 MCP 调用必须实现 streamable
    HTTP 会话（initialize → Mcp-Session-Id），否则浏览器端 400。
    """
    web_files = sorted(BUILTIN_DIR.glob("*/web/*.js"))
    assert web_files, "应存在玩法包 web 组件文件"

    for path in web_files:
        text = path.read_text(encoding="utf-8").strip()
        # 先剥掉文件顶部注释行再校验形态
        core = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("//")
        ).strip()
        assert core.startswith("(function (Vue, UiBlock) {"), (
            f"{path}: 必须以 (function (Vue, UiBlock) {{ 开头（IIFE 形参由加载器注入）"
        )
        assert text.endswith("});"), f"{path}: 必须以 }}); 收尾"
        if "function callTool" in text:
            assert "Mcp-Session-Id" in text, (
                f"{path}: callTool 缺少 Mcp-Session-Id 会话管理"
            )
            assert "ensureSession" in text, (
                f"{path}: 缺少 ensureSession（initialize → session）"
            )
