"""玩家模型端到端验收（D45–D47 / v0.8.0）。

守住的东西（对应 `docs/PLAYER_MODEL_PLAN.md` §1 的 R1–R9 与 §6 验收清单）：

- **R2/R3**：注册不创建实体、不写 `local:player`；`token.entity_id` 为空是常态
- **R8**：没有化身时**自举工具照样调得到**（`requires_entity=False`），
  且提示是"你还没有角色"而不是"连接未认证"
- **R5/R6**：`api.caller()` / `caller_principal()` 跟着 `act_as` 变，主体键稳定
- **R4**：roster 由玩法包从内核账本派生（`avatars_of`），内核不持有列表
- **D14**：认领后包删不掉；注销账户级联清全部化身 + 发 `on_principal_deleted`
- **D44**：停用玩家包 → 视图 tab 消失、化身与数据都还在
- **续玩（PLAY_DEV §14.4 第 5 点）**：`act_as` 只在**工具上下文**可用，所以重登后的
  接管只能"惰性"发生在读侧自举工具里（记忆优先 → 唯一一具次之 → 多具不猜）

测法：**真实走工具入口**（`build_dynamic_tool` 的 wrapper + `_meta` 注入），
而不是直接调 handler——否则"工具门（`requires_entity`）"这条最关键的改动
就没人守着了。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from play_fixtures import PLAYER_ID, install_player_play  # noqa: E402
from world_fixtures import give_avatar, seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError  # noqa: E402
from worlditor_mcp.world.identity import IdentityService  # noqa: E402
from worlditor_mcp.world.mcp import build_dynamic_tool, build_mcp_server  # noqa: E402
from worlditor_mcp.world.mcp.http import build_http_app  # noqa: E402
from worlditor_mcp.world.play import PlayLoader  # noqa: E402
from worlditor_mcp.world.play.api import WorlditorPlayAPI  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402

DEMO_ID = "worlditor_play_demo"


def _run(coro):
    return asyncio.run(coro)


def _ctx(info) -> object:
    """仿造 HTTP 中间件注入的请求上下文（`_meta` 五字段，与 http.py 同键名）。"""
    meta = type(
        "Meta",
        (),
        {
            "worlditor_entity_id": info.entity_id,
            "worlditor_tier": info.tier,
            "worlditor_account_id": info.account_id or "",
            "worlditor_username": info.username or "",
            "worlditor_token": info.token,
        },
    )()
    request_ctx = type("RequestContext", (), {"meta": meta})()
    return type("Context", (), {"request_context": request_ctx})()


async def call_with(engine, ctx, tool: str, **args) -> dict:
    """经**真实的工具入口**调用（含档位 / 化身门 / 世界激活过滤）。"""
    binding = engine._tools[tool]
    wrapper = build_dynamic_tool(engine, binding, tool)
    return json.loads(await wrapper(ctx, **args))


async def call(engine, info, tool: str, **args) -> dict:
    return await call_with(engine, _ctx(info), tool, **args)


def _ctx_of(engine, token: str) -> object:
    """按**当前**凭据行造上下文——`token.entity_id` 会随 `act_as` 变，不能用旧快照。"""
    row = engine.store.get_token(token)
    assert row is not None, token
    meta = type(
        "Meta",
        (),
        {
            "worlditor_entity_id": row.entity_id,
            "worlditor_tier": row.tier,
            "worlditor_account_id": row.account_id or "",
            "worlditor_username": row.username or "",
            "worlditor_token": token,
        },
    )()
    request_ctx = type("RequestContext", (), {"meta": meta})()
    return type("Context", (), {"request_context": request_ctx})()


async def _setup(tmp_path: Path):
    """引擎 + 最小世界 + **参考玩家包** + 一个注册好的玩家（**没有化身**）。"""
    install_player_play(tmp_path / "plays")
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    await seed_test_world(engine)
    loader = PlayLoader(engine, plays_dir=tmp_path / "plays")
    await loader.load_all()
    identity = IdentityService(engine, auth_mode="open")
    info = await identity.register_human("小明", "pass123")
    return engine, loader, identity, info


def test_registration_creates_no_entity_and_no_player_tag(tmp_path):
    """R2/R3：注册只产出凭据；内核不写任何"这是玩家"的标记。"""

    async def fn():
        engine, _loader, _identity, info = await _setup(tmp_path)
        try:
            assert info.entity_id == ""
            assert engine.list_entities(include_absent=True) == []
            assert engine.entities_of_account(info.account_id) == []
        finally:
            await engine.terminate()

    _run(fn())


def test_bootstrap_tools_work_without_avatar(tmp_path):
    """R8/R9：没有化身时**自举工具照样能用**，并明确说"你还没有角色"。"""

    async def fn():
        engine, _loader, _identity, info = await _setup(tmp_path)
        try:
            who = await call(engine, info, "player_whoami")
            assert "当前化身：还没有" in who["text"], who
            assert "化身总数：0" in who["text"], who

            avatars = await call(engine, info, "player_avatars")
            assert "还没有任何化身" in avatars["text"], avatars

            # 创建 → 造实体 + 认领 + 指过去（三步都在包里）
            created = await call(engine, info, "player_create", name="小明")
            assert "已创建化身" in created["text"], created
            # 凭据指针真的写进去了（`act_as` 生效，且是**落库**的）
            assert engine.store.get_token(info.token).entity_id
            entity = engine.get_entity(engine.store.get_token(info.token).entity_id)
            assert entity is not None and entity.user_id == info.account_id
            assert entity.pos_key() == ("default", 0, 0)  # 包的落点策略
        finally:
            await engine.terminate()

    _run(fn())


def test_no_avatar_gate_message_is_not_the_auth_one(tmp_path):
    """工具门（D46）：需要身体的工具回"你还没有角色"；围观/无上下文才回"未认证"。"""

    async def fn():
        engine, _loader, _identity, info = await _setup(tmp_path)
        try:
            # 参考玩家包里 `player_retire` 是**默认 requires_entity=True** 的工具
            denied = await call(engine, info, "player_retire", entity_id="x")
            assert "你还没有角色" in denied["text"], denied
            assert "未认证" not in denied["text"], denied

            # 没有请求上下文（进程内直调）→ 那条才是"未认证"
            binding = engine._tools["player_retire"]
            wrapper = build_dynamic_tool(engine, binding, "player_retire")
            bare = type("Context", (), {"request_context": None})()
            out = json.loads(await wrapper(bare))
            assert "未认证" in out["text"], out
        finally:
            await engine.terminate()

    _run(fn())


def test_multiple_avatars_and_switch(tmp_path):
    """R4/R5：一个主体 0/1/N 具化身；切换后 `api.caller()` 跟着变（roster 归包）。"""

    async def fn():
        engine, _loader, _identity, info = await _setup(tmp_path)
        try:
            first = await call(engine, info, "player_create", name="小明")
            assert first
            one = engine.store.get_token(info.token).entity_id
            second = await call(engine, info, "player_create", name="小明二号")
            assert second
            two = engine.store.get_token(info.token).entity_id
            assert two != one

            listing = await call(engine, info, "player_avatars")
            assert "小明" in listing["text"] and "小明二号" in listing["text"]

            # 切回第一具：包先用自己的 roster 校验归属，再 act_as
            switched = await call(engine, info, "player_switch", entity_id=one)
            assert "已切换" in switched["text"], switched
            assert engine.store.get_token(info.token).entity_id == one

            # 不是我的 → 切不了（这一句是安全边界：内核不校验归属）
            stranger = await engine.place_entity(None, "default", 0, 1, name="路人")
            refused = await call(engine, info, "player_switch", entity_id=stranger.id)
            assert "不是你的化身" in refused["text"], refused
            assert engine.store.get_token(info.token).entity_id == one
        finally:
            await engine.terminate()

    _run(fn())


def test_relogin_resumes_avatar_lazily(tmp_path):
    """D-a 的续玩：重登签发的新凭据指针为空，**接管只能发生在工具调用里**。

    守住 `docs/PLAY_DEV.md` §14.4 第 5 点：`act_as` 需要**凭据上下文**，而它只在
    工具 handler 里存在——主体事件回调里调用直接抛错。所以续玩落在**读侧自举工具**
    上，顺序是：记忆优先 → 唯一一具次之 → 多具且无记忆**不猜**（让玩家自己挑）。
    """

    async def fn():
        engine, _loader, identity, info = await _setup(tmp_path)
        try:
            await call(engine, info, "player_create", name="小明")
            first = engine.store.get_token(info.token).entity_id
            await call(engine, info, "player_create", name="小明二号")
            assert engine.store.get_token(info.token).entity_id != first
            await call(engine, info, "player_switch", entity_id=first)  # 记忆 = 第一具

            # ① `act_as` 要凭据上下文：没有请求上下文时它根本走不通——
            #    所以"登录时自动接管"这件事在事件回调里**做不到**（A 的由来）
            api = engine._play_apis[PLAYER_ID]
            with pytest_raises_world_error("需要连接上下文"):
                await api.act_as(first)

            # ② 重登：新凭据从空开始（D-a 的固有代价，不是 bug）
            again = await identity.login("小明", "pass123")
            assert again.token != info.token and again.entity_id == ""

            # ③ 第一次问"我是谁" → 顺手接上（记忆优先）
            who = await call_with(engine, _ctx_of(engine, again.token), "player_whoami")
            assert "已接上你上次操作的那具" in who["text"], who
            assert engine.store.get_token(again.token).entity_id == first

            # ④ 多具 + **没有记忆** → 不猜（挑哪具是玩法判断，包不替玩家决定）
            await api.kv_set("active_avatar", {})
            fresh = await identity.login("小明", "pass123")
            listing = await call_with(
                engine, _ctx_of(engine, fresh.token), "player_avatars"
            )
            assert engine.store.get_token(fresh.token).entity_id == "", listing
            assert "← 当前" not in listing["text"], listing

            # ⑤ 只有**一具**化身 → 唯一候选，不必猜
            other = await identity.register_human("小红", "pass123")
            await give_avatar(engine, other, name="小红")
            only = await identity.login("小红", "pass123")
            assert only.entity_id == ""
            who2 = await call_with(engine, _ctx_of(engine, only.token), "player_whoami")
            assert engine.store.get_token(only.token).entity_id == other.entity_id
            assert "已接上你上次操作的那具" in who2["text"], who2
        finally:
            await engine.terminate()

    _run(fn())


def test_claimed_avatar_is_protected_and_retire_is_the_owner_channel(tmp_path):
    """D14：认领后包删不掉；要退得走 `release_avatar` → `remove_entity`（两步留痕）。"""

    async def fn():
        engine, loader, _identity, info = await _setup(tmp_path)
        try:
            await call(engine, info, "player_create", name="小明")
            avatar_id = engine.store.get_token(info.token).entity_id
            # 包不允许把**最后一具**退掉（退掉就没得玩了）
            last = await call(engine, info, "player_retire", entity_id=avatar_id)
            assert "最后一具" in last["text"], last
            # 再建一具，才有得退
            await call(engine, info, "player_create", name="小明二号")
            second_avatar_id = engine.store.get_token(info.token).entity_id
            # 第三具：让"退掉当前那具"之后还剩得下东西（包拒退最后一具）
            await call(engine, info, "player_create", name="小明三号")
            third_avatar_id = engine.store.get_token(info.token).entity_id

            # 包的普通删除通道被 D14 挡住（这是不变的红线）
            api = engine._play_apis[PLAYER_ID]
            with pytest_raises_world_error("绑定了账户"):
                await api.remove_entity(avatar_id)

            # 退掉自己的：解绑 + 清指针 → 之后才删得掉
            out = await call(engine, info, "player_retire", entity_id=avatar_id)
            assert "已退掉" in out["text"], out
            assert engine.get_entity(avatar_id) is None
            # 退的**不是当前那具** → 指针不动（当前仍是第三具）
            assert engine.store.get_token(info.token).entity_id == third_avatar_id
            # 再退**当前那具**（还剩两具，包不拦）→ 指针清空（回到"还没有化身"）
            out = await call(engine, info, "player_retire", entity_id=third_avatar_id)
            assert "已退掉" in out["text"], out
            assert engine.store.get_token(info.token).entity_id == ""
            assert engine.get_entity(second_avatar_id) is not None
        finally:
            await engine.terminate()

    _run(fn())


class pytest_raises_world_error:
    """本地小断言器：期望抛 WorldError 且消息匹配（避免为一个断言引入 pytest）。"""

    def __init__(self, match: str) -> None:
        self.match = match

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert exc_type is not None, f"应当抛出 WorldError（匹配 {self.match!r}）"
        assert issubclass(exc_type, WorldError), f"抛的是 {exc_type}"
        assert self.match in str(exc), str(exc)
        return True


def test_roster_service_is_derived_from_kernel_ledger(tmp_path):
    """R4/§14.3：对外服务只读内核账本；另一个包经 `call_service` 软依赖消费它。"""

    async def fn():
        engine, loader, identity, info = await _setup(tmp_path)
        try:
            # 另一个包（模拟"需要我全部化身"的包：队伍面板 / 切换角色 UI）
            other = WorlditorPlayAPI(engine, "pkg_party")
            engine.attach_play_api("pkg_party", other)

            async def _roster_tool(api, ctx, **kwargs):
                rows = await api.call_service(PLAYER_ID, "avatars_of")
                active = await api.call_service(PLAYER_ID, "active_avatar")
                switched = await api.call_service(
                    PLAYER_ID, "switch_to", entity_id=str(kwargs.get("entity_id") or "")
                )
                return {
                    "text": json.dumps(
                        {
                            "count": len(rows),
                            "active": active,
                            "switched": switched,
                            # 零依赖那一路：只读"我现在是谁"
                            "caller": api.caller(),
                            "principal": api.caller_principal(),
                        },
                        ensure_ascii=False,
                    )
                }

            other.register_tool(
                "party_roster",
                _roster_tool,
                params={"entity_id": "string"},
                requires_entity=False,
            )

            async def _on_login(api, principal):
                # ⚠ 主体事件里**没有"当前调用者"上下文**（登录是 HTTP/CLI 路径，
                # 不经过 MCP 请求）——所以服务必须显式传 principal，不能靠缺省。
                rows = await api.call_service(
                    PLAYER_ID, "avatars_of", principal=principal.account_id
                )
                # ⚠ kv_set 是 async（PLAY_DEV §4 的"同步/异步界线"）；漏 await 会被
                # 事件总线的异常隔离吞成一条日志，测试里表现为"KV 里什么都没有"
                await api.kv_set(
                    "seen", {"count": len(rows), "who": principal.account_id}
                )

            engine.register_world_event(
                "on_principal_login", _on_login, play_id="pkg_party"
            )

            await call(engine, info, "player_create", name="小明")
            first = engine.store.get_token(info.token).entity_id
            await call(engine, info, "player_create", name="小明二号")
            second = engine.store.get_token(info.token).entity_id

            out = json.loads(
                (await call(engine, info, "party_roster", entity_id=first))["text"]
            )
            assert out["count"] == 2, out
            assert out["caller"] == first, "switch_to 之后本包的 caller() 也跟着变"
            assert out["principal"] == info.account_id
            # active_avatar 是在 switch_to **之前**读的 → 还是第二具（顺序即语义，
            # 服务读的是"此刻"的指针）
            assert out["active"]["entity_id"] == second
            # 指针写的是**凭据行**（act_as 的落点）
            assert engine.store.get_token(info.token).entity_id == first

            # switch_to 只接受调用方自己的化身（跨主体一律拒绝）
            with pytest_raises_world_error("不是当前调用方"):
                await other.call_service(PLAYER_ID, "switch_to", entity_id="nope")

            # 登录事件：另一个包收到了（主体键稳定，同一账户反复登录都是它）
            again = await identity.login("小明", "pass123")
            assert again.account_id == info.account_id
            assert other.kv_get("seen") == {"count": 2, "who": info.account_id}
            # ⚠ D-a 的代价如实记录：登录签发的**新凭据**指针从空开始
            # （不是 bug：换设备/重登后由玩法包的自举工具重新选定）
            assert again.entity_id == ""
        finally:
            await engine.terminate()

    _run(fn())


def test_account_deletion_cascades_and_notifies(tmp_path):
    """D47：注销 = 全部化身清理 + `on_principal_deleted`（包据此清自己的 roster）。"""

    async def fn():
        engine, _loader, identity, info = await _setup(tmp_path)
        try:
            await call(engine, info, "player_create", name="小明")
            await call(engine, info, "player_create", name="小明二号")
            avatar_ids = {e.id for e in engine.entities_of_account(info.account_id)}
            assert len(avatar_ids) == 2

            seen: list[str] = []
            engine.register_world_event(
                "on_principal_deleted",
                lambda api, principal: seen.append(principal.account_id),
                play_id=PLAYER_ID,
            )
            await identity.delete_account(info.account_id)

            assert seen == [info.account_id]
            assert engine.entities_of_account(info.account_id) == []
            for eid in avatar_ids:
                assert engine.get_entity(eid) is None, (
                    "注销必须清掉全部化身（避免孤儿）"
                )
            # 包自己的 KV（"上次操作的是哪具"）也清了
            api = engine._play_apis[PLAYER_ID]
            assert info.account_id not in (api.kv_get("active_avatar", {}) or {})
        finally:
            await engine.terminate()

    _run(fn())


def test_disabling_player_package_keeps_avatars(tmp_path):
    """D44：停用玩家包 → 视图 tab 消失，但旧化身仍在世界、数据保留。"""

    async def fn():
        engine, loader, _identity, info = await _setup(tmp_path)
        try:
            await call(engine, info, "player_create", name="小明")
            avatar_id = engine.store.get_token(info.token).entity_id
            assert any(v["play_id"] == PLAYER_ID for v in engine.list_views())

            await loader.disable(PLAYER_ID)
            assert not any(v["play_id"] == PLAYER_ID for v in engine.list_views())
            assert engine.get_entity(avatar_id) is not None, "停用不删数据（D44）"
            assert engine.get_entity(avatar_id).user_id == info.account_id
        finally:
            await engine.terminate()

    _run(fn())


def test_views_are_not_filtered_without_avatar(tmp_path):
    """R9：**没有化身时 `/views` 不过滤**——否则"创建角色"的入口会跟着消失。

    这是 `/views` 过滤的一个死角：`play_active_for_entity("")` 会回落到**默认世界**，
    于是"玩家在别的世界"就等于"什么视图都看不到"——包括那个唯一的出路，人被困死
    在门口。宁可多显示几个 tab（点了会因世界未启用而不可用，那是可理解的）。
    """

    async def fn():
        engine, loader, identity, info = await _setup(tmp_path)
        try:
            # 乙世界只启用 demo → 参考玩家包在这个世界里"不存在"
            await engine.create_world("world_b", "乙世界", play_ids=[DEMO_ID])
            await engine.create_map("m_b", "乙世界地图")
            await engine.create_location("m_b", 0, 0, "乙世界广场")
            await engine.assign_map("m_b", "world_b")

            from starlette.testclient import TestClient

            app = build_http_app(build_mcp_server(engine), identity, engine=engine)
            client = TestClient(app)
            h = {"Authorization": f"Bearer {info.token}"}

            # 没有化身 → 不过滤（R9：出口必须看得见）
            views = client.get("/views", headers=h).json()["views"]
            assert PLAYER_ID in {v["play_id"] for v in views}, views

            # 有了化身**且站在乙世界** → 按世界过滤（D15 的正常行为回来了）
            avatar = await give_avatar(engine, info, name="小明")
            await engine.move_entity(avatar.id, "m_b", 0, 0)
            views = client.get("/views", headers=h).json()["views"]
            assert PLAYER_ID not in {v["play_id"] for v in views}, views
        finally:
            await engine.terminate()

    _run(fn())


def test_principal_events_are_not_pushed_to_sse(tmp_path):
    """D47：主体事件**不推 SSE**（否则等于把主体名册广播给每个订阅者）。"""

    async def fn():
        engine, _loader, identity, _info = await _setup(tmp_path)
        try:
            queue = engine.subscribe()
            try:
                await identity.login("小明", "pass123")
                assert queue.empty(), "登录事件不该出现在 SSE 流里"
            finally:
                engine.unsubscribe(queue)
        finally:
            await engine.terminate()

    _run(fn())
