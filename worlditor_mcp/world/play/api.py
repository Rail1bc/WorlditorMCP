"""WorlditorPlayAPI：玩法包唯一入口（DESIGN_V4.md「WorlditorPlayAPI」）。

每个玩法包一个独立实例：kv 带 play id（namespace 隔离）；所有引擎动作
转发到 V4WorldEngine（引擎锁内执行）。玩法包拿不到引擎内部对象，只能通过
API 原语操作；API 版本随内核版本绑定。
"""

from __future__ import annotations

from typing import Any

from ..v4engine import V4WorldEngine
from ..v4model import ItemDef


class WorlditorPlayAPI:
    """玩法包 API（构造由 PlayLoader 完成；玩法包在 setup(api, context) 中使用）。"""

    def __init__(self, engine: V4WorldEngine, play_id: str) -> None:
        self._engine = engine
        self.play_id = play_id

    # ---------- 注册 ----------

    def register_item_def(
        self, item: ItemDef, *, fields: list[dict] | None = None
    ) -> None:
        """注册物品定义（持久化；同 id 覆盖更新）；fields 为字段 schema（D9）。"""
        if fields:
            item.fields = list(item.fields or []) + list(fields)
        self._engine.register_item_def(item)

    def add_item_fields(self, item_id: str, fields: list[dict]) -> None:
        """向已有物品类型追加字段（D9）。"""
        self._engine.add_item_fields(item_id, fields, play_id=self.play_id)

    def register_entity_kind(
        self,
        kind: str,
        *,
        block_move: bool = False,
        interactions: tuple[str, ...] = (),
        tick: bool = False,
        label: str | None = None,
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """注册实体 kind 元数据（label 为 kind 标签文案，B1）。

        fields 为 kind 声明字段 schema（{name,label,type,default?}，D9）；
        categories 为分类标签（D10，宽松无需预注册）。
        """
        self._engine.register_entity_kind(
            kind,
            block_move=block_move,
            interactions=interactions,
            tick=tick,
            label=label or "",
            play_id=self.play_id,
            fields=fields,
            categories=categories,
        )

    def add_kind_fields(self, kind: str, fields: list[dict]) -> None:
        """向已有 kind 追加字段（D9：玩法包 B 给其他包的 kind 加字段）。"""
        self._engine.add_kind_fields(kind, fields, play_id=self.play_id)

    def add_category_fields(self, category: str, fields: list[dict]) -> None:
        """向分类追加字段（该分类全部 kind 生效，D10）。"""
        self._engine.add_category_fields(category, fields, play_id=self.play_id)

    def list_kinds(self, category: str | None = None) -> list[dict]:
        """kind 列表（含字段 schema 与分类）；category 过滤（D10 精准选取）。"""
        return self._engine.list_kinds(category)

    def register_interaction(
        self, action: str, handler, *, label: str | None = None
    ) -> None:
        """注册全局交互动作（C3）；handler 签名 async (api, req) -> InteractionResult。"""
        self._engine.register_interaction(
            action, handler, label=label or "", play_id=self.play_id
        )

    def register_world_event(
        self, event: str, handler, *, interval: float = 0.0
    ) -> None:
        """订阅世界事件；on_tick 需给 interval（各自间隔秒数，A3）。"""
        self._engine.register_world_event(
            event, handler, interval=interval, play_id=self.play_id
        )

    def register_ui_component(self, name: str, web_entry: str) -> None:
        """注册自定义界面组件（B9；v4.1 WebUI 落地）。"""
        self._engine.register_ui_component(name, web_entry, play_id=self.play_id)

    def register_ui_hook(self, block_kind: str, position: str, provider) -> None:
        """向已有界面块注入子块（B9：before/after/replace；v4.1 渲染落地）。"""
        self._engine.register_ui_hook(
            block_kind, position, provider, play_id=self.play_id
        )

    # ---------- 只读 ----------

    def get_entity(self, entity_id: str):
        return self._engine.get_entity(entity_id)

    def list_entities(self, map_id=None, row=None, col=None) -> list:
        return self._engine.list_entities(map_id, row, col)

    def get_location(self, map_id: str, row: int, col: int):
        return self._engine.get_location(map_id, row, col)

    def get_map(self, map_id: str):
        return self._engine.get_map(map_id)

    def list_actions(self, target_id: str) -> list:
        """目标实体可用动作按钮（C3，UI 菜单生成用）。"""
        return self._engine.list_actions(target_id)

    # ---------- 世界与组织只读（D15；写 = admin 管理端点） ----------

    def list_worlds(self) -> list:
        return self._engine.list_worlds()

    def get_world(self, world_id: str):
        return self._engine.get_world(world_id)

    def entity_world(self, entity_id: str) -> str | None:
        """实体所在世界 id（经地图归属推导）。"""
        return self._engine.entity_world(entity_id)

    def map_world(self, map_id: str) -> str | None:
        return self._engine.map_world(map_id)

    def list_folders(self, world_id: str) -> list:
        return self._engine.list_folders(world_id)

    def list_maps_by_folder(self, world_id: str, folder_id: str | None = None) -> list:
        return self._engine.list_maps_by_folder(world_id, folder_id)

    # ---------- 玩法数据 KV（play_data 表，namespace = 玩法包 id） ----------
    # world_id 传入时双层隔离：(world_id, play_id)——同玩法包在不同世界各自状态（D15）

    def kv_get(self, key: str, default=None, *, world_id: str | None = None) -> Any:
        namespace = f"{world_id}:{self.play_id}" if world_id else self.play_id
        return self._engine.kv_get(namespace, key, default)

    async def kv_set(
        self, key: str, value: Any, *, world_id: str | None = None
    ) -> None:
        namespace = f"{world_id}:{self.play_id}" if world_id else self.play_id
        await self._engine.kv_set(namespace, key, value)

    # ---------- 引擎动作（走原语，锁内执行；均按 entity_id） ----------

    async def give_item(
        self, entity_id: str, item_id: str, count: int = 1, attrs: dict | None = None
    ) -> int:
        return await self._engine.give_item(entity_id, item_id, count, attrs)

    async def take_item(self, entity_id: str, item_id: str, count: int = 1) -> bool:
        return await self._engine.take_item(entity_id, item_id, count)

    def count_item(self, entity_id: str, item_id: str) -> int:
        return self._engine.count_item(entity_id, item_id)

    def list_inventory(self, entity_id: str) -> list[dict]:
        return self._engine.list_inventory(entity_id)

    async def move_entity(
        self, entity_id: str, map_id: str, row: int, col: int
    ) -> None:
        """实体直接移动到坐标（行为驱动；实体放置/移除是地图编辑 admin 操作，B8）。"""
        await self._engine.move_entity(entity_id, map_id, row, col)

    async def set_attrs(self, entity_id: str, patch: dict) -> None:
        await self._engine.set_attrs(entity_id, patch)

    def get_attrs(self, entity_id: str) -> dict:
        return self._engine.get_attrs(entity_id)

    # ---------- 字段原语（D9：set_data/get_data，可被覆盖/禁用 D11） ----------

    async def set_data(self, entity_id: str, name: str, value: Any) -> None:
        """字段写（合并写；走原语分派，可被其他包 override/disable）。"""
        await self._engine.set_data(entity_id, name, value)

    async def get_data(self, entity_id: str, name: str | None = None) -> Any:
        """字段读（单字段或全量；走原语分派）。"""
        return await self._engine.get_data(entity_id, name)

    # ---------- 原语覆盖（D11 / A3） ----------

    def override_primitive(self, name: str, handler) -> None:
        """覆盖行为原语：handler(api, *args, **kwargs)，锁内回调；可调
        api.call_default_primitive 走 super 通道（前置/后置条件）。"""
        self._engine.override_primitive(name, handler, play_id=self.play_id)

    def disable_primitive(self, name: str) -> None:
        """禁用行为原语（调用抛"该能力已被禁用"）。"""
        self._engine.disable_primitive(name, play_id=self.play_id)

    async def call_default_primitive(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """super 通道：显式调用内核默认实现（绕过分派表）。"""
        return await self._engine.call_default_primitive(name, *args, **kwargs)

    def list_primitive_overrides(self) -> list[dict]:
        """原语覆盖/禁用状态（管理页可见）。"""
        return self._engine.list_primitive_overrides()

    # ---------- MCP 工具（G2 / D2） ----------

    def register_tool(
        self,
        name: str,
        handler,
        *,
        description: str = "",
        params: dict[str, str] | None = None,
    ) -> None:
        """注册 MCP 工具：handler(api, ctx, **args)，返回 str 或 {text, ui}。

        同名工具冲突**报错拒绝**（D2）；参数类型限
        string/integer/number/boolean（FastMCP schema 生成）。
        """
        self._engine.register_tool(
            name,
            handler,
            description=description,
            params=params,
            play_id=self.play_id,
        )

    def caller(self) -> str | None:
        """当前调用者实体 id（MCP 工具 handler 内有效；无身份返回 None）。"""
        from ..mcp import _caller_entity

        return _caller_entity.get()

    def register_view(
        self,
        key: str,
        *,
        title: str,
        icon: str = "",
        provider: dict | None = None,
    ) -> None:
        """注册 WebUI 视图（G3：provider = {type:"component", url:"web/xxx.js"}）。"""
        self._engine.register_view(
            key, title=title, icon=icon, provider=provider, play_id=self.play_id
        )

    def list_views(self) -> list[dict]:
        return self._engine.list_views()

    # ---------- 自定义事件（G8 / D1 说话通道） ----------

    async def emit(self, event: str, data: Any = None, *, log: bool = False) -> None:
        """发自定义事件（任意事件名；SSE 推送；log=True 写 world_log）。"""
        await self._engine.emit(event, data, log=log)

    # ---------- 实体生命周期（D14：玩法包可 spawn/despawn） ----------

    async def place_entity(
        self,
        kind: str,
        map_id: str,
        row: int,
        col: int,
        *,
        name: str | None = None,
        desc: str = "",
        attrs: dict | None = None,
        state: dict | None = None,
    ):
        """放置实体（spawn；身份化实体不可被 remove，D14）。"""
        return await self._engine.place_entity(
            kind, map_id, row, col, name=name, desc=desc, attrs=attrs, state=state
        )

    async def remove_entity(self, entity_id: str) -> None:
        """移除实体（despawn；身份化实体被拒绝，D14）。"""
        await self._engine.remove_entity(entity_id)

    # ---------- 地图编辑（D14：地块/连接/地图/模板） ----------

    async def update_location(self, map_id: str, row: int, col: int, **kwargs) -> None:
        await self._engine.update_location(map_id, row, col, **kwargs)

    async def update_connection(
        self, map_id: str, row: int, col: int, direction: str, **kwargs
    ) -> None:
        await self._engine.update_connection(map_id, row, col, direction, **kwargs)

    async def create_map(
        self, map_id: str, name: str, *, description: str | None = None, **kwargs
    ):
        await self._engine.create_map(map_id, name, description=description, **kwargs)

    async def save_template(self, template) -> None:
        await self._engine.save_template(template)

    async def delete_template(self, template_id: str) -> None:
        await self._engine.delete_template(template_id)

    async def set_state(self, entity_id: str, patch: dict) -> None:
        await self._engine.set_state(entity_id, patch)

    def get_state(self, entity_id: str) -> dict:
        return self._engine.get_state(entity_id)

    async def say(self, entity_id: str, text: str, *, scope: str = "cell") -> None:
        await self._engine.say(entity_id, text, scope=scope)

    async def interact(
        self,
        entity_id: str,
        target_id: str,
        action: str,
        args: dict | None = None,
        item_id: str | None = None,
    ):
        return await self._engine.interact(entity_id, target_id, action, args, item_id)

    async def flush_item_defs(self) -> None:
        """（PlayLoader 内部使用）把注册的物品定义落库。"""
        await self._engine.flush_item_defs()
