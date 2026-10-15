"""WorlditorPlayAPI：玩法包唯一入口（DESIGN.md「WorlditorPlayAPI」）。

每个玩法包一个独立实例：kv 带 play id（namespace 隔离）；所有引擎动作
转发到 WorldEngine（引擎锁内执行）。玩法包拿不到引擎内部对象，只能通过
API 原语操作；API 版本随内核版本绑定。
"""

from __future__ import annotations

from typing import Any

from ..engine import WorldEngine
from ..errors import WorldError
from ..model import COMPONENT_LOCAL, is_core_component


class WorlditorPlayAPI:
    """玩法包 API（构造由 PlayLoader 完成；玩法包在 setup(api, context) 中使用）。"""

    def __init__(self, engine: WorldEngine, play_id: str) -> None:
        self._engine = engine
        self.play_id = play_id

    # ---------- 物品：已移除（v2 / D37） ----------
    #
    # 原 `register_item_def` / `save_item_def` / `add_item_fields` / `get_item_def` /
    # `list_item_defs` / `delete_item_def` / `flush_item_defs` 全部删除——**物品不在内核**：
    #   - 物品**类型** → 用组件声明表达（`register_entity_tag`：名字 + 字段 schema + 归属）
    #   - 物品**实例** → 实体 + 组件
    #   - `use_action` → interaction 名（本 API 的 `register_interaction`）
    #   - 管理员手工维护的定义 → **实体模板**（`register_entity_template` / `save_template`）
    #   - 原 `item_id` 交互槽位 → `interact(..., args={"item": ...})`
    #   - 原 `on_item_used` 事件 → 本包 `emit("item_used", {...})`（任意事件名皆可）
    # 见 DESIGN §12.8 / D37。

    # ---------- 注册 ----------

    def declare_component(
        self,
        name: str,
        *,
        interactions: tuple[str, ...] = (),
        label: str | None = None,
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """声明本玩法包拥有的组件；来源由 API 实例自动填入。"""
        self._engine.declare_component(
            name,
            interactions=interactions,
            label=label or "",
            play_id=self.play_id,
            fields=fields,
            categories=categories,
        )

    def register_entity_kind(
        self,
        kind: str,
        *,
        interactions: tuple[str, ...] = (),
        label: str | None = None,
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> None:
        """声明一个组件（D41；旧名，等价的 `declare_component` 更好读）。

        Args:
            label: 文案（B1），也是放置实体时未给名字的默认名。
            fields: 字段 schema（{name,label,type,default?}，D9）。
            categories: 选取分组（D10，宽松无需预注册；**不再承载字段**，D41）。
            tags: **已作废**（D41）："类型 = 一组组件的预设"归实体模板
                （`register_entity_template`），传非空值会报错。
        """
        self._engine.register_entity_kind(
            kind,
            interactions=interactions,
            label=label or "",
            play_id=self.play_id,
            fields=fields,
            categories=categories,
            tags=tags,
        )

    def register_entity_type(
        self,
        kind: str,
        *,
        tags: tuple[str, ...] = (),
        label: str | None = None,
        interactions: tuple[str, ...] = (),
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """``register_entity_kind`` 的同义名（D41；``tags`` 同上已作废）。"""
        self.register_entity_kind(
            kind,
            interactions=interactions,
            label=label,
            fields=fields,
            categories=categories,
            tags=tags,
        )

    def register_entity_tag(
        self,
        tag: str,
        *,
        label: str | None = None,
        interactions: tuple[str, ...] = (),
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """声明一个组件（D41；旧名，等价的 `declare_component` 更好读）。

        实体带上这个组件就获得这里声明的一切（interactions 并集，D19）——
        "给玩家再组合一个刷怪笼组件"就是这么来的。
        """
        self._engine.register_entity_tag(
            tag,
            label=label or "",
            interactions=interactions,
            play_id=self.play_id,
            fields=fields,
            categories=categories,
        )

    def add_tag_fields(self, tag: str, fields: list[dict]) -> None:
        """给**一个组件**追加字段（D41：跨包扩展的正当路径，也是唯一的）。

        同名字段在同一组件内重复声明 → 报错（D41：同一地址只能有一个声明）。
        """
        self._engine.add_tag_fields(tag, fields, play_id=self.play_id)

    def add_kind_fields(self, kind: str, fields: list[dict]) -> None:
        """``add_tag_fields`` 的旧名（D41：旧调用点零改动）。"""
        self._engine.add_kind_fields(kind, fields, play_id=self.play_id)

    def list_kinds(self, category: str | None = None) -> list[dict]:
        """**组件清单**（D41：只有一套声明，不再是"类型 + 标签"两张表）。"""
        return self._engine.list_kinds(category)

    def capabilities(self, entity) -> dict:
        """某实体的能力（D41）：生效组件 / 动作并集 / **按组件分组**的字段。"""
        return self._engine.capabilities(entity)

    def register_interaction(
        self, action: str, handler, *, label: str | None = None
    ) -> None:
        """注册全局交互动作（C3）；handler 签名 async (api, req) -> InteractionResult。"""
        self._engine.register_interaction(
            action, handler, label=label or "", play_id=self.play_id
        )

    def register_world_event(
        self,
        event: str,
        handler,
        *,
        interval: float = 0.0,
        phase: str = "simulate",
        order: int = 0,
    ) -> None:
        """订阅世界事件；on_tick 需给 interval（各自间隔秒数，A3）。

        Args:
            interval: on_tick 专用（正秒数）。
            phase: 执行阶段（D27）——``input`` → ``simulate`` → ``present``，
                缺省 ``simulate``；跨包顺序靠它显式声明（不再依赖包加载序）。
            order: 同阶段内序号（越小越先，可负）；同 phase/order 按注册序兜底。
        """
        self._engine.register_world_event(
            event,
            handler,
            interval=interval,
            phase=phase,
            order=order,
            play_id=self.play_id,
        )

    def register_ui_component(self, name: str, web_entry: str) -> None:
        """注册自定义界面组件（B9；WebUI 落地）。"""
        self._engine.register_ui_component(name, web_entry, play_id=self.play_id)

    def register_ui_hook(self, block_kind: str, position: str, provider) -> None:
        """向已有界面块注入子块（B9：before/after/replace；渲染落地）。"""
        self._engine.register_ui_hook(
            block_kind, position, provider, play_id=self.play_id
        )

    async def apply_ui_hooks(self, block) -> Any:
        """应用全部已注册 ui_hook（服务端展开，锁内）。

        玩法包生成自己的界面数据后调用——其他包注入的部件 UI（如背包面板
        注入角色卡）在此展开；返回注入后的 UiBlock（或 None）。

        D15/v0.3.0：按**当前调用者所在世界**过滤——注入方玩法包在该世界未
        启用时，其部件不出现（无身份上下文时不过滤）。
        """
        return await self._engine.apply_ui_hooks(block, entity_id=self.caller())

    # ---------- 只读 ----------

    def get_entity(self, entity_id: str):
        return self._engine.get_entity(entity_id)

    def list_entities(
        self, map_id=None, row=None, col=None, viewer_id: str | None = None
    ) -> list:
        return self._engine.list_entities(map_id, row, col, viewer_id=viewer_id)

    def query_entities(
        self,
        *,
        tags: list[str] | tuple[str, ...] | None = None,
        exclude_tags: list[str] | tuple[str, ...] | None = None,
        map_id: str | None = None,
        world_id: str | None = None,
        row: int | None = None,
        col: int | None = None,
        viewer_id: str | None = None,
        changed_since_tick: int | None = None,
        changed_since_revision: int | None = None,
        where=None,
        limit: int | None = None,
    ) -> list:
        """实体查询（D26）：「所有带某组件的实体」不再需要全量扫 + 自己筛。

        ```python
        for e in api.query_entities(tags=["poison"], world_id=world_id):
            hp = await api.get_data(e.id, "hp", component="worlditor_play_bestiary:stat") or 0
            await api.set_data(
                e.id, "hp", hp - 1, component="worlditor_play_bestiary:stat"
            )
        ```

        语义要点（详见 ``WorldEngine.query_entities``）：
        - ``tags`` / ``exclude_tags`` 筛的是**组件的存在**（D41），裸名会按 D41
          解析成完整组件键（唯一声明者 → 加前缀；无人声明 → ``local:``；多个 → 报错）。
        - 组件匹配按 D21 生效：声明该组件的包在实体所在世界未激活 → 不匹配；
          实体自带的纯数据组件（无声明者）照常匹配。
        - ``viewer_id`` 走感知过滤（G12 隐身），与 list_entities 同源。
        - 增量遍历（D28）：``changed_since_revision``（精确游标，配
          ``api.world_revision()``）或 ``changed_since_tick``（窗口粒度，宁可多报）。
        - 严格校验：拼错的地图/世界、非法组件名会报错，而不是"查到空"。
        """
        return self._engine.query_entities(
            tags=tags,
            exclude_tags=exclude_tags,
            map_id=map_id,
            world_id=world_id,
            row=row,
            col=col,
            viewer_id=viewer_id,
            changed_since_tick=changed_since_tick,
            changed_since_revision=changed_since_revision,
            where=where,
            limit=limit,
        )

    def current_tick(self) -> int:
        """当前 tick 窗口号（D28：心跳轮次；配合 changed_since_tick 做增量遍历）。"""
        return self._engine.tick

    def world_revision(self) -> int:
        """当前全局变更号（D28：增量游标——记住它，下轮用 changed_since_revision）。"""
        return self._engine.revision

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

    # D8：持有（背包）全下沉玩法包——API 无 give/take/count/list_inventory，
    # 背包模型由玩法包自管（play_data / 自建模型），内核仅持有物品定义。

    async def move_entity(
        self, entity_id: str, map_id: str, row: int, col: int
    ) -> None:
        """实体直接移动到坐标（行为驱动；实体放置/移除是地图编辑 admin 操作，B8）。"""
        await self._engine.move_entity(entity_id, map_id, row, col)

    async def move(self, entity_id: str, direction: str, *, path: int | None = None):
        """路径移动（D11：分派入口，可被过滤器改写方向/覆盖；返回 SceneView）。

        direction 为绝对方向（up/right/down/left）或玩法包约定的相对方向
        （如 movement 包的 forward/back/left/right，由过滤器换算）。
        """
        return await self._engine.move(entity_id, direction, path=path)

    # ---------- 组件（D32 / D33：实体唯一的数据单位） ----------
    #
    # **玩法包不得写 ``core:`` 命名空间**（内核保留，D33）——在这里就拒绝，
    # 不依赖包自觉；读（get_component / list_components）不受限。

    def _guard_component(self, component: str) -> str:
        """组件写入的命名空间守卫（D33 / D43）。

        - `core:` —— 内核保留，玩法包一律拒写（D33）；
        - **`<别人的 play_id>:` —— 拒写**（D43）：包名写在键里就该是真规则，
          不能只是"命名约定"。要影响别人的组件，走 `call_service`（让对方自己写）、
          事件，或在**声明期**用 `add_tag_fields` 显式登记扩展（"扩展可以，但要留痕"）；
        - `<自己的 play_id>:` 与 `local:` —— 可写（`local:` **暂不收紧**，D43：
          夹具与文档例子都在写它，收紧留到以后单独一步）。
        """
        if is_core_component(component):
            raise WorldError(
                f"core: 是内核保留的组件命名空间，玩法包不得写入（{component}）"
            )
        source = str(component).split(":", 1)[0]
        if source not in (COMPONENT_LOCAL, self.play_id):
            raise WorldError(
                f"{source}: 是别的玩法包的命名空间，本包（{self.play_id}）不得写入"
                f"（{component}）——要影响对方的数据请走 call_service 或事件"
            )
        return component

    def list_components(self, entity_id: str) -> list[str]:
        """该实体的组件名列表（只读）。"""
        return self._engine.list_components(entity_id)

    def get_component(self, entity_id: str, component: str) -> dict | None:
        """整块读组件数据（不存在返回 ``None``；只读）。"""
        return self._engine.get_component(entity_id, component)

    async def add_component(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        """整块新建组件（**已存在 → 报错**；要整体替换用 ``set_component``）。"""
        await self._engine.add_component(
            entity_id, self._guard_component(component), data
        )

    async def set_component(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        """整块写组件（建或**整体替换**）。"""
        await self._engine.set_component(
            entity_id, self._guard_component(component), data
        )

    async def remove_component(self, entity_id: str, component: str) -> bool:
        """整块删组件（幂等：不存在 → False）。"""
        return await self._engine.remove_component(
            entity_id, self._guard_component(component)
        )

    async def set_perception(self, entity_id: str, patch: dict) -> None:
        """设置感知（``invisible`` / ``see_invisible``，布尔）——**写 ``core:perception`` 的唯一入口**。

        玩法包不能直写 ``core:``（D33），但"让一个实体隐身"本来就是玩法包的正当能力，
        所以内核给这个**窄口受控入口**（与 D20"NPC 升格必须经身份服务"同一做法：
        规则不放宽，能力不丢失）。语义见 G1 / G12：普通 viewer 看不到 ``invisible``
        实体；``see_invisible`` 为真的 viewer 能看到。
        """
        await self._engine.set_perception(entity_id, patch)

    async def clear_position(self, entity_id: str) -> None:
        """让实体**离开世界**（下线 / 收进容器 / 传送中间态）——**写 ``core:position`` 的受控入口**。

        与 `remove_entity` 的区别：**实体还在**（组件、标签、账户绑定全保留），只是不在
        任何地块上。再放回来用 `move_entity`（它接受不在场的实体）。

        同样的理由（D33 让玩法包写不了 ``core:``）——而"下线"正是玩法包最需要的那种状态，
        所以内核给窄口受控入口而不是让能力消失。幂等。
        """
        await self._engine.clear_position(entity_id)

    # ---------- 字段原语（D9 的开放模型保留：字段 = **组件内**的一个键） ----------

    async def set_data(
        self, entity_id: str, name: str, value: Any, *, component: str
    ) -> None:
        """字段写（走原语分派，可被其他包 override/disable；``core:`` 除外）。

        ``component`` 必填——v2 起没有扁平命名空间；写在未建组件上会隐式建出。
        """
        await self._engine.set_data(
            entity_id, name, value, component=self._guard_component(component)
        )

    async def get_data(
        self, entity_id: str, name: str | None = None, *, component: str
    ) -> Any:
        """字段读（``name=None`` 返回整块组件数据；走原语分派）。"""
        return await self._engine.get_data(entity_id, name, component=component)

    async def remove_data(self, entity_id: str, name: str, *, component: str) -> bool:
        """删除组件内的一个字段（走原语分派，可被 override/过滤器拦；D23 的另一半）。

        返回是否真的删掉了（字段不存在 → False，幂等）。删掉整个字段比
        ``set_data(name, None)`` 干净：``None`` 仍是"有这个字段、值为空"。
        """
        return await self._engine.remove_data(
            entity_id, name, component=self._guard_component(component)
        )

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

    def register_primitive_filter(self, name: str, filter, *, label: str = "") -> None:
        """登记原语过滤器（G14）：filter(api, **params) -> dict | ShortCircuit。

        三态：raise WorldError = 否决；返回参数字典 = 改写继续链；
        返回 ShortCircuit(value) = 短路（跳过后续过滤器与默认实现）。
        **同一包同一原语可注册多个**（各带 label，链序 = 注册序）；
        与 override/disable 互斥（原语至多一个覆盖者/禁用者）。
        """
        self._engine.register_primitive_filter(
            name, filter, label=label, play_id=self.play_id
        )

    def list_primitive_filters(self) -> list[dict]:
        """原语过滤器链状态（管理页可见）。"""
        return self._engine.list_primitive_filters()

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
        string/integer/number/boolean/array（G11；FastMCP schema 生成）。
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

    # ---------- 玩法包管理页（v0.1.12：管理端注册协议） ----------

    def register_admin_page(
        self,
        key: str,
        *,
        title: str,
        icon: str = "",
        component_url: str,
        actions: dict,
    ) -> None:
        """注册玩法包管理页（可注册多个；管理端导航 + actions 代理）。

        - ``component_url``：管理页组件入口（协议同视图组件：
          ``new Function("Vue","UiBlock", code)``；必须为本包 web/ 资源）
        - ``actions``：玩法包自管的数据动作 dict（动作名 -> handler），
          handler 签名 ``async (api, **params) -> Any``（api 为本包实例）；
          管理端经 ``POST /admin/play-pages/{play_id}/{page_key}/{action}``
          锁内代理调用——数据语义（背包 slots、物品定义字段等）由本包
          定义与校验，内核不裸露 play_data 裸编辑
        """
        self._engine.register_admin_page(
            key,
            title=title,
            icon=icon,
            component_url=component_url,
            actions=actions,
            play_id=self.play_id,
        )

    def list_admin_pages(self) -> list[dict]:
        return self._engine.list_admin_pages()

    # ---------- 跨包服务（M3：玩法包间同步调用） ----------

    def register_service(self, name: str, handler) -> None:
        """注册玩法包服务（供其他包同步调用）：handler(api, **params) -> Any。

        服务 = 本包能力边界内的操作（如背包读写）；调用方经
        ``call_service(play_id, name, **params)`` 使用。
        """
        self._engine.register_service(name, handler, play_id=self.play_id)

    def list_services(self) -> list[dict]:
        return self._engine.list_services()

    async def call_service(self, play_id: str, name: str, **params: Any) -> Any:
        """调用其他玩法包的服务（锁内、异常隔离）；服务不存在报错。"""
        return await self._engine.call_service(self.play_id, play_id, name, **params)

    # ---------- 自定义事件（G8 / D1 说话通道） ----------

    async def emit(self, event: str, data: Any = None, *, log: bool = False) -> None:
        """发自定义事件（任意事件名；SSE 推送；log=True 写 world_log）。"""
        await self._engine.emit(event, data, log=log)

    async def list_world_log(self, limit: int = 100) -> list[dict]:
        """世界日志（最新在前；社交/日志视图数据源）。"""
        return await self._engine.list_world_log(limit)

    # ---------- 实体生命周期（D14：玩法包可 spawn/despawn） ----------

    async def place_entity(
        self,
        kind: str | None = None,
        map_id: str | None = None,
        row: int | None = None,
        col: int | None = None,
        *,
        name: str | None = None,
        desc: str = "",
        components: dict | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
    ):
        """放置实体（spawn；绑定了账户的实体不可被 remove，D14 / D42）。

        D41：**能力就是组件**——``kind`` / ``tags`` 是输入便利（裸名解析），
        ``kind="slime"`` 等于带上 ``bestiary:slime`` 组件；刷怪笼包要"生成一个带刷怪
        能力的实体"就是 ``place_entity("slime", ..., tags=["spawner"])``。两者都可省
        （没有能力组件的实体也合法）；要带数据的组件走 ``components``。
        ``components`` 为初始组件（v2；``core:`` 一律拒绝，见 ``_guard_component``）。
        **位置三参数可选（D36）**：全不给 = 造一个**不在世界上**的实体
        （物品放进容器、待投放的 NPC）——它们不出现在 ``list_entities`` /
        ``query_entities`` 的默认结果里，要拿得传 ``include_absent=True``。
        """
        if isinstance(components, dict):
            for key in components:
                self._guard_component(str(key))
        return await self._engine.place_entity(
            kind,
            map_id,
            row,
            col,
            name=name,
            desc=desc,
            components=components,
            tags=tags,
        )

    async def remove_entity(self, entity_id: str) -> None:
        """移除实体（despawn；**绑定了账户的实体被拒绝**，D14 / D42）。"""
        await self._engine.remove_entity(entity_id)

    # ---------- 地图编辑（D14：地块/连接/地图/模板） ----------

    async def create_location(
        self,
        map_id: str,
        row: int,
        col: int,
        name: str,
        *,
        description: object = None,
    ):
        """新建地块（世界包/内容导入用；坐标重复或空名称报错）。"""
        return await self._engine.create_location(
            map_id, row, col, name, description=description
        )

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

    async def assign_map(
        self,
        map_id: str,
        world_id: str,
        *,
        folder_id: str | None = None,
        sort: int | None = None,
    ) -> None:
        """把地图归属到世界（世界包导入内容时用；覆盖旧归属）。

        ``sort`` 为该组织节点内的序号（文件夹与地图共用序号空间，
        见 DESIGN §4.3.2）；缺省 = 同节点保留原位 / 换节点排到末尾。
        """
        await self._engine.assign_map(map_id, world_id, folder_id=folder_id, sort=sort)

    async def delete_map(self, map_id: str) -> None:
        """删除地图（G2：级联清理；图上玩家/agent 在场被拒）。"""
        await self._engine.delete_map(map_id)

    async def save_template(self, template) -> None:
        await self._engine.save_template(template)

    async def delete_template(self, template_id: str) -> None:
        await self._engine.delete_template(template_id)

    def register_entity_template(
        self, template_id: str, name: str, data: dict, *, label: str = ""
    ) -> None:
        """注册玩法包自带的实体模板（D22：内存注册表，随包卸载消失）。

        data = ``{kind, tags[], name, desc, components}``；管理端本地模板落库，
        两边合并成一个选择列表（``list_templates("entity")``）。
        """
        self._engine.register_entity_template(
            template_id, name, data, play_id=self.play_id, label=label
        )

    def list_templates(self, scope: str | None = None) -> list[dict]:
        """模板清单（D22：玩法包注册 + 管理端本地合并）。"""
        return self._engine.list_templates(scope)

    async def apply_location_template(
        self, template_id: str, map_id: str, row: int, col: int
    ):
        """套用地块模板到 (row, col)（同图目标平移、跨图目标原样；占位则拒绝）。"""
        return await self._engine.apply_location_template(template_id, map_id, row, col)

    async def interact(
        self,
        entity_id: str,
        target_id: str,
        action: str,
        args: dict | None = None,
    ):
        """交互（走原语分派，可被覆盖/禁用）。

        v2 / D37：原 ``item_id`` 参数已删除——把物品标识放进 ``args`` 即可
        （如 ``args={"item": "apple"}``），内核不解释其内容。
        """
        return await self._engine.interact(entity_id, target_id, action, args)
