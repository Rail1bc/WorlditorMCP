"""测试夹具：构造"演示玩法包"（插件时代 demo_play 的替代，D3）。

demo_play 已按 D3 删除（领域包即 SDK 模板）；玩法包机制测试需要一个
行为完整的参考玩法包，此处以字符串常量写入 tmp 目录，覆盖：
kind（merchant/sign/door）、交互（talk/trade/read/open/eat/bye/buy_*）、
事件（on_tick / on_entity_enter / on_item_used / on_world_edited）、
物品（apple/megaphone）、kv 读写、出生礼包。
"""

from __future__ import annotations

from pathlib import Path

PLAY_ID = "worlditor_play_demo"

_SHOP_JSON = """{
  "apple": { "price": 5, "label": "苹果" },
  "megaphone": { "price": 10, "label": "喇叭" }
}
"""

_MAIN_PY = '''"""测试夹具玩法包：worlditor_play_demo（行为与插件时代 demo_play 一致）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from worlditor_mcp.world.play.api import WorlditorPlayAPI
from worlditor_mcp.world.v4model import (
    Effect,
    InteractionRequest,
    InteractionResult,
    MenuButton,
    UiBlock,
)

APPLE_ITEM = "apple"
MEGAPHONE_ITEM = "megaphone"
FOREST_ROW = 4  # 迷雾森林起始行（row >= 4 视为迷雾区域）

_GOLD = "gold"  # 玩家 attrs 中的金币键（演示 attrs 自管玩法数据）


def _load_shop() -> dict:
    """货单数据（data/shop.json）：{item_id: {"price": int, "label": str}}。"""
    path = Path(__file__).parent / "data" / "shop.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


_SHOP = _load_shop()


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_entity_kind("merchant", interactions=("talk", "trade"), label="商贩")
    api.register_entity_kind("sign", interactions=("read",), label="告示牌")
    api.register_entity_kind("door", block_move=True, interactions=("open",), label="门")
    api.register_interaction("talk", _talk, label="打招呼")
    api.register_interaction("trade", _trade, label="看看货")
    api.register_interaction("buy_apple", _buy_apple, label="买苹果（5金）")
    api.register_interaction("buy_megaphone", _buy_megaphone, label="买喇叭（10金）")
    api.register_interaction("bye", _bye, label="道别")
    api.register_interaction("read", _read, label="阅读")
    api.register_interaction("open", _open, label="开门")
    api.register_interaction("eat", _eat, label="吃")
    api.register_world_event("on_tick", _on_tick, interval=5)
    api.register_world_event("on_entity_enter", _on_entity_enter)
    api.register_world_event("on_item_used", _on_item_used)
    api.register_world_event("on_world_edited", _on_world_edited)


async def _talk(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """打招呼：演示 text + menu 对话流。"""
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


async def _trade(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """查看货单：演示 list 界面 + 购买入口。"""
    items = [
        {"label": f"{info['label']}（{info['price']} 金）", "value": item_id}
        for item_id, info in _SHOP.items()
    ]
    return InteractionResult(
        text="阿福的货担：苹果 5 金、喇叭 10 金。",
        ui=UiBlock(
            kind="list",
            title="阿福的货单",
            items=items,
            actions=[
                MenuButton(label="买苹果（5金）", action="buy_apple"),
                MenuButton(label="买喇叭（10金）", action="buy_megaphone"),
                MenuButton(label="道别", action="bye"),
            ],
        ),
    )


async def _buy_apple(
    api: WorlditorPlayAPI, req: InteractionRequest
) -> InteractionResult:
    """买苹果：声明式 effects 写法（v0.3.0 内核结算，D12 后删除）。"""
    if req.target is None or req.target.kind != "merchant":
        return InteractionResult(text="这里没有卖苹果的。")
    gold = api.get_attrs(req.entity_id).get(_GOLD, 0)
    price = _SHOP.get(APPLE_ITEM, {}).get("price", 5)
    if gold < price:
        return InteractionResult(
            text=f"钱不够……一个苹果要 {price} 金（你只有 {gold} 金）。"
        )
    return InteractionResult(
        text=f"「给你，新鲜摘的苹果！」（花费 {price} 金）",
        effects=[
            Effect("set_attrs", {"patch": {_GOLD: gold - price}}),
            Effect("give_item", {"item_id": APPLE_ITEM, "count": 1}),
        ],
    )


async def _buy_megaphone(
    api: WorlditorPlayAPI, req: InteractionRequest
) -> InteractionResult:
    """买喇叭：命令式 API 写法（A1：两种写法演示）。"""
    if req.target is None or req.target.kind != "merchant":
        return InteractionResult(text="这里没有卖喇叭的。")
    gold = api.get_attrs(req.entity_id).get(_GOLD, 0)
    price = _SHOP.get(MEGAPHONE_ITEM, {}).get("price", 10)
    if gold < price:
        return InteractionResult(
            text=f"钱不够……一个喇叭要 {price} 金（你只有 {gold} 金）。"
        )
    await api.set_attrs(req.entity_id, {_GOLD: gold - price})
    await api.give_item(req.entity_id, MEGAPHONE_ITEM, 1)
    return InteractionResult(
        text=f"「喇叭拿好，喊一嗓子全镇都能听见！」（花费 {price} 金）"
    )


async def _bye(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    return InteractionResult(text="「慢走啊，常来逛逛！」")


async def _read(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """阅读告示牌：演示 kv（namespace 隔离）读写。"""
    reads = api.kv_get("bulletin_reads", 0) + 1
    await api.kv_set("bulletin_reads", reads)
    text = "小镇公告：明日广场有集市，欢迎各位摆摊！"
    return InteractionResult(
        text=f"{text}\\n（告示牌已被阅读 {reads} 次）",
        ui=UiBlock(kind="text", text=text),
    )


async def _open(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """开门：演示 state 变更（门开 → block_move 解除）。"""
    if req.target is None or req.target.kind != "door":
        return InteractionResult(text="这不是一扇能开的门。")
    if req.target.state.get("open"):
        return InteractionResult(text="木门已经开着呢。")
    await api.set_state(req.target.id, {"open": True, "block_move": False})
    return InteractionResult(text="吱呀——木门缓缓打开，迷雾森林的凉意扑面而来。")


async def _eat(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """吃苹果：物品 use 交互（req.item_id 由 use 流程注入）。"""
    item_id = req.item_id or APPLE_ITEM
    if api.count_item(req.entity_id, item_id) < 1:
        return InteractionResult(text="你身上没有苹果。")
    await api.take_item(req.entity_id, item_id, 1)
    return InteractionResult(text="咔嚓——又脆又甜！感觉精力恢复了一些。")


async def _on_tick(api: WorlditorPlayAPI, dt: float) -> None:
    """演示 tick 状态机：告示牌定期更新"张贴时间"。"""
    for entity in api.list_entities():
        if entity.kind == "sign":
            await api.set_state(entity.id, {"last_updated": time.strftime("%H:%M:%S")})


async def _on_entity_enter(
    api: WorlditorPlayAPI, entity, map_id: str, row: int, col: int
) -> None:
    """演示事件驱动行为：进入迷雾区域给出提示（cell 级说话）。"""
    if row >= FOREST_ROW and entity.kind in ("player", "agent"):
        await api.say(entity.id, "雾越来越浓，你几乎看不清三米以外的东西……")


async def _on_item_used(
    api: WorlditorPlayAPI, entity, item_id: str, count: int, args: dict, result
) -> None:
    """演示事件响应：吃苹果恢复精力（attrs 玩法数据自管）。"""
    if item_id == APPLE_ITEM and entity is not None:
        energy = api.get_attrs(entity.id).get("energy", 0) + 1
        await api.set_attrs(entity.id, {"energy": energy})


async def _on_world_edited(api: WorlditorPlayAPI, what) -> None:
    """演示编辑事件响应：新玩家/agent 实体出生礼包（初始金币）。"""
    if isinstance(what, dict) and what.get("op") == "place_entity":
        entity = api.get_entity(what["entity_id"])
        if (
            entity is not None
            and entity.kind in ("player", "agent")
            and "gold" not in entity.attrs
        ):
            await api.set_attrs(entity.id, {"gold": 100})


def teardown(api: WorlditorPlayAPI) -> None:
    """玩法包卸载钩子（可选）：演示用，无事可做。"""
'''


def install_demo_play(plays_root: Path) -> Path:
    """把演示玩法包写入 plays_root/，返回其目录（供 PlayLoader 发现）。"""
    play_dir = plays_root / PLAY_ID
    play_dir.mkdir(parents=True, exist_ok=True)
    (play_dir / "play.yaml").write_text(
        "name: worlditor_play_demo\n"
        "display_name: 演示玩法包\n"
        "version: 0.1.0\n"
        "author: worlditor\n"
        "requires:\n"
        '  worlditor: ">=0.3.0"\n'
        "  plays: []\n",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(_MAIN_PY, encoding="utf-8")
    data_dir = play_dir / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "shop.json").write_text(_SHOP_JSON, encoding="utf-8")
    return play_dir
