"""worlditor_play_items：背包与物品使用（D8 持有下沉落地，M3 领域包）。

设计要点：
- **持有全下沉**（D8）：背包存 play_data（``bag:<entity_id>`` → {"slots": [...]}），
  内核无 inventories 表；格子容量 BAG_SLOTS、单格堆叠上限 STACK_MAX。
- **操作统一走服务通道**：bag_add/take/count/get 注册为跨包服务（M3 服务机制），
  由引擎在锁内调用（读改写原子）；工具与视图也经服务读写——单一入口。
- **物品定义**（D13）：苹果/面包归本包注册（内核仅喇叭）；use_action 指向
  interaction 包注册的交互动作（eat）。
- **跨包用例**：player 包发出生礼包（bag_add）、interaction 包商贩交易
  （bag_take 收款 / bag_add 交货）、social 包喇叭持有（bag_count/take）。
"""

from __future__ import annotations

from worlditor_mcp.world import ItemDef, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

BAG_SLOTS = 20
STACK_MAX = 99
_BAG_PREFIX = "bag:"

_VIEW_KEY = "items"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    # 物品定义（D13：苹果/面包归 items 包）
    api.register_item_def(
        ItemDef(
            id="apple",
            name="苹果",
            desc="红彤彤的苹果，咬一口又脆又甜。",
            stackable=True,
            use_action="eat",
        ),
        fields=[{"name": "price", "label": "价格", "type": "int"}],
    )
    api.register_item_def(
        ItemDef(
            id="bread",
            name="面包",
            desc="刚出炉的面包，麦香扑鼻。",
            stackable=True,
            use_action="eat",
        )
    )
    # 跨包服务（锁内执行；供 player/interaction/social 等包调用）
    api.register_service("bag_add", _bag_add)
    api.register_service("bag_take", _bag_take)
    api.register_service("bag_count", _bag_count)
    api.register_service("bag_get", _bag_get)
    # MCP 工具
    api.register_tool(
        "world_bag",
        _world_bag,
        description="查看你的背包：物品与数量（物品 id 可用于 world_use）。",
    )
    api.register_tool(
        "world_use",
        _world_use,
        description=(
            "使用背包中的一件物品（item_id 来自 world_bag）：消耗 1 个并触发"
            "该物品的使用效果。"
        ),
        params={"item_id": "string"},
    )
    # 背包视图
    api.register_view(
        _VIEW_KEY,
        title="背包",
        icon="🎒",
        provider={
            "type": "component",
            "url": f"/plays/{api.play_id}/web/bag.js",
        },
    )


# ---------- 背包内核（服务 handler，引擎锁内调用，读改写原子） ----------


def _bag_of(api: WorlditorPlayAPI, entity_id: str) -> list[dict]:
    raw = api.kv_get(f"{_BAG_PREFIX}{entity_id}", None)
    if not isinstance(raw, dict) or not isinstance(raw.get("slots"), list):
        return []
    return [s for s in raw["slots"] if isinstance(s, dict)]


async def _bag_save(api: WorlditorPlayAPI, entity_id: str, slots: list[dict]) -> None:
    await api.kv_set(f"{_BAG_PREFIX}{entity_id}", {"slots": slots})


def _check_count(count: object) -> int:
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise WorldError("count 必须是正整数")
    return count


async def _bag_add(api: WorlditorPlayAPI, **params) -> dict:
    """加物品：优先堆叠未满格，其次开新格；满 → WorldError。返回 {item_id, total}。"""
    entity_id = str(params.get("entity_id") or "")
    item_id = str(params.get("item_id") or "")
    count = _check_count(params.get("count", 1))
    if not entity_id or not item_id:
        raise WorldError("entity_id/item_id 必填")
    if api.get_item_def(item_id) is None:
        raise WorldError(f"物品不存在：{item_id}")
    slots = _bag_of(api, entity_id)
    # 堆叠到未满格
    for slot in slots:
        if slot["item_id"] == item_id and slot["count"] < STACK_MAX:
            add = min(count, STACK_MAX - slot["count"])
            slot["count"] += add
            count -= add
            if count == 0:
                await _bag_save(api, entity_id, slots)
                total = _bag_total(api, entity_id, item_id)
                return {"item_id": item_id, "total": total}
    # 开新格
    while count > 0:
        if len(slots) >= BAG_SLOTS:
            raise WorldError("背包已满")
        add = min(count, STACK_MAX)
        slots.append({"item_id": item_id, "count": add})
        count -= add
    await _bag_save(api, entity_id, slots)
    total = _bag_total(api, entity_id, item_id)
    return {"item_id": item_id, "total": total}


async def _bag_take(api: WorlditorPlayAPI, **params) -> dict:
    """扣物品（整量扣减）；不足 → WorldError。返回 {item_id, total}。"""
    entity_id = str(params.get("entity_id") or "")
    item_id = str(params.get("item_id") or "")
    count = _check_count(params.get("count", 1))
    if not entity_id or not item_id:
        raise WorldError("entity_id/item_id 必填")
    slots = _bag_of(api, entity_id)
    for slot in slots:
        if slot["item_id"] == item_id:
            if slot["count"] < count:
                raise WorldError(f"「{item_id}」数量不足")
            slot["count"] -= count
            if slot["count"] == 0:
                slots.remove(slot)
            await _bag_save(api, entity_id, slots)
            return {"item_id": item_id, "total": _bag_total(api, entity_id, item_id)}
    raise WorldError(f"背包中没有「{item_id}」")


def _bag_total(api: WorlditorPlayAPI, entity_id: str, item_id: str) -> int:
    return sum(s["count"] for s in _bag_of(api, entity_id) if s["item_id"] == item_id)


async def _bag_count(api: WorlditorPlayAPI, **params) -> int:
    """持有数量（读）。"""
    entity_id = str(params.get("entity_id") or "")
    item_id = str(params.get("item_id") or "")
    if not entity_id or not item_id:
        raise WorldError("entity_id/item_id 必填")
    return _bag_total(api, entity_id, item_id)


async def _bag_get(api: WorlditorPlayAPI, **params) -> dict:
    """背包全量（读）：{slots: [{item_id, count}], capacity}。"""
    entity_id = str(params.get("entity_id") or "")
    if not entity_id:
        raise WorldError("entity_id 必填")
    defs = {d["id"]: d for d in api.list_item_defs()}
    slots = []
    for s in _bag_of(api, entity_id):
        defn = defs.get(s["item_id"])
        slots.append(
            {
                "item_id": s["item_id"],
                "name": defn["name"] if defn else s["item_id"],
                "count": s["count"],
            }
        )
    return {"slots": slots, "capacity": BAG_SLOTS, "used": len(slots)}


# ---------- MCP 工具 ----------


def _me(api: WorlditorPlayAPI):
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    if api.get_entity(entity_id) is None:
        raise WorldError(f"实体不存在：{entity_id}")
    return entity_id


async def _world_bag(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我的背包（经服务通道读，锁内原子）。"""
    me = _me(api)
    bag = await api.call_service(api.play_id, "bag_get", entity_id=me)
    lines = [f"{s['name']}×{s['count']}" for s in bag["slots"]]
    text = f"背包（{bag['used']}/{bag['capacity']}）：" + (
        "、".join(lines) if lines else "空的"
    )
    return {**bag, "text": text}


async def _world_use(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """使用物品：交互成功（interact 返回）→ 扣 1。"""
    me = _me(api)
    item_id = str(kwargs.get("item_id") or "")
    if not item_id:
        raise WorldError("item_id 必填")
    defn = api.get_item_def(item_id)
    if defn is None:
        raise WorldError(f"物品不存在：{item_id}")
    if not defn.use_action:
        raise WorldError(f"「{defn.name}」不能使用")
    if (
        await api.call_service(api.play_id, "bag_count", entity_id=me, item_id=item_id)
        < 1
    ):
        raise WorldError(f"你没有「{defn.name}」")
    result = await api.interact(me, me, defn.use_action, item_id=item_id)
    # 交互成功 → 扣 1（命令式持有变更）
    await api.call_service(
        api.play_id, "bag_take", entity_id=me, item_id=item_id, count=1
    )
    return {
        "text": result.text if result else f"使用了「{defn.name}」。",
        "result": result.to_dict() if result else None,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源（服务/工具/视图随生命周期自动清理）。"""
