"""世界层的领域错误（内核 / 模型 / 玩法包共用）。

单独成模块是为了让 ``model.py``（数据解析）能抛出**与引擎同一种**错误：
``WorldError`` 的消息面向用户，管理端与 MCP 工具端点原样透出（400 / 提示文案），
而 ``ValueError`` 保留给"不该发生"的编程错误——两者混用会让非法输入变成 500。

``WorldError`` 仍然可以从 ``worlditor_mcp.world.engine`` 导入
（引擎 re-export，保持既有导入路径不变）。
"""

from __future__ import annotations


class WorldError(Exception):
    """世界动作的业务错误（非法方向、实体不存在、数据格式非法等），消息可直接展示。"""
