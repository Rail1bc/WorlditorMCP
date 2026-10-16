"""参考玩家包：worlditor_play_player（D45–D47 的落地示范）。

**它回答的是"玩家是什么"**——内核不回答这个问题：

- 内核只记两本账：这次请求**以哪具实体行动**（凭据指针）、**哪些实体属于哪个主体**
  （实体上的 ``core:account``）。它不认识"玩家"、不诞生角色、不指定落点（D45）。
- 本包决定：一个主体能有几具化身、怎么造、落在哪、怎么切换、怎么退掉。

一具化身 = 一个**带 ``core:account`` 的普通实体**（"是不是人"看账户绑定，D42）。
所以"化身"不需要内核认识——本包给它一个 ``local:avatar`` 标记组件，纯属本包
自己的内容约定（内核不解释它；判断"这是不是人"永远看 ``core:account``）。

对外能力：

- 工具（MCP）：``player_whoami`` / ``player_create`` / ``player_switch`` /
  ``player_retire`` / ``player_avatars``
- 服务（跨包同步调用）：``avatars_of`` / ``active_avatar`` / ``switch_to``
- 视图：``player``（角色面板）

**五个刻意的设计点**（都是给玩法包作者看的示范）：

1. **自举工具声明 ``requires_entity=False``**：``whoami`` / ``create`` / ``switch`` /
   ``avatars`` 在没有化身时也必须能调——否则"创建第一具化身"这件事自己就被
   "需要化身"挡住了（工具门默认 ``requires_entity=True``）。
2. **roster 从内核账本派生**：``avatars_of`` 走 ``query_entities(where=…)`` 按
   ``core:account`` 筛，不另外维护一份名单——两份名单迟早不一致（D46）。
   本包只在 KV 里记"上次操作的是哪具"（这是**玩法状态**，内核没这个概念）。
3. **落点自定**：内核没有出生点（D45），本包自己挑——先看自己的内容
   （``data/spawn.json``），再退回"坐标序最小的地块"。
4. **删化身要两步**：``release_avatar``（解绑，内核窄口）→ ``remove_entity``。
   D14 保护的是**别人**的化身；自己的要退，得显式解绑，让这个动作留痕。
5. **续玩只能"惰性接管"**：``api.act_as()`` 写的是**凭据**指针，而凭据上下文
   **只在工具 handler 里**存在——``on_principal_login`` 这类事件回调里调用它会抛
   "需要连接上下文"（PLAY_DEV §14.4）。所以"登录后接着玩"落在**读侧自举工具**上
   （``_resume()``）：谁先被调用，谁完成接管。
"""

from __future__ import annotations

import json
from pathlib import Path

from worlditor_mcp.world import WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

# 本包自己的 KV 键（play_data，namespace = 本包 id）：主体 → 上次操作的化身 id。
# 这是**玩法状态**（内核没有"上次那具"这个概念），也是登录后恢复选中的依据。
_ACTIVE_KEY = "active_avatar"

# "这是本包造的化身"——纯内容标记，**不承载任何内核语义**（D41/D42）。
# 参考世界内容包用 local: 命名空间与本包对接（内容与行为在同一个组件上相遇）。
_AVATAR = "local:avatar"

# 落点内容文件：{"map_id": "...", "row": 0, "col": 0}（可选；不存在则自动挑）
_SPAWN_FILE = "spawn.json"


def _read_spawn_file() -> dict:
    """本包自带的落点（``data/spawn.json``）；没有/读坏 → 空（走自动挑）。"""
    path = Path(__file__).parent / "data" / _SPAWN_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _avatars_of(api: WorlditorPlayAPI, principal: str) -> list:
    """某主体的全部化身（**从内核账本派生**，含不在世界上的）。

    不看位置：下线中的化身照样算数（D36：位置是可选组件，"不在场"不是"不存在"）。
    """
    if not principal:
        return []
    return api.query_entities(
        include_absent=True, where=lambda e: e.user_id == principal
    )


def _pick_tile(api: WorlditorPlayAPI) -> tuple[str, int, int] | None:
    """挑一个落点：**本包自己的策略**（内核没有出生点，D45）。

    顺序：① ``data/spawn.json`` 写明的那块（若仍然存在）→ ② 坐标序最小的地块。
    都没有（空世界）→ ``None``：造出来的化身**不在世界上**（合法状态，D36），
    等地图就绪后再由本包（或别的包）放进去。
    """
    wanted = _read_spawn_file()
    map_id = str(wanted.get("map_id") or "")
    row, col = wanted.get("row"), wanted.get("col")
    if map_id and isinstance(row, int) and isinstance(col, int):
        if api.get_location(map_id, row, col) is not None:
            return (map_id, row, col)
    tiles = api.list_locations()
    if not tiles:
        return None
    first = min(tiles, key=lambda loc: (loc.map_id, loc.row, loc.col))
    return (first.map_id, first.row, first.col)


def _summary(entity) -> dict:
    """化身摘要（给工具返回/服务调用用；名字走 core:info 的只读派生视图）。"""
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "map_id": entity.map_id,
        "row": entity.row,
        "col": entity.col,
        "in_world": entity.has_position(),
    }


async def _resume(api: WorlditorPlayAPI) -> str | None:
    """**惰性接管**：把本次凭据指回"这个主体上次操作的那具"（D-a 的续玩入口）。

    为什么必须"惰性"：``api.act_as()`` 写的是**凭据**指针，而凭据上下文只在
    **工具 handler** 里存在（``on_principal_login`` / ``on_tick`` 这些回调里没有 →
    会抛"需要连接上下文"）。所以"登录后接着玩"没有别的落点，只能放在**读侧自举
    工具**上：谁先被调用谁完成接管（视图在 ``onMounted`` 调一次 ``player_whoami``，
    agent 第一次问"我是谁"也是它）。

    顺序（**每一步都只在自己的 roster 里挑**，内核不校验归属）：
    ① 凭据已指向一具**仍属于我**的化身 → 不动（尊重本设备上一次的显式选择）；
    ② 本包 KV 记的"上次那具"仍属于我 → 接上；
    ③ 我只有**一具**化身 → 直接接上（唯一候选，不必猜）；
    ④ 多具且没有记忆 → **不猜**，留给 ``player_switch``（``player_whoami`` 会提示）。

    Returns:
        接上的实体 id；没有可接的（围观凭据 / 一具都没有 / 需要玩家自己挑）→ ``None``。
    """
    principal = api.caller_principal() or ""
    if not principal:
        return None  # 围观（read）凭据：没有主体，也就没有"续玩"
    mine = {e.id: e for e in _avatars_of(api, principal)}
    current = api.caller()
    if current and current in mine:
        # ① 已指向**自己的一具**化身 → 不动（悬空指针、别人的实体都会落到下面重挑）
        return current
    remembered = _remembered(api, principal)
    target = remembered if remembered in mine else ""
    if not target and len(mine) == 1:
        target = next(iter(mine))
    if not target:
        return None
    await api.act_as(target)
    await _remember(api, principal, target)
    return target


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    # 本包的内容标记组件：带上它的实体**在本包眼里**是一具化身。
    # 它不贡献内核能力（没有 interactions / fields）——纯粹是"本包的内容约定"。
    api.declare_component(_AVATAR, label="化身")

    # 工具：自举类一律 requires_entity=False（见模块 docstring 第 1 点）
    api.register_tool(
        "player_whoami",
        _whoami,
        description="查看我是谁：主体、当前行动的化身、一共有几具化身",
        requires_entity=False,
    )
    api.register_tool(
        "player_avatars",
        _avatars_tool,
        description="列出我的全部化身（含不在世界上的）",
        requires_entity=False,
    )
    api.register_tool(
        "player_create",
        _create,
        description="创建一具属于我的化身（落点由本包决定）",
        params={"name": "string"},
        requires_entity=False,
    )
    api.register_tool(
        "player_switch",
        _switch,
        description="切换当前行动的化身（只能切我自己的）",
        params={"entity_id": "string"},
        requires_entity=False,
    )
    api.register_tool(
        "player_retire",
        _retire,
        description="退掉我一具多余的化身（解绑后删除，不可恢复）",
        params={"entity_id": "string"},
    )

    # 服务（G59 的软依赖锚点）：需要"我的**全部**化身"的包调这三个，
    # 只关心"我现在是谁"的包直接读 api.caller() 即可，不必依赖本包（见 PLAY_DEV）。
    api.register_service("avatars_of", _service_avatars_of)
    api.register_service("active_avatar", _service_active_avatar)
    api.register_service("switch_to", _service_switch_to)

    # 视图（G3/D7）：角色面板——没有化身时显示"还没有角色"的入口
    api.register_view(
        "player",
        title="角色",
        icon="🧍",
        provider={"type": "component", "url": f"/plays/{api.play_id}/web/view.js"},
    )

    # D47：主体登录/注销信号——本包只需要"注销时把 KV 里的记录清掉"
    # （化身本身由内核级联删除 + 发 on_entity_removed）。
    api.register_world_event("on_principal_deleted", _on_principal_deleted)


async def _whoami(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我是谁：主体 + 当前行动的化身 + 化身总数（没有化身时也照常回答）。

    **续玩就在这一句**（``_resume``）：重登 / 换设备后第一次问"我是谁"，顺手把凭据
    指回上次那具——这是唯一做得到的时机（见 ``_resume`` 的说明）。
    """
    principal = api.caller_principal() or ""
    before = api.caller()
    current = await _resume(api)
    name = api.caller_name()
    avatars = _avatars_of(api, principal)
    lines = [f"主体：{name or '（未命名）'}（{principal[:8] or '无'}）"]
    if current:
        entity = api.get_entity(current)
        where = (
            f"({entity.map_id}, {entity.row}, {entity.col})"
            if entity is not None and entity.has_position()
            else "不在世界上"
        )
        note = "" if before else "（已接上你上次操作的那具）"
        lines.append(
            f"当前化身：{entity.name if entity else '（已不存在）'} {where}{note}"
        )
    else:
        lines.append("当前化身：还没有——先创建一具（player_create）")
    lines.append(f"化身总数：{len(avatars)}")
    return {"text": "\n".join(lines)}


async def _avatars_tool(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我的化身清单（含不在世界上的）——同样顺手续玩（``_resume``）。"""
    await _resume(api)
    avatars = _avatars_of(api, api.caller_principal() or "")
    current = api.caller()
    if not avatars:
        return {"text": "你还没有任何化身：用 player_create 创建第一具。"}
    lines = []
    for entity in avatars:
        mark = "← 当前" if entity.id == current else ""
        info = _summary(entity)
        where = (
            f"({info['map_id']}, {info['row']}, {info['col']})"
            if info["in_world"]
            else "不在世界上"
        )
        lines.append(f"- {info['name']} [{entity.id[:8]}] {where} {mark}".rstrip())
    return {"text": "你的化身：\n" + "\n".join(lines)}


async def _create(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """创建化身：造实体 → **认领给当前主体** → 指为当前行动实体。

    三步的顺序有意义：先造（内核不知道它是谁的）→ 认领（写 ``core:account``，
    从此受 D14 保护）→ 指过去（``act_as``）。少了中间那步，新实体只是个路人；
    少了最后一步，玩家得再切一次才操作得到它。
    """
    principal = api.caller_principal() or ""
    if not principal:
        return {"text": "围观（read）凭据不能创建角色：请用玩家身份登录。"}
    name = str(kwargs.get("name") or "").strip() or (api.caller_name() or "无名者")
    tile = _pick_tile(api)
    if tile is None:
        # 空世界：造一具**不在世界上**的化身（D36 合法状态），等地图就绪再放进去
        entity = await api.place_entity(components={_AVATAR: {}}, name=name)
    else:
        # ⚠ 位置一律用**关键字**传：`place_entity(kind, map_id, row, col, …)` 的
        # 第一个位置参数是 `kind`（D41 起只是输入便利），按位置传极易写成
        # "半截位置" → 报错（这个坑在写参考包时真的踩了一次）
        entity = await api.place_entity(
            map_id=tile[0],
            row=tile[1],
            col=tile[2],
            components={_AVATAR: {}},
            name=name,
        )
    await api.claim_avatar(entity.id)  # 内核窄口：写 core:account（D46）
    await api.act_as(entity.id)  # 把当前凭据指过去
    await _remember(api, principal, entity.id)
    where = (
        f"落在 ({tile[0]}, {tile[1]}, {tile[2]})"
        if tile
        else "世界还没有地块，先待在外面"
    )
    return {"text": f"已创建化身「{name}」〔{entity.id[:8]}〕，{where}。"}


async def _switch(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """切换当前行动的化身——**先用自己的 roster 校验归属**，再 act_as。

    这一句 ``if entity_id not in mine`` 是**安全边界**（D46）：内核不校验归属
    （它没有名单），把客户端传来的 id 直接交给 ``api.act_as`` 等于让任何人
    操控任何实体。
    """
    principal = api.caller_principal() or ""
    target = str(kwargs.get("entity_id") or "").strip()
    if not target:
        return {"text": "请给出要切换到的化身 id（见 player_avatars）。"}
    mine = {e.id: e for e in _avatars_of(api, principal)}
    if target not in mine:
        return {"text": "这具不是你的化身，切不了。"}
    await api.act_as(target)
    await _remember(api, principal, target)
    return {"text": f"已切换到「{mine[target].name}」〔{target[:8]}〕。"}


async def _retire(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """退掉一具自己的化身：**解绑（窄口）→ 删除**（D14 保护的是别人的化身）。"""
    principal = api.caller_principal() or ""
    target = str(kwargs.get("entity_id") or "").strip()
    mine = {e.id: e for e in _avatars_of(api, principal)}
    if target not in mine:
        return {"text": "这具不是你的化身，退不了。"}
    if len(mine) <= 1:
        return {"text": "这是你最后一具化身，退掉就没得玩了（想彻底离开请注销账户）。"}
    name = mine[target].name
    cleared = await api.release_avatar(target)  # 解绑 + 清空指向它的凭据指针
    await api.remove_entity(target)  # 现在它不绑账户了，D14 不再拦
    if api.caller() == target:
        await api.act_as(None)  # 自己把自己退了 → 回到"还没有化身"
    if cleared:
        await _forget(api, principal)
    return {"text": f"已退掉化身「{name}」。"}


def _remembered(api: WorlditorPlayAPI, principal: str) -> str:
    """本包记的"这个主体上次操作的是哪具"（KV；没有 → 空串）。"""
    active = api.kv_get(_ACTIVE_KEY, {})
    if not isinstance(active, dict):
        return ""
    return str(active.get(principal) or "")


async def _remember(api: WorlditorPlayAPI, principal: str, entity_id: str) -> None:
    """记下"这个主体上次操作的是哪具"（本包自己的玩法状态）。"""
    active = api.kv_get(_ACTIVE_KEY, {})
    active = dict(active) if isinstance(active, dict) else {}
    active[principal] = entity_id
    await api.kv_set(_ACTIVE_KEY, active)


async def _forget(api: WorlditorPlayAPI, principal: str) -> None:
    active = api.kv_get(_ACTIVE_KEY, {})
    if isinstance(active, dict) and principal in active:
        active = {k: v for k, v in active.items() if k != principal}
        await api.kv_set(_ACTIVE_KEY, active)


async def _on_principal_deleted(api: WorlditorPlayAPI, principal) -> None:
    """账户注销（D47）：内核已删掉该主体的全部化身，这里清自己的记录。"""
    account_id = getattr(principal, "account_id", "")
    if account_id:
        await _forget(api, account_id)


# ---------- 对外服务（软依赖锚点；handler(api, **params)） ----------


async def _service_avatars_of(api: WorlditorPlayAPI, principal: str = "", **_) -> list:
    """某主体的全部化身摘要列表。

    ⚠ **主体事件里要显式传 `principal`**（`on_principal_login` / `_logout` / `_deleted`
    是 HTTP/CLI 路径触发的，没有"当前调用者"上下文，缺省解析出来是空的）。
    工具 handler 里可以省略——那时 `api.caller_principal()` 有值。
    """
    who = str(principal or api.caller_principal() or "")
    return [_summary(e) for e in _avatars_of(api, who)]


async def _service_active_avatar(
    api: WorlditorPlayAPI, principal: str = "", **_
) -> dict:
    """某主体**当前行动的化身**：先看本次凭据指向谁，再看本包记的"上次那具"。

    两个来源都要看：凭据指针是"这台设备现在操作谁"，KV 是"这个主体上次选的是谁"
    （换设备登录后据此恢复）。两边都指向自己的化身时才算数。
    """
    who = str(principal or api.caller_principal() or "")
    mine = {e.id: e for e in _avatars_of(api, who)}
    current = api.caller()
    if current in mine:
        return _summary(mine[current])
    remembered = _remembered(api, who)
    if remembered in mine:
        return _summary(mine[remembered])
    return {}


async def _service_switch_to(api: WorlditorPlayAPI, entity_id: str = "", **_) -> dict:
    """把**当前凭据**切到某具化身（只接受调用方自己的；跨主体一律拒绝）。

    ⚠ 拒绝时抛 ``WorldError`` 而不是 ``ValueError``：``call_service`` 的异常隔离
    会把**其它**异常统一换成"服务执行出错，请稍后再试"（M3：不让提供方的内部
    实现细节漏给调用方），只有 ``WorldError`` 的文案会原样透出。
    """
    who = api.caller_principal() or ""
    mine = {e.id: e for e in _avatars_of(api, who)}
    target = str(entity_id or "")
    if target not in mine:
        raise WorldError("这具不是当前调用方的化身")
    await api.act_as(target)
    await _remember(api, who, target)
    return _summary(mine[target])


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：本包没有自管资源（KV 与化身数据都保留，D44）。"""
