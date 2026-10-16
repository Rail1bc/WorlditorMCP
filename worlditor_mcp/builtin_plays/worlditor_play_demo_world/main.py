"""worlditor_play_demo_world：演示世界（把一张完整示例地图导入世界）。

职责：**只做内容导入**——读取本包 ``world.json``，把地图、地块与连接、静态
实体一次写进世界；地图已存在则整体跳过（幂等，不覆盖用户改动）。

- v0.2.0 起**内核不再内置任何世界内容**：`store.py` 只创建一个空的"默认世界"，
  地图/地块/实体全部由本包（或用户经管理端地图编辑器）提供——想换世界主题，
  停用本包换成你自己的世界包即可。
- **导入走 `api.import_bundle`（单事务）**：41 个地块 + 3 个实体要么全落盘、
  要么一个字节都不写。逐条 `create_location` / `place_entity` 的写法在"导入到
  一半抛错"时会留下半张世界，而"地图已存在则跳过"的幂等判断又会让重跑**假装
  成功**（GAPS G55）——本包是这条 API 的参考实现。
- 本包**不注册组件声明与交互**：商贩·阿福 / 告示牌 / 木门只是实体数据；它们的
  行为（打招呼/交易/阅读/开门）原先由内置 interaction 包提供，该包 **v0.7.0 起
  已废弃**——现在归社区包（软依赖：没有对应包时实体照样在地图上，只是没有可
  交互动作）。
- 卸载/停用本包**不删除**已导入的数据（数据归用户）；要清空请用管理端地图
  编辑器删除地图。
- ``setup`` 是 async（内核 PlayLoader 自 v0.2.0 起支持 await setup，用于这类
  需要写世界的导入型包）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from worlditor_mcp.world.play.api import WorlditorPlayAPI

_DATA_FILE = Path(__file__).with_name("world.json")
_DEFAULT_MAP_ID = "default"
_DEFAULT_WORLD_ID = "default"


def _load() -> dict[str, Any]:
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


async def setup(api: WorlditorPlayAPI, context) -> None:
    """导入 world.json 的世界数据（幂等：地图已存在则跳过；单事务落盘）。"""
    data = _load()
    map_def = data.get("map") or {}
    map_id = str(map_def.get("id") or _DEFAULT_MAP_ID)
    if api.get_map(map_id) is not None:
        return  # 地图已存在（用户可能改过）——不覆盖
    # 归属默认世界（管理端「世界与地图」页按世界列地图；默认世界由内核播种）。
    # 默认世界被删过 → 传 None：地图照常导入，只是未归属。
    world_id = (
        _DEFAULT_WORLD_ID if api.get_world(_DEFAULT_WORLD_ID) is not None else None
    )
    # D41：实体 = 组件字典——内容里的 `components` **就是**实体带的全部能力/数据。
    # 这里用共享的 `local:` 命名空间（内容方不占任何玩法包的命名空间），
    # 于是"给商贩加行为"的玩法包只要声明 `local:merchant` 即可对接（§12.6）。
    await api.import_bundle(
        map_def,
        locations=data.get("locations") or [],
        entities=data.get("entities") or [],
        world_id=world_id,
    )


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：已导入的世界数据不回收（数据归用户，管理端可编辑/删除）。"""
