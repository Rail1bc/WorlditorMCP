"""worlditor_play_demo_world：演示世界（把一张完整示例地图导入世界）。

职责：**只做内容导入**——读取本包 ``world.json``，把地图、地块与连接、静态
实体写进世界；地图已存在则整体跳过（幂等，不覆盖用户改动）。

- v0.2.0 起**内核不再内置任何世界内容**：`store.py` 只创建一个空的"默认世界"，
  地图/地块/实体全部由本包（或用户经管理端地图编辑器）提供——想换世界主题，
  停用本包换成你自己的世界包即可。
- 本包**不注册 kind 与交互**：商贩·阿福 / 告示牌 / 木门的行为由 interaction
  包提供（软依赖：未装 interaction 时实体照样在地图上，只是没有可交互动作）。
- 卸载/停用本包**不删除**已导入的数据（数据归用户）；要清空请用管理端地图
  编辑器删除地图。
- ``setup`` 是 async（内核 PlayLoader 自 v0.2.0 起支持 await setup，用于这类
  需要写世界的导入型包）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from worlditor_mcp.world import WorldError
from worlditor_mcp.world.play.api import WorlditorPlayAPI

_DATA_FILE = Path(__file__).with_name("world.json")
_DEFAULT_MAP_ID = "default"
_DEFAULT_WORLD_ID = "default"


def _load() -> dict[str, Any]:
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


async def setup(api: WorlditorPlayAPI, context) -> None:
    """导入 world.json 的世界数据（幂等：地图已存在则跳过）。"""
    data = _load()
    map_def = data.get("map") or {}
    map_id = str(map_def.get("id") or _DEFAULT_MAP_ID)
    if api.get_map(map_id) is not None:
        return  # 地图已存在（用户可能改过）——不覆盖
    await api.create_map(
        map_id,
        str(map_def.get("name") or "主世界"),
        description=map_def.get("description"),
        timezone=map_def.get("timezone"),
        spawn_row=int(map_def.get("spawn_row") or 0),
        spawn_col=int(map_def.get("spawn_col") or 0),
    )
    # 归属默认世界（管理端「世界与地图」页按世界列地图；默认世界由内核播种）
    try:
        await api.assign_map(map_id, _DEFAULT_WORLD_ID)
    except WorldError:
        pass  # 默认世界被删过：地图仍可用，仅未归属
    for loc in data.get("locations") or []:
        row, col = int(loc["row"]), int(loc["col"])
        description = loc.get("description")
        if api.get_location(map_id, row, col) is None:
            await api.create_location(
                map_id, row, col, loc["name"], description=description
            )
        else:  # 续跑（上次导入中断）：已存在的地块只更新名称/描述
            kwargs: dict[str, Any] = {"name": loc["name"]}
            if description is not None:
                kwargs["description"] = description
            await api.update_location(map_id, row, col, **kwargs)
        for direction, slot in (loc.get("connections") or {}).items():
            if not slot.get("enabled") or not slot.get("paths"):
                continue
            await api.update_connection(
                map_id, row, col, direction, enabled=True, paths=slot["paths"]
            )
    for entity in data.get("entities") or []:
        await api.place_entity(
            str(entity["kind"]),
            map_id,
            int(entity["row"]),
            int(entity["col"]),
            name=entity.get("name"),
            desc=str(entity.get("desc") or ""),
            attrs=entity.get("attrs") or {},
            state=entity.get("state") or {},
        )


def teardown(api: WorlditorPlayAPI) -> None:
    """卸载钩子：已导入的世界数据不回收（数据归用户，管理端可编辑/删除）。"""
