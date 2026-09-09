"""worlditor_play_player：玩家档（玩家部件模式，DESIGN §4.5）。

职责（阶段 1 拆分后）：
- **角色视图（玩家聚合界面）**：world_profile 工具返回角色卡 UiBlock——
  其他包经 ui_hook 向 character 块注入部件面板（items 包注入背包面板 =
  「背包追加到玩家界面」），视图组件用 UiBlockRenderer 通用渲染。
- **world_profile 工具**：我的角色信息（attrs + 聚合 ui）。

设计：玩家 = 内核身份实体（player/agent kind，身份红线在内核）+ **可追加
部件**——出生礼包、背包、技能树等各为独立部件包（本包只以通用概念描述，
不引用任何具体部件包）：
- 部件信息文本由部件包自己的工具提供（背包 = world_bag）；
- 部件面板 UI 由部件包 ui_hook 注入（hook 注册与否 = 天然软依赖）；
- 本包只描述"我是谁、我的属性"，从不搬运部件数据。
"""

from __future__ import annotations

from worlditor_mcp.world import UiBlock, WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

_VIEW_KEY = "player"


def setup(api: WorlditorPlayAPI, context) -> None:
    """玩法包入口（由内核 PlayLoader 调用）。"""
    api.register_tool(
        "world_profile",
        _world_profile,
        description="查看你的角色信息：名称/类型与属性（部件信息见各部件工具，"
        "如背包 world_bag）。",
    )
    api.register_view(
        _VIEW_KEY,
        title="角色",
        icon="🧍",
        provider={
            "type": "component",
            "url": f"/plays/{api.play_id}/web/profile.js",
        },
    )


def _me(api: WorlditorPlayAPI):
    entity_id = api.caller()
    if entity_id is None:
        raise WorldError("无法确定调用者身份")
    entity = api.get_entity(entity_id)
    if entity is None:
        raise WorldError(f"实体不存在：{entity_id}")
    return entity


async def _world_profile(api: WorlditorPlayAPI, ctx, **kwargs) -> dict:
    """我的角色卡：attrs + 聚合 ui（角色卡 + 各包 hook 注入的部件面板）。

    玩家壳零部件引用：背包面板由 items 包 ui_hook 注入（本包无感知）；
    背包文本信息用 items 包的 world_bag 工具（职责归部件包）。
    """
    me = _me(api)
    text = f"{me.name}（{me.kind}）：" + "、".join(
        f"{k}={v}" for k, v in me.attrs.items()
    )
    card = UiBlock(
        kind="character",
        data={
            "avatar": "🧍",
            "attrs": [{"label": k, "value": str(v)} for k, v in me.attrs.items()],
        },
    )
    card = await api.apply_ui_hooks(card)
    return {
        "text": text,
        "name": me.name,
        "kind": me.kind,
        "attrs": dict(me.attrs),
        "ui": card.to_dict() if card else None,
    }


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：无自管资源。"""
