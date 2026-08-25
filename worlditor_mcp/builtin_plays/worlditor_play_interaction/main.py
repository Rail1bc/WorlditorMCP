"""worlditor_play_interaction：交互（M3 领域包）。

职责（DESIGN §6 / D13）：
- 种子演示实体的 kind 与交互：merchant（talk/trade）、sign（read）、
  door（open，block_move 内核物理阻挡）；苹果/面包的 eat 效果。
- 交互弹窗编排 = UiBlock（text/list/menu + actions），WebUI 渲染；本包
  提供 handler 内容（命令式调用原语，D12）。
- **商贩交易跨包**：buy_* 扣玩家金币（attrs）+ 调 items 包 bag_add 交货。

依赖：worlditor_play_items（货品入玩家背包）。
"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4engine import WorldError
from worlditor_mcp.world.v4model import InteractionResult, MenuButton, UiBlock

ITEMS_PLAY = "worlditor_play_items"
_GOLD_ATTR = "gold"

# 商贩货单：item_id -> (价格, 标签)（定价 = 本包玩法内容）
_SHOP = {
    "apple": (5, "苹果"),
    "bread": (3, "面包"),
    "megaphone": (10, "喇叭"),
}


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    # 种子实体 kind（D13：实体由内核播种，kind 与交互由本包注册）
    api.register_entity_kind("merchant", interactions=("talk", "trade"), label="商贩")
    api.register_entity_kind("sign", interactions=("read",), label="告示牌")
    api.register_entity_kind(
        "door", block_move=True, interactions=("open",), label="门"
    )
    # 交互动作（全局注册；可用动作 = kind 声明 ∪ 全局注册表，C3）
    api.register_interaction("talk", _talk, label="打招呼")
    api.register_interaction("trade", _trade, label="看看货")
    api.register_interaction("read", _read, label="阅读")
    api.register_interaction("open", _open, label="开门")
    api.register_interaction("eat", _eat, label="吃")
    api.register_interaction("buy_apple", _buy_apple, label="买苹果")
    api.register_interaction("buy_bread", _buy_bread, label="买面包")
    api.register_interaction("buy_megaphone", _buy_megaphone, label="买喇叭")
    # agent 交互通道
    api.register_tool(
        "world_interact",
        _world_interact,
        description=(
            "与世界中的实体交互：target_id 为目标实体，action 为动作名"
            "（/scene 或 world_who 可查看目标与可用动作）。返回交互结果。"
        ),
        params={"target_id": "string", "action": "string"},
    )


# ---------- 交互 handler（D12：命令式调用原语，无 effects） ----------


def _target(api: WorlditorPlayAPI, req, kind: str):
    if req.target is None or req.target.kind != kind:
        raise WorldError("目标不对")
    return req.target


async def _talk(api: WorlditorPlayAPI, req) -> InteractionResult:
    _target(api, req, "merchant")
    return InteractionResult(
        text="商贩·阿福笑眯眯地看着你：「你好呀！我是阿福，镇上的老商贩。要来点什么吗？」",
        ui=UiBlock(
            kind="text",
            text="商贩·阿福笑眯眯地看着你：「你好呀！我是阿福，镇上的老商贩。要来点什么吗？」",
            actions=[
                MenuButton(label="看看货", action="trade"),
                MenuButton(label="道别", action="bye"),
            ],
        ),
    )


async def _trade(api: WorlditorPlayAPI, req) -> InteractionResult:
    _target(api, req, "merchant")
    items = [
        {"label": f"{label}（{price} 金）", "value": item_id}
        for item_id, (price, label) in _SHOP.items()
    ]
    return InteractionResult(
        text="阿福的货担：苹果 5 金、面包 3 金、喇叭 10 金。",
        ui=UiBlock(
            kind="list",
            title="阿福的货单",
            items=items,
            actions=[
                MenuButton(label="买苹果（5金）", action="buy_apple"),
                MenuButton(label="买面包（3金）", action="buy_bread"),
                MenuButton(label="买喇叭（10金）", action="buy_megaphone"),
                MenuButton(label="道别", action="bye"),
            ],
        ),
    )


async def _buy(api: WorlditorPlayAPI, req, item_id: str) -> InteractionResult:
    """通用购买：金币校验 → 扣金（attrs）→ items 服务交货。"""
    _target(api, req, "merchant")
    price, label = _SHOP.get(item_id, (None, None))
    if price is None:
        return InteractionResult(text="阿福摊摊手：「这个我不卖。」")
    gold = api.get_attrs(req.entity_id).get(_GOLD_ATTR, 0)
    if gold < price:
        return InteractionResult(
            text=f"钱不够……{label}要 {price} 金（你只有 {gold} 金）。"
        )
    await api.set_attrs(req.entity_id, {_GOLD_ATTR: gold - price})
    await api.call_service(
        ITEMS_PLAY, "bag_add", entity_id=req.entity_id, item_id=item_id, count=1
    )
    return InteractionResult(text=f"「给你，新鲜{label}！」（花费 {price} 金）")


async def _buy_apple(api: WorlditorPlayAPI, req) -> InteractionResult:
    return await _buy(api, req, "apple")


async def _buy_bread(api: WorlditorPlayAPI, req) -> InteractionResult:
    return await _buy(api, req, "bread")


async def _buy_megaphone(api: WorlditorPlayAPI, req) -> InteractionResult:
    return await _buy(api, req, "megaphone")


async def _read(api: WorlditorPlayAPI, req) -> InteractionResult:
    _target(api, req, "sign")
    return InteractionResult(
        text="小镇公告：明日广场有集市，欢迎各位摆摊！",
        ui=UiBlock(kind="text", text="小镇公告：明日广场有集市，欢迎各位摆摊！"),
    )


async def _open(api: WorlditorPlayAPI, req) -> InteractionResult:
    _target(api, req, "door")
    if req.target.state.get("open"):
        return InteractionResult(text="木门已经开着呢。")
    await api.set_state(req.target.id, {"open": True, "block_move": False})
    return InteractionResult(text="吱呀——木门缓缓打开，迷雾森林的凉意扑面而来。")


async def _eat(api: WorlditorPlayAPI, req) -> InteractionResult:
    """吃（苹果/面包 use 效果）：精力 +1（持有扣减由 items 包 world_use 负责）。"""
    energy = api.get_attrs(req.entity_id).get("energy", 0) + 1
    await api.set_attrs(req.entity_id, {"energy": energy})
    return InteractionResult(text="咔嚓——又脆又甜！感觉精力恢复了一些。")


# ---------- MCP 工具 ----------


async def _world_interact(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """agent 交互通道：interact(me, target, action)。"""
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    target_id = str(kwargs.get("target_id") or "")
    action = str(kwargs.get("action") or "")
    if not target_id or not action:
        raise WorldError("target_id/action 必填")
    result = await api.interact(entity_id, target_id, action)
    return {
        "text": result.text if result else "（无回应）",
        "ui": result.ui.to_dict() if result and result.ui else None,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
