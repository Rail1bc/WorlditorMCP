"""worlditor-mcp：一行命令部署的世界服务（MCP 为第一公民协议）。

世界以 (map_id, 行, 列) 为身份的地块组成；任意 agent 框架经 MCP
（streamable HTTP / stdio）接入，人类玩家经内置 WebUI 登录游玩，
拥有者经管理页治理。内核纯数据，行为由玩法包承载（见 DESIGN.md）。
"""

__version__ = "0.1.0"
