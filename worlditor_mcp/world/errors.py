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


class IncompatibleDataError(WorldError):
    """数据目录里的**既有内容**与当前版本不兼容（拒绝启动，不做迁移）。

    与 ``WorldError`` 的区别只在**谁该被怪罪**：``WorldError`` 是"这次动作不合法"
    （改输入即可），本类是"这份数据这个版本读不了"——按 D13 不迁移，唯一出路是
    删除数据目录重建，所以消息里带**表 / 行键 / 字段 / 该删哪个文件**。

    由 ``WorldStore._load_all`` 在启动期抛出；``cli`` 捕获它并打印指引而**不打栈**：
    一屏 traceback 里的信息量只有最后一句话，而运维真正需要的是"删哪个文件"。
    """
