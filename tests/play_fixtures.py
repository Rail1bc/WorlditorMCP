"""测试夹具：构造"演示玩法包"（插件时代 demo_play 的替代，D3）。

demo_play 已按 D3 删除（领域包即 SDK 模板）；玩法包机制测试需要一个
行为完整的参考玩法包，此处以字符串常量写入 tmp 目录，覆盖：
kind（merchant/sign/door）、交互（talk/trade/read/open/eat/bye/buy_*）、
事件（on_tick / on_entity_enter / on_world_edited + 玩法包自定义 item_used）、
**组件声明**（apple/megaphone 两条标签，D37：原物品定义）、**视图组件**（view.js）、
**部件聚合**（world_whoami 产出 character 块 + ui_hook 展开）、管理页（shop）、
kv 读写、出生礼包。

组件文件（web/*.js）不是字符串常量，而是从 ``tests/fixtures/plays/`` 下
**提交在案**的参考实现复制——那两份文件同时是"视图组件样式约定"与
"版本串一致性"两条守卫的对象，也是玩法包作者可照抄的活例子。
"""

from __future__ import annotations

import shutil
from pathlib import Path

PLAY_ID = "worlditor_play_demo"
PROBE_ID = "worlditor_play_probe"
_REFERENCE_WEB = (
    Path(__file__).resolve().parent / "fixtures" / "plays" / PLAY_ID / "web"
)
_PROBE_WEB = Path(__file__).resolve().parent / "fixtures" / "plays" / PROBE_ID / "web"

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
from worlditor_mcp.world import (
    InteractionRequest,
    InteractionResult,
    MenuButton,
    UiBlock,
)

APPLE_ITEM = "apple"
MEGAPHONE_ITEM = "megaphone"
FOREST_ROW = 4  # 迷雾森林起始行（row >= 4 视为迷雾区域）

_GOLD = "gold"  # 玩家 stat 组件里的金币键（演示玩法数据自管）
_BAG_KEY = "bag"  # play_data 中的背包（D8：持有下沉，演示 kv 自管持有）
# v2（D32）：玩法数据按**组件**分组——组件名 = source:name 信封；
# 玩法包不得写 core:（D33），所以这里用 local: 命名空间。
_STAT = "local:stat"  # 玩家玩法数据组件（金币 / 精力）
_SIGN = "local:sign"  # 告示牌动态数据
_DOOR = "local:door"  # 木门状态


def _card_rows(components: dict) -> list[dict]:
    """组件 → 角色卡行（label = 「组件名 · 字段名」；UiBlock character 的数据源）。"""
    rows: list[dict] = []
    for comp in sorted(components or {}):
        data = components.get(comp)
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            rows.append({"label": f"{comp} · {key}", "value": value})
    return rows


def _bag(api: WorlditorPlayAPI) -> dict:
    """读背包：{item_id: count}（演示玩法数据自管持有，D8）。"""
    raw = api.kv_get(_BAG_KEY, {})
    return raw if isinstance(raw, dict) else {}


async def _bag_add(api: WorlditorPlayAPI, item_id: str, count: int) -> dict:
    bag = _bag(api)
    bag[item_id] = bag.get(item_id, 0) + count
    await api.kv_set(_BAG_KEY, bag)
    return bag


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
    api.register_entity_kind("door", interactions=("open",), label="门")
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
    api.register_world_event("on_world_edited", _on_world_edited)
    api.register_tool(
        "world_whoami",
        _whoami,
        description="查看你的当前身份",
    )
    # 物品**类型** → 组件声明（D37）：货单引用的两个货品各登记一条标签——标签名
    # 就是「包自己的物品标识」，字段 schema 承接原 ItemDef 的字段化定义；
    # 原 ItemDef.use_action 由 interaction 名承担（见上面的 eat 交互）。
    api.register_entity_tag(
        APPLE_ITEM,
        label="苹果",
        fields=[{"name": "heal", "label": "回复", "type": "int", "default": 3}],
    )
    api.register_entity_tag(
        MEGAPHONE_ITEM,
        label="喇叭",
        fields=[{"name": "volume", "label": "音量", "type": "int", "default": 10}],
    )
    # 实体模板的**包声明**（D22）：随包卸载/停用消失，重新启用即恢复。
    # 它同时是 D37 的示范——"管理员手工维护的物品定义"原来靠 user_data 标记区分，
    # 现在这条"包声明 vs 本地数据"的区分由**存储位置**承担（本地模板落 templates 表，
    # 见管理端 save_template）。测试用它验"停用只清代码声明、不碰本地数据"。
    api.register_entity_template(
        "pkg_npc",
        "包声明 NPC",
        {"kind": "npc", "name": "路人", "components": {"local:stat": {"hp": 10}}},
    )
    # 视图组件（G3/D7）：参考实现 = tests/fixtures/plays/.../web/view.js
    api.register_view(
        "demo",
        title="演示",
        icon="🧪",
        provider={"type": "component", "url": f"/plays/{api.play_id}/web/view.js"},
    )
    # 管理页（v0.1.12 协议）：货单管理——actions 演示玩法包自管数据语义
    api.register_admin_page(
        "shop",
        title="货单管理",
        icon="🧺",
        component_url="/plays/worlditor_play_demo/web/admin-shop.js",
        actions={
            "list": _admin_shop_list,
            "set_price": _admin_shop_set_price,
        },
    )


async def _admin_shop_list(api: WorlditorPlayAPI, **params) -> dict:
    """管理页动作：货单（kv 覆盖层 {item_id: price}，默认 = data/shop.json）。"""
    raw = api.kv_get("shop_prices", {})
    prices = raw if isinstance(raw, dict) else {}
    merged = {item_id: dict(info) for item_id, info in _SHOP.items()}
    for item_id, price in prices.items():
        if item_id in merged:
            merged[item_id]["price"] = price
        else:
            merged[item_id] = {"price": price, "label": item_id}
    return {"prices": merged}


async def _admin_shop_set_price(api: WorlditorPlayAPI, **params) -> dict:
    """管理页动作：改价（写入 play_data，命名空间 = 本包 id）。"""
    item_id = str(params.get("item_id") or "")
    price = params.get("price")
    if item_id not in _SHOP:
        raise ValueError(f"商品不存在：{item_id}")
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise ValueError("价格必须是非负整数")
    raw = api.kv_get("shop_prices", {})
    prices = raw if isinstance(raw, dict) else {}
    prices[item_id] = price
    await api.kv_set("shop_prices", prices)
    return {"item_id": item_id, "price": price}


async def _whoami(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """MCP 动态工具演示：身份经 api.caller() 读取（G2）。

    同时演示**部件聚合**（DESIGN §4.5）：返回 character 块并交给 ui_hook
    服务端展开——其他包向 character 注入的面板会追加进来；无人注入时
    就是块本身（软依赖：注册与否决定，而非由本包探测）。
    """
    entity_id = api.caller()
    entity = api.get_entity(entity_id) if entity_id else None
    card = UiBlock(
        kind="character",
        title=entity.name if entity else "（无身份）",
        data={"attrs": _card_rows(dict(entity.components)) if entity else []},
    )
    card = await api.apply_ui_hooks(card)
    return {
        "text": f"我是 {entity_id}",
        "ui": card.to_dict() if card else None,
    }


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
    """买苹果：命令式 API 写法（D12：无 effects，handler 直接调原语）。"""
    if req.target is None or req.target.kind != "merchant":
        return InteractionResult(text="这里没有卖苹果的。")
    gold = await api.get_data(req.entity_id, _GOLD, component=_STAT) or 0
    price = _SHOP.get(APPLE_ITEM, {}).get("price", 5)
    if gold < price:
        return InteractionResult(
            text=f"钱不够……一个苹果要 {price} 金（你只有 {gold} 金）。"
        )
    await api.set_data(req.entity_id, _GOLD, gold - price, component=_STAT)
    await _bag_add(api, APPLE_ITEM, 1)
    return InteractionResult(
        text=f"「给你，新鲜摘的苹果！」（花费 {price} 金）"
    )


async def _buy_megaphone(
    api: WorlditorPlayAPI, req: InteractionRequest
) -> InteractionResult:
    """买喇叭：命令式 API 写法（A1：两种写法演示）。"""
    if req.target is None or req.target.kind != "merchant":
        return InteractionResult(text="这里没有卖喇叭的。")
    gold = await api.get_data(req.entity_id, _GOLD, component=_STAT) or 0
    price = _SHOP.get(MEGAPHONE_ITEM, {}).get("price", 10)
    if gold < price:
        return InteractionResult(
            text=f"钱不够……一个喇叭要 {price} 金（你只有 {gold} 金）。"
        )
    await api.set_data(req.entity_id, _GOLD, gold - price, component=_STAT)
    await _bag_add(api, MEGAPHONE_ITEM, 1)
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
    """开门：演示组件写入（v2 / D34：**所有实体都不阻挡**，开门只是写数据）。

    原实现靠 ``set_state(block_move=False)`` 解除阻挡——D33 起玩法包不得写
    ``core:``，且 D34 已整体移除阻挡机制，所以这里退化为一次普通的组件写。
    """
    if req.target is None or req.target.kind != "door":
        return InteractionResult(text="这不是一扇能开的门。")
    if req.target.component(_DOOR).get("open"):
        return InteractionResult(text="木门已经开着呢。")
    await api.set_component(req.target.id, _DOOR, {"open": True})
    return InteractionResult(text="吱呀——木门缓缓打开，迷雾森林的凉意扑面而来。")


async def _eat(api: WorlditorPlayAPI, req: InteractionRequest) -> InteractionResult:
    """吃苹果：interaction 名即「用途」（D37：原 ItemDef.use_action → interaction）。

    物品标识由玩法包自己从 ``args`` 里取（``interact(..., args={"item": "apple"})``，
    内核不解释 args 的内容），恢复精力也在本 handler 内完成——D37 之后内核不再代发
    ``on_item_used``，「用了一个东西」改由本包 ``emit`` 自定义事件（事件名开放，D1/G8）。
    """
    item_id = str((req.args or {}).get("item") or APPLE_ITEM)
    bag = _bag(api)
    if bag.get(item_id, 0) < 1:
        return InteractionResult(text="你身上没有苹果。")
    bag[item_id] -= 1
    await api.kv_set(_BAG_KEY, bag)
    # 原 _on_item_used handler 的逻辑并入本处（D37：内核事件已删除）
    if item_id == APPLE_ITEM:
        energy = (await api.get_data(req.entity_id, "energy", component=_STAT) or 0) + 1
        await api.set_data(req.entity_id, "energy", energy, component=_STAT)
    # 玩法包自定义事件：演示 D37 的替代路径（log=True 落世界日志，可被别的包订阅）
    await api.emit(
        "item_used",
        {"entity_id": req.entity_id, "item": item_id},
        log=True,
    )
    return InteractionResult(text="咔嚓——又脆又甜！感觉精力恢复了一些。")


async def _on_tick(api: WorlditorPlayAPI, dt: float) -> None:
    """演示 tick 状态机：告示牌定期更新"张贴时间"。"""
    for entity in api.list_entities():
        if entity.kind == "sign":
            await api.set_data(
                entity.id, "last_updated", time.strftime("%H:%M:%S"), component=_SIGN
            )


async def _on_entity_enter(
    api: WorlditorPlayAPI, entity, map_id: str, row: int, col: int
) -> None:
    """演示事件驱动行为：进入迷雾区域发自定义事件（说话下沉后，M2/D1）。"""
    if row >= FOREST_ROW and entity.kind == "player":
        await api.emit(
            "fog_enter",
            {"entity_id": entity.id, "row": row, "text": "雾越来越浓，你几乎看不清三米以外的东西……"},
            log=True,
        )


async def _on_world_edited(api: WorlditorPlayAPI, what) -> None:
    """演示编辑事件响应：新玩家实体出生礼包（初始金币）。"""
    if isinstance(what, dict) and what.get("op") == "place_entity":
        entity = api.get_entity(what["entity_id"])
        if (
            entity is not None
            and entity.kind == "player"
            and _GOLD not in entity.component(_STAT)
        ):
            await api.set_data(entity.id, _GOLD, 100, component=_STAT)


def teardown(api: WorlditorPlayAPI) -> None:
    """玩法包卸载钩子（可选）：演示用，无事可做。"""
'''


_PROBE_MAIN = '''"""测试探针玩法包：一个工具 + 一个视图 + 一个管理页。

与 worlditor_play_demo 分开成两个包，才能验证：
- "某世界只启用其中一个"时工具被拒、视图消失（D21 激活过滤的端到端行为）
- SSE 自动刷新：停用本包 → 玩家端「探针」tab 消失（`plays_changed` 信号）
- **管理页之间切换**：宿主必须重新加载组件，否则会渲染成上一个页面的界面
  （`web/admin-ping.js` 里的 `PROBE-PAGE-MARKER` 是验收锚点）
"""

from __future__ import annotations

from worlditor_mcp.world.play.api import WorlditorPlayAPI


def setup(api: WorlditorPlayAPI, context) -> None:
    """入口：注册探针工具、探针视图与管理页。"""
    api.register_tool("world_ping", _ping, description="探针：返回 pong")
    api.register_view(
        "ping",
        title="探针",
        icon="📡",
        provider={"type": "component", "url": f"/plays/{api.play_id}/web/view.js"},
    )
    api.register_admin_page(
        "ping",
        title="探针面板",
        icon="📡",
        component_url=f"/plays/{api.play_id}/web/admin-ping.js",
        actions={"info": _admin_info},
    )


async def _ping(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    return {"text": "pong"}


async def _admin_info(api: WorlditorPlayAPI, **params) -> dict:
    """管理页动作：返回一个可断言的固定文案。"""
    return {"text": "探针面板已连接"}


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
'''


def install_probe_play(plays_root: Path) -> Path:
    """装一个最小玩法包（工具 + 视图 + 管理页），供激活过滤/SSE/切页对比用。"""
    play_dir = plays_root / PROBE_ID
    play_dir.mkdir(parents=True, exist_ok=True)
    (play_dir / "play.yaml").write_text(
        "name: worlditor_play_probe\n"
        "display_name: 探针玩法包\n"
        "version: 0.1.0\n"
        "author: test\n"
        "requires:\n"
        '  worlditor: ">=0.1.0"\n'
        "  plays: []\n",
        encoding="utf-8",
    )
    (play_dir / "main.py").write_text(_PROBE_MAIN, encoding="utf-8")
    web_dir = play_dir / "web"
    web_dir.mkdir(exist_ok=True)
    # 组件文件从**提交在案**的参考实现复制（同 install_demo_play 的约定）
    for name in ("view.js", "admin-ping.js"):
        shutil.copyfile(_PROBE_WEB / name, web_dir / name)
    return play_dir


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
    web_dir = play_dir / "web"
    web_dir.mkdir(exist_ok=True)
    # 组件文件从仓库**提交在案**的参考实现复制，而不是就地写占位符：
    # 视图组件样式约定（v0.1.17）与版本串一致性（v0.5.2）两条守卫因此指向
    # 真实文件（tests/fixtures/plays/…/web/），而不是测试自己刚写的东西。
    for name in ("view.js", "admin-shop.js"):
        shutil.copyfile(_REFERENCE_WEB / name, web_dir / name)
    return play_dir
