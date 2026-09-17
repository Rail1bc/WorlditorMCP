"""世界引擎：世界底子的核心动作（协议无关，见 DESIGN.md）。

设计要点：
- **实体统一模型**：玩家/agent/布景实体都是 ``Entity``（entities 表）；
  玩家/agent 为身份化实体（可认证绑定、位置持久化）。
- **物品**：定义（ItemDef）为内核注册表；持有下沉玩法包（D8，无 inventories）。
- **交互**：handler 命令式调用内核原语（D12，无 effects 清单）。
- **事件总线**：单一事件源（8 事件），玩法包订阅 + world_log 历史；
  SSE 是事件总线的序列化出口。
- **注册表**：kind / interaction / event / ui 组件与钩子，玩法包扩展入口。
- **on_tick 调度**（A3）：单循环按 1s 粒度检查，各 handler 各自间隔，
  串行执行 + 异常隔离。

并发模型：实例级**可重入**异步锁（AsyncRLock）——原语分派（override /
过滤器链 / 默认实现）与玩法包 handler（交互 / 事件 / tick / MCP 工具）均在
锁内执行；handler 内再调 API 原语必须重入（普通 asyncio.Lock 会自锁死锁），
多段「读-判-写」原子（DESIGN §2.4 并发模型）。
时钟与 PRNG 注入（``clock`` / ``rand``），保证时间感知描述与加权抽取可测。

分区地图（按节定位的辅助锚点；行号随演化漂移属正常）：
- 注册表区：~395–1030（物品/kind/字段/工具/视图/服务/原语分派/交互/事件/UI/清理）
- 事件总线区：~1031–1227（emit / SSE 推送 / tick 循环）
- 只读查询：~1229–1326（实体/地图/世界/组织）
- 世界组织 CRUD：~1330–1432（worlds / folders / 归属）
- 实体原语：~1441–1532（place / remove / 身份化受控删除）
- 移动区：~1534–1616（move / move_entity / 默认实现）
- 数据字段区：~1648–1673（attrs / state / set/get_data）
- 场景构建：~1675–1756（路径解析 / 阻挡 / SceneView）
- 交互区：~1758–1845（interact / 可用动作）
- 地图编辑区：~1849–2207（地块 / 连接 / 地图 / 模板 / 删除级联）
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .model import (
    ATTR_INVISIBLE,
    ATTR_SEE_INVISIBLE,
    DIRECTIONS,
    IDENTITY_KINDS,
    STATE_BLOCK_MOVE,
    WORLD_EVENTS,
    ConnectionPath,
    Entity,
    InteractionRequest,
    InteractionResult,
    ItemDef,
    MenuButton,
    ScenePath,
    SceneView,
    ShortCircuit,
    TagSpec,
    Target,
    World,
    WorldFolder,
    WorldMap,
    WorldTemplate,
    location_to_dict,
    parse_location,
    parse_map,
    parse_path,
    parse_tags,
    parse_text_schedule,
)
from .store import DEFAULT_WORLD_ID, WorldStore

logger = logging.getLogger("worlditor")

TICK_GRANULARITY_SECONDS = 1.0
# IDENTITY_KINDS 权威定义在 model.py（v0.2.0 起只有 player）

# 哨兵：update 类动作用于区分「参数未提供（不变）」与「显式传 None（清空/重置）」
_UNSET = object()

# 交互 handler 签名：async def handler(api, req: InteractionRequest) -> InteractionResult
InteractionHandler = Callable[[Any, InteractionRequest], Any]
# 事件 handler 签名随事件（见 model.WORLD_EVENTS 注释）
WorldEventHandler = Callable[..., Any]
# UI 钩子 provider：async def provider(api, block: UiBlock) -> list[UiBlock]
UiHookProvider = Callable[..., Any]


class WorldError(Exception):
    """世界动作的业务错误（非法方向、实体不存在等），消息可直接展示给用户。"""


class AsyncRLock:
    """可重入异步锁：同一任务可多次 acquire（计数释放）。

    引擎在锁内调用玩法包 handler，handler 内再调 API 原语（同样走锁）——
    普通 asyncio.Lock 在这种场景会自锁死锁，需要重入。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._count = 0

    async def acquire(self) -> None:
        task = asyncio.current_task()
        if self._owner is task:
            self._count += 1
            return
        await self._lock.acquire()
        self._owner = task
        self._count = 1

    def release(self) -> None:
        if self._owner is not asyncio.current_task():
            raise RuntimeError("锁释放者不是持有者")
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> AsyncRLock:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.release()


@dataclass
class _EventBinding:
    """一次事件订阅（play_id 用于取 API 与 namespace）。"""

    play_id: str
    handler: WorldEventHandler
    interval: float = 0.0  # on_tick 专用：各自间隔（A3）
    last_run: float = 0.0


@dataclass
class _InteractionBinding:
    play_id: str
    handler: InteractionHandler
    label: str = ""


@dataclass
class _UiHookBinding:
    """一次界面钩子注册（B9：before/after/replace）。"""

    play_id: str
    provider: UiHookProvider


@dataclass
class _PrimitiveOverride:
    """原语分派登记（D11/A3）：handler=None 表示禁用该能力。"""

    play_id: str
    handler: Callable | None = None


@dataclass
class _PrimitiveFilter:
    """原语过滤器登记（G14）：filter(api, **params) -> dict | ShortCircuit。"""

    play_id: str
    filter: Callable
    label: str = ""


@dataclass
class _FieldAppend:
    """一次字段追加登记（D9/D10：记录归属供卸载清理）。"""

    play_id: str
    field: dict


@dataclass
class _ToolBinding:
    """MCP 工具登记（D2：同名冲突报错；handler(api, ctx, **args)）。"""

    play_id: str
    handler: Callable
    description: str = ""
    params: dict[str, str] = field(
        default_factory=dict
    )  # 参数名 -> string/integer/number/boolean


@dataclass
class _ViewBinding:
    """WebUI 视图登记（G3/D7：provider = 组件入口 URL）。"""

    play_id: str
    title: str
    icon: str = ""
    provider: dict = field(default_factory=dict)


@dataclass
class _ServiceBinding:
    """玩法包服务登记（M3：跨包同步调用通道；handler(api, **params) -> Any）。"""

    play_id: str
    name: str
    handler: Callable


@dataclass
class _AdminPageBinding:
    """玩法包管理页登记（管理端注册协议，v0.1.12）。

    管理页 = 管理端导航入口（title/icon/组件）+ 玩法包自管的数据动作
    （component_url 必须为本包资源；action 由管理端点锁内代理调用）。
    """

    play_id: str
    key: str
    title: str
    icon: str = ""
    component_url: str = ""
    actions: dict[str, Callable] = field(default_factory=dict)


# 可被玩法包覆盖/禁用的行为原语（D11；place/remove 不可覆盖，D14）
OVERRIDABLE_PRIMITIVES = frozenset(
    {"move", "move_entity", "set_data", "get_data", "interact"}
)

# 原语名 → 默认实现方法名（分派表兜底）
_PRIMITIVE_DEFAULT_NAMES = {
    "move": "_move_default",
    "move_entity": "_move_entity_default",
    "set_data": "_set_data_default",
    "get_data": "_get_data_default",
    "interact": "_interact_default",
}

# 原语命名参数（过滤器收到 **params；位置参数按此规范化）
_PRIMITIVE_PARAM_NAMES = {
    "move": ["entity_id", "direction", "path"],
    "move_entity": ["entity_id", "map_id", "row", "col"],
    "set_data": ["entity_id", "name", "value"],
    "get_data": ["entity_id", "name"],
    "interact": ["entity_id", "target_id", "action", "args", "item_id"],
}


def _primitive_params(name: str, args: tuple, kwargs: dict) -> dict:
    """原语位置/关键字参数 → 命名参数 dict（过滤器与默认实现共用）。"""
    names = _PRIMITIVE_PARAM_NAMES[name]
    params = dict(kwargs)
    for i, value in enumerate(args):
        if i < len(names) and names[i] not in params:
            params[names[i]] = value
    return params


_FIELD_TYPES = ("str", "int", "float", "bool", "json")


def _check_primitive_name(name: object) -> str:
    if not isinstance(name, str) or name not in OVERRIDABLE_PRIMITIVES:
        raise WorldError(f"原语必须是 {'/'.join(sorted(OVERRIDABLE_PRIMITIVES))} 之一")
    return name


def _validate_fields(fields: list) -> list[dict]:
    """字段 schema 校验：{name,label,type,default?}；type ∈ str/int/float/bool/json。"""
    if not isinstance(fields, list):
        raise WorldError("fields 必须是列表")
    out: list[dict] = []
    for f in fields:
        if (
            not isinstance(f, dict)
            or not isinstance(f.get("name"), str)
            or not f["name"]
        ):
            raise WorldError("字段 schema 需要 name")
        ftype = f.get("type", "str")
        if ftype not in _FIELD_TYPES:
            raise WorldError(f"字段类型必须是 {'/'.join(_FIELD_TYPES)} 之一")
        out.append(
            {
                "name": f["name"],
                "label": str(f.get("label") or f["name"]),
                "type": ftype,
                **({"default": f["default"]} if "default" in f else {}),
            }
        )
    return out


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_pos(row: object, col: object) -> None:
    if not _is_int(row) or not _is_int(col):
        raise WorldError("地块坐标必须是整数")


def _clean_required(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldError(f"{what}不能为空")
    return value.strip()


def _check_direction(direction: object) -> str:
    if direction not in DIRECTIONS:
        raise WorldError(f"方向必须是 {'/'.join(DIRECTIONS)} 之一")
    return str(direction)


def _clean_sort(sort: object) -> int | None:
    """组织树序号归一化：None/未给 = 交给下层决定（保留原位或排到末尾）。"""
    if sort is None or sort is _UNSET:
        return None
    if not _is_int(sort):
        if isinstance(sort, str) and sort.strip().lstrip("-").isdigit():
            return int(sort.strip())
        raise WorldError("排序序号必须是整数")
    return int(sort)


# ---------- 模板负载（D22：地块与实体共用一个"模板"概念） ----------

TEMPLATE_SCOPES = ("location", "entity")


def _template_to_absolute(data: dict, row: int, col: int) -> dict:
    """模板负载 → parse_location 可吃的绝对坐标形式（锚点 = (row, col)）。

    目标两种写法：``{dr, dc}`` 相对偏移（同图，放置时平移）与
    ``{map_id, row, col}`` 绝对坐标（跨图，原样复制）。
    """
    out: dict[str, Any] = {
        "map_id": "",
        "row": row,
        "col": col,
        "name": data.get("name"),
        "description": data.get("description"),
        "connections": {},
    }
    raw = data.get("connections")
    if isinstance(raw, dict):
        for direction, slot in raw.items():
            if direction not in DIRECTIONS or not isinstance(slot, dict):
                continue
            paths = []
            for path in slot.get("paths") or []:
                if not isinstance(path, dict):
                    continue
                targets = []
                for t in path.get("targets") or []:
                    if not isinstance(t, dict):
                        continue
                    if _is_int(t.get("dr")) and _is_int(t.get("dc")):
                        targets.append(
                            {
                                "row": row + int(t["dr"]),
                                "col": col + int(t["dc"]),
                                "weight": t.get("weight", 1.0),
                            }
                        )
                    elif _is_int(t.get("row")) and _is_int(t.get("col")):
                        item = {
                            "row": int(t["row"]),
                            "col": int(t["col"]),
                            "weight": t.get("weight", 1.0),
                        }
                        if isinstance(t.get("map_id"), str) and t["map_id"]:
                            item["map_id"] = t["map_id"]
                        targets.append(item)
                paths.append(
                    {
                        "label": path.get("label"),
                        "reveal_target": path.get("reveal_target", True),
                        "targets": targets,
                    }
                )
            out["connections"][direction] = {
                "direction": direction,
                "enabled": bool(slot.get("enabled")),
                "paths": paths,
            }
    return out


def _absolute_to_template(loc: dict) -> dict:
    """规范地块 dict → 模板负载（同图目标转回相对偏移，锚点在 (0,0)）。"""
    out: dict[str, Any] = {
        "name": loc["name"],
        "description": loc.get("description"),
        "connections": {},
    }
    for direction, slot in loc["connections"].items():
        paths = []
        for path in slot["paths"]:
            targets = []
            for t in path["targets"]:
                if t.get("map_id"):
                    targets.append(
                        {
                            "map_id": t["map_id"],
                            "row": t["row"],
                            "col": t["col"],
                            "weight": t["weight"],
                        }
                    )
                else:
                    targets.append(
                        {"dr": t["row"], "dc": t["col"], "weight": t["weight"]}
                    )
            item: dict[str, Any] = {
                "reveal_target": path["reveal_target"],
                "targets": targets,
            }
            if path.get("label"):
                item["label"] = path["label"]
            paths.append(item)
        out["connections"][direction] = {"enabled": slot["enabled"], "paths": paths}
    return out


def _location_template_payload(data: Any) -> dict[str, Any]:
    """地块模板负载规范化（best-effort：能规范就规范，缺 name 留到套用时再报错）。

    这样"先存个空壳模板、之后再填"仍然可行；真正套用时 `parse_location` 会以
    "地块名称不能为空"拒绝——报错发生在使用点，而不是保存点。
    """
    if not isinstance(data, dict):
        raise WorldError("地块模板 data 必须是对象")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return dict(data)
    loc = parse_location(_template_to_absolute(data, 0, 0))
    return _absolute_to_template(location_to_dict(loc))


def _location_from_template(data: dict, map_id: str, row: int, col: int) -> Any:
    """按放置坐标实例化地块模板（同图目标平移、跨图目标原样）。"""
    payload = _template_to_absolute(data, row, col)
    payload["map_id"] = map_id
    return parse_location(payload)


def _entity_template_payload(data: Any) -> dict[str, Any]:
    """实体模板负载校验 + 规范化（D22：{kind, tags[], name, desc, attrs, state}）。"""
    if not isinstance(data, dict):
        raise WorldError("实体模板 data 必须是对象")
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise WorldError("实体模板需要 kind（基底类型）")
    attrs = data.get("attrs")
    state = data.get("state")
    if attrs is not None and not isinstance(attrs, dict):
        raise WorldError("实体模板 attrs 必须是对象")
    if state is not None and not isinstance(state, dict):
        raise WorldError("实体模板 state 必须是对象")
    return {
        "kind": kind.strip(),
        "tags": parse_tags(data.get("tags")),
        "name": str(data.get("name") or "").strip(),
        "desc": str(data.get("desc") or ""),
        "attrs": dict(attrs or {}),
        "state": dict(state or {}),
    }


class WorldEngine:
    """世界底子的唯一权威引擎（插件进程内；事实模型 + 原语 + 注册表 + 事件总线）。"""

    def __init__(
        self,
        store: WorldStore,
        *,
        clock: Callable[[], datetime] | None = None,
        rand: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self._lock = AsyncRLock()
        # 时钟返回带时区的 datetime（默认本地时区）；rand 返回 [0,1)（默认 random）
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._rand = rand
        # 注册表（玩法包扩展点）
        # D18：类型与标签**共用一个命名空间**（_tag_specs）——register_entity_kind
        # 写入的是"隐式同名标签"，能力解析只有一条路径
        self._tag_specs: dict[str, TagSpec] = {}
        # 类型预设标签：register_entity_kind/type(kind, tags=[...]) → kind 自带的额外标签
        self._type_tags: dict[str, tuple[str, ...]] = {}
        # D21 规格级能力缓存：(kind, tags...) → 有序 TagSpec 列表（不含世界过滤）
        self._spec_cache: dict[tuple[str, tuple[str, ...]], tuple[TagSpec, ...]] = {}
        self._interactions: dict[str, _InteractionBinding] = {}
        self._event_bindings: dict[str, list[_EventBinding]] = {
            e: [] for e in WORLD_EVENTS
        }
        self._ui_components: dict[str, str] = {}
        self._ui_hooks: dict[tuple[str, str], list[_UiHookBinding]] = {}
        # D9/D10 字段设施：标签/分类/物品的追加字段声明（标签自身字段在 spec.fields）
        self._tag_fields: dict[str, list[_FieldAppend]] = {}
        self._category_fields: dict[str, list[_FieldAppend]] = {}
        self._item_fields: dict[str, list[_FieldAppend]] = {}
        # 物品定义归属（play_id）：玩法包卸载时清理其注册的物品定义（v0.2.0）
        self._item_def_play: dict[str, str] = {}
        # D11/A3 原语分派表：name -> 覆盖登记（无登记 = 内核默认实现）
        self._primitive_overrides: dict[str, _PrimitiveOverride] = {}
        # G14 原语过滤器链：name -> 按注册序的过滤器列表（链尾 = 默认实现）
        self._primitive_filters: dict[str, list[_PrimitiveFilter]] = {}
        # D2/G2 MCP 工具注册表（玩法包 register_tool；MCP server 动态同步）
        self._tools: dict[str, _ToolBinding] = {}
        self._mcp: Any | None = None  # 绑定后工具注册/清理即时 add/remove
        # G3/D7 视图注册表（玩法包 register_view；GET /views 暴露）
        self._views: dict[str, _ViewBinding] = {}
        # M3 跨包服务注册表：play_id -> name -> binding（玩法包间同步调用）
        self._services: dict[str, dict[str, _ServiceBinding]] = {}
        # 管理页注册表：play_id -> key -> binding（管理端导航 + actions 代理）
        self._admin_pages: dict[str, dict[str, _AdminPageBinding]] = {}
        # D22 玩法包注册的实体模板（内存：随包卸载消失；与落库的本地模板合并展示）
        self._play_templates: dict[str, dict] = {}
        # 玩法包 API 实例（PlayLoader attach；handler 调用时按 play_id 取）
        self._play_apis: dict[str, Any] = {}
        # 事件流订阅者（SSE 出口，B11：事件总线序列化推送；队列满丢最旧）
        self._subscribers: set[asyncio.Queue] = set()
        self._tick_task: asyncio.Task | None = None

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        """载入持久化数据并启动 on_tick 心跳循环。"""
        await self.store.initialize()
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def terminate(self) -> None:
        """取消心跳循环并关闭存储连接。"""
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        await self.store.close()

    # ---------- 辅助 ----------

    def _now_ts(self) -> float:
        return self._clock().timestamp()

    def _default_map_id(self) -> str:
        m = next(iter(self.store.maps.values()), None)
        if m is None:
            raise WorldError("世界尚未初始化")
        return m.id

    def _map_arg(self, map_id: object) -> str:
        if map_id in (None, ""):
            return self._default_map_id()
        if not isinstance(map_id, str) or map_id not in self.store.maps:
            raise WorldError(f"地图不存在：{map_id}")
        return map_id

    def _now_for(self, m: Any) -> datetime:
        now = self._clock()
        if m and m.timezone:
            try:
                return now.astimezone(ZoneInfo(m.timezone))
            except (KeyError, ValueError):
                return now
        return now

    def _require_entity(self, entity_id: str) -> Entity:
        entity = self.store.entities.get(entity_id)
        if entity is None:
            raise WorldError(f"实体不存在：{entity_id}")
        return entity

    # ---------- 玩法包注册（WorlditorPlayAPI 转发至此） ----------

    def register_item_def(self, item: Any, *, play_id: str = "") -> None:
        """注册/更新物品定义（同步更新内存；``flush_item_defs`` 批量落库）。

        物品 id 是类型键（玩法包引用），注册冲突即覆盖更新（同 id 视为同一物品）；
        ``play_id`` 记录归属，玩法包卸载时据此清理（见 item_defs_of_play）。
        """
        if not isinstance(item, ItemDef) and not (
            hasattr(item, "id") and hasattr(item, "name") and hasattr(item, "to_dict")
        ):
            raise WorldError("物品定义格式错误")
        if not isinstance(item.id, str) or not item.id:
            raise WorldError("物品 id 不能为空")
        if not isinstance(item.name, str) or not item.name.strip():
            raise WorldError("物品名称不能为空")
        self.store.items[item.id] = item
        if play_id:
            self._item_def_play[item.id] = play_id

    def item_defs_of_play(self, play_id: str) -> list[str]:
        """该玩法包注册的物品定义 id（卸载清理用）。"""
        return [i for i, p in self._item_def_play.items() if p == play_id]

    async def flush_item_defs(self) -> None:
        """把内存中的物品定义全量写回 items 表（PlayLoader 加载结束后调用）。"""
        async with self._lock:
            for item in list(self.store.items.values()):
                await self.store.save_item(item)

    async def delete_item_def(self, item_id: str) -> None:
        """删除物品定义（管理页；背包数据语义归持有方，此处不校验背包引用）。"""
        async with self._lock:
            item_id = _clean_required(item_id, "物品 id")
            if item_id not in self.store.items:
                raise WorldError(f"物品定义不存在：{item_id}")
            await self.store.delete_item(item_id)
            await self._emit(
                "on_world_edited", {"op": "delete_item_def", "item_id": item_id}
            )

    def register_entity_kind(
        self,
        kind: str,
        *,
        block_move: bool = False,
        interactions: tuple[str, ...] = (),
        label: str = "",
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
        tags: tuple[str, ...] | list[str] = (),
    ) -> None:
        """注册实体类型（D18：**就是注册一条隐式同名标签** + 一组预设标签）。

        v0.5 起 kind 退化为"预设的标志位"：它自身贡献一条名为 kind 的标签
        （``implicit=True``），再通过 ``tags`` 声明该类型**预设**的额外标签
        （"类型 A = {A, C}"）。老代码（只传 kind）行为完全不变——能力解析时
        基底 kind 本来就会作为标签参与并集。

        Args:
            block_move: 任一标签为真即阻挡（D19）。
            interactions: 默认可用的动作名（与全局注册表取并集）。
            label: 文案（B1）；也是放置实体时未给名字的默认名。
            play_id: 声明者（能力面按世界激活过滤，D21）。
            fields: 字段 schema（D9，UI 通用渲染）。
            categories: 分类标签（D10，宽松）。
            tags: 该类型**预设**的额外标签（D18）。
        """
        kind = _clean_required(kind, "kind")
        self._register_tag(
            kind,
            block_move=block_move,
            interactions=interactions,
            label=label,
            play_id=play_id,
            fields=fields,
            categories=categories,
            implicit=True,
        )
        if kind in self._type_tags or tags:
            self._type_tags[kind] = parse_tags(tags)
            self._invalidate_spec_cache()

    def register_entity_type(
        self,
        kind: str,
        *,
        tags: tuple[str, ...] | list[str] = (),
        label: str = "",
        block_move: bool = False,
        interactions: tuple[str, ...] = (),
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """注册"类型 = 标签预设"（D18：``register_entity_type("A", tags=["c"])``
        → 类型 A 的实体自带标签 ``A`` 与 ``c``）。等价于 ``register_entity_kind``，
        只是名字更贴合"类型只是预设"的模型。
        """
        self.register_entity_kind(
            kind,
            block_move=block_move,
            interactions=interactions,
            label=label,
            play_id=play_id,
            fields=fields,
            categories=categories,
            tags=tags,
        )

    def register_entity_tag(
        self,
        tag: str,
        *,
        label: str = "",
        block_move: bool = False,
        interactions: tuple[str, ...] = (),
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> None:
        """注册一条标签（D18：能力由标签承载；与类型共用一个命名空间）。"""
        tag = _clean_required(tag, "标签名")
        self._register_tag(
            tag,
            block_move=block_move,
            interactions=interactions,
            label=label,
            play_id=play_id,
            fields=fields,
            categories=categories,
            implicit=False,
        )

    def _register_tag(
        self,
        tag: str,
        *,
        block_move: bool,
        interactions: tuple[str, ...] | list[str],
        label: str,
        play_id: str,
        fields: list[dict] | None,
        categories: tuple[str, ...] | list[str],
        implicit: bool,
    ) -> None:
        if not isinstance(block_move, bool):
            raise WorldError("block_move 必须是布尔值")
        if not isinstance(interactions, (tuple, list)) or not all(
            isinstance(a, str) and a for a in interactions
        ):
            raise WorldError("interactions 必须是动作名列表")
        self._tag_specs[tag] = TagSpec(
            tag=tag,
            block_move=block_move,
            interactions=tuple(interactions),
            label=str(label or ""),
            play_id=play_id,
            fields=_validate_fields(fields or []),
            categories=tuple(
                str(c) for c in categories if isinstance(c, str) and c.strip()
            ),
            implicit=implicit,
        )
        self._invalidate_spec_cache()

    # ---------- 字段设施（D9 / D10） ----------

    def add_tag_fields(
        self, tag: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """向已有标签追加字段（D18：B 包给**任何带该标签的实体**加字段）。

        这就是 v0.4 之前的 ``add_kind_fields``——语义随 D18 扩张：以前只影响
        ``kind`` 恰好等于该名字的实体，现在影响所有带该标签的实体（含实例标签）。
        """
        tag = _clean_required(tag, "标签名")
        if tag not in self._tag_specs:
            raise WorldError(f"标签（类型）未注册：{tag}")
        self._tag_fields.setdefault(tag, []).extend(
            _FieldAppend(play_id=play_id, field=f) for f in _validate_fields(fields)
        )

    def add_kind_fields(
        self, kind: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """``add_tag_fields`` 的旧名（v0.2–v0.4 的调用点无需改动）。"""
        self.add_tag_fields(kind, fields, play_id=play_id)

    def add_category_fields(
        self, category: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """向分类追加字段（该分类全部标签生效；宽松，无需预注册分类）。"""
        category = _clean_required(category, "分类名")
        self._category_fields.setdefault(category, []).extend(
            _FieldAppend(play_id=play_id, field=f) for f in _validate_fields(fields)
        )

    def add_item_fields(
        self, item_id: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """向已有物品类型追加字段。"""
        item_id = _clean_required(item_id, "物品 id")
        if item_id not in self.store.items:
            raise WorldError(f"物品未注册：{item_id}")
        self._item_fields.setdefault(item_id, []).extend(
            _FieldAppend(play_id=play_id, field=f) for f in _validate_fields(fields)
        )

    def effective_fields(self, tag: str) -> list[dict]:
        """单个标签的有效字段 = 声明 ∪ 追加声明 ∪ 所属分类声明（D10 运行时合并）。"""
        return self._merge_fields([tag])

    def effective_fields_for(self, tags: list[str] | tuple[str, ...]) -> list[dict]:
        """多标签的有效字段（D19 覆盖顺序：列表靠后者优先）。"""
        return self._merge_fields(list(tags))

    def _merge_fields(self, tags: list[str]) -> list[dict]:
        """字段合并（D19 顺序）：标签字段（按列表顺序，靠后覆盖）→ 分类字段（最后）。"""
        merged: dict[str, dict] = {}
        categories: list[str] = []
        for tag in tags:
            spec = self._tag_specs.get(tag)
            if spec is None:
                continue  # 未注册标签：无行为贡献（D19/R6）
            for f in spec.fields + [a.field for a in self._tag_fields.get(tag, [])]:
                merged[f["name"]] = f
            for category in spec.categories:
                if category not in categories:
                    categories.append(category)
        for category in categories:
            for a in self._category_fields.get(category, []):
                merged[a.field["name"]] = a.field
        return list(merged.values())

    def list_kinds(self, category: str | None = None) -> list[dict]:
        """类型 + 标签清单（D25：含字段 schema、来源包、是否隐式、预设标签）。

        类型与标签共用一个命名空间，所以这是一张**合并清单**：``implicit=True``
        的条目来自 ``register_entity_kind``（即"类型"），False 来自
        ``register_entity_tag``（显式标签）。任何一条都可以当实体基底 kind 用。
        category 过滤（D10 精准选取）。
        """
        out = []
        for tag, spec in self._tag_specs.items():
            if category is not None and category not in spec.categories:
                continue
            out.append(
                {
                    "kind": tag,  # 兼容旧字段名（= 标签名）
                    "tag": tag,
                    "label": spec.label or tag,
                    "block_move": spec.block_move,
                    "interactions": list(spec.interactions),
                    "fields": self.effective_fields(tag),
                    "categories": list(spec.categories),
                    "play_id": spec.play_id,
                    "implicit": spec.implicit,
                    "preset_tags": list(self._type_tags.get(tag, ())),
                }
            )
        return sorted(out, key=lambda k: k["tag"])

    # ---------- 标签能力解析（D18 / D19 / D21） ----------

    def _invalidate_spec_cache(self) -> None:
        """注册表变动即清空规格缓存（D21：缓存以 (kind, tags) 为键，不含世界）。"""
        self._spec_cache.clear()

    def entity_tags(self, entity: Entity) -> list[str]:
        """实体有效标签 = 基底 kind + 类型预设标签 + 实例 tags（去重保序）。"""
        return parse_tags(
            [entity.kind, *self._type_tags.get(entity.kind, ()), *entity.tags]
        )

    def _entity_specs(self, entity: Entity) -> tuple[TagSpec, ...]:
        """有效标签对应的规格（**不含世界过滤**；规格级缓存，D21/C1）。

        未注册的标签没有规格 → 不贡献任何能力（实体照常存在，D19/R6）。
        """
        key = (entity.kind, tuple(entity.tags))
        cached = self._spec_cache.get(key)
        if cached is not None:
            return cached
        specs = tuple(
            spec
            for tag in self.entity_tags(entity)
            if (spec := self._tag_specs.get(tag)) is not None
        )
        self._spec_cache[key] = specs
        return specs

    def _active_specs(self, entity: Entity) -> tuple[TagSpec, ...]:
        """按实体**所在世界**过滤后的规格（D21：标签所属包未激活 → 不参与并集）。"""
        world_id = self.store.map_world.get(entity.map_id)
        return tuple(
            spec
            for spec in self._entity_specs(entity)
            if not spec.play_id or self._world_play_active(world_id, spec.play_id)
        )

    def capabilities(self, entity: Entity) -> dict:
        """实体合并后的能力（D19；管理端/编辑器诊断 + 玩法包自查用）。

        block_move = 任一标签为真；interactions = 并集；fields = 按
        隐式 kind 标签 → 实例 tags（数组序）→ 分类字段 的顺序合并。

        同时把标签**分三类**报出来，便于编辑器解释"为什么没效果"：
        ``inactive_tags``（注册了但该世界未激活）、``unknown_tags``（没注册）。
        （诊断路径不做缓存，热路径走 `_active_specs`。）
        """
        world_id = self.store.map_world.get(entity.map_id)
        active: list[str] = []
        inactive: list[str] = []
        unknown: list[str] = []
        for tag in self.entity_tags(entity):
            spec = self._tag_specs.get(tag)
            if spec is None:
                unknown.append(tag)
            elif not spec.play_id or self._world_play_active(world_id, spec.play_id):
                active.append(tag)
            else:
                inactive.append(tag)
        specs = [self._tag_specs[t] for t in active]
        return {
            "tags": self.entity_tags(entity),
            "active_tags": active,
            "inactive_tags": inactive,
            "unknown_tags": unknown,
            "block_move": any(s.block_move for s in specs),
            "interactions": sorted({a for s in specs for a in s.interactions}),
            "fields": self.effective_fields_for(active),
        }

    # ---------- MCP 工具注册（D2 / G2） ----------

    def attach_mcp(self, mcp: Any) -> None:
        """绑定 MCP server：此后 register_tool / 清理工具即时同步 add/remove。"""
        self._mcp = mcp
        for name in list(self._tools):
            self._sync_tool_add(name)
        self._refresh_instructions()

    def _refresh_instructions(self) -> None:
        """按当前工具集刷新 MCP instructions（零工具时提示未加载玩法包）。"""
        settings = getattr(self._mcp, "settings", None)
        if settings is None:
            return
        try:
            from .mcp import build_instructions

            settings.instructions = build_instructions(self)
        except Exception:  # noqa: BLE001
            logger.debug("[worlditor] MCP instructions 刷新失败", exc_info=True)

    def _sync_tool_add(self, name: str) -> None:
        if self._mcp is None:
            return
        binding = self._tools.get(name)
        if binding is None:
            return
        from .mcp import build_dynamic_tool

        self._mcp.add_tool(
            build_dynamic_tool(self, binding, name),
            name=name,
            description=binding.description or f"玩法包工具：{name}",
        )
        self._refresh_instructions()

    def _sync_tool_remove(self, name: str) -> None:
        if self._mcp is not None:
            try:
                self._mcp.remove_tool(name)
            except Exception:  # noqa: BLE001
                logger.debug("[worlditor] MCP 工具移除失败（可能未注册）：%s", name)
            self._refresh_instructions()

    def register_tool(
        self,
        name: str,
        handler: Callable,
        *,
        description: str = "",
        params: dict[str, str] | None = None,
        play_id: str = "",
    ) -> None:
        """注册 MCP 工具（G2：handler(api, ctx, **args)，身份经 api.caller()）。

        同名工具冲突**报错拒绝**（D2，避免静默替换）。
        """
        name = _clean_required(name, "工具名")
        if name in self._tools:
            prev = self._tools[name]
            raise WorldError(f"工具名冲突：{name}（已由 {prev.play_id} 注册）")
        if not callable(handler):
            raise WorldError("工具 handler 必须是可调用对象")
        params = dict(params or {})
        for pname, ptype in params.items():
            if ptype not in ("string", "integer", "number", "boolean", "array"):
                raise WorldError(
                    f"工具参数类型必须是 string/integer/number/boolean/array：{pname}"
                )
        self._tools[name] = _ToolBinding(
            play_id=play_id,
            handler=handler,
            description=str(description or ""),
            params=params,
        )
        self._sync_tool_add(name)

    def list_tools(self) -> list[dict]:
        """已注册工具（管理页可见：谁注册了什么）。"""
        return [
            {
                "name": name,
                "play_id": b.play_id,
                "description": b.description,
                "params": dict(b.params),
            }
            for name, b in sorted(self._tools.items())
        ]

    # ---------- 视图注册（G3 / D7） ----------

    def register_view(
        self,
        key: str,
        *,
        title: str,
        icon: str = "",
        provider: dict | None = None,
        play_id: str = "",
    ) -> None:
        """注册 WebUI 视图（G3：provider = {type, url} 组件入口；WebUI 动态加载）。

        视图 key 冲突报错（同 D2 风格）。
        """
        key = _clean_required(key, "视图 key")
        title = _clean_required(title, "视图标题")
        if key in self._views:
            prev = self._views[key]
            raise WorldError(f"视图 key 冲突：{key}（已由 {prev.play_id} 注册）")
        provider = dict(provider or {})
        ptype = provider.get("type")
        if ptype is not None and ptype != "component":
            raise WorldError("视图 provider.type 仅支持 component")
        # 视图安全（阶段 3）：url 必须指向本站本包资源（/plays/<play_id>/web/…）
        # —— WebUI 对 provider.url fetch 时附带 Bearer，跨站 URL 会外泄凭据
        url = str(provider.get("url") or "")
        url_prefix = f"/plays/{play_id}/web/"
        if not url.startswith(url_prefix):
            raise WorldError(f"视图 provider.url 必须指向本站本包资源（{url_prefix}…）")
        self._views[key] = _ViewBinding(
            play_id=play_id,
            title=title,
            icon=str(icon or ""),
            provider={"type": "component", "url": url},
        )

    def list_views(self) -> list[dict]:
        """视图列表（GET /views：管理页展示与前端路由初始化共用，G3）。"""
        return [
            {
                "key": key,
                "title": v.title,
                "icon": v.icon,
                "play_id": v.play_id,
                "provider": dict(v.provider),
            }
            for key, v in sorted(self._views.items())
        ]

    # ---------- 玩法包管理页（v0.1.12：管理端注册协议） ----------

    def register_admin_page(
        self,
        key: str,
        *,
        title: str,
        icon: str = "",
        component_url: str,
        actions: dict[str, Callable],
        play_id: str = "",
    ) -> None:
        """注册玩法包管理页（管理端可多页；actions = 玩法包自管的数据动作）。

        管理页协议（与 register_view 同源的安全模型）：
        - component_url 必须指向本站本包资源（``/plays/<play_id>/web/…``）——
          管理端加载组件时附带 Bearer，跨站 URL 会外泄凭据；
        - actions 为玩法包定义的管理动作，handler 签名 ``async (api, **params)``
          （api 为提供者自己的 API 实例），由管理端点锁内代理调用——数据
          语义（背包 slots、物品定义字段等）只有玩法包自己懂，内核不裸露
          play_data 编辑。
        - 同包 key 冲突报错（同 D2 风格）；生命周期随玩法包卸载清理。

        Raises:
            WorldError: key/title 非法、component_url 非本包资源、无 action、
                action 不可调用、同包 key 冲突。
        """
        key = _clean_required(key, "管理页 key")
        title = _clean_required(title, "管理页标题")
        if not isinstance(actions, dict) or not actions:
            raise WorldError("管理页需要至少一个 action")
        cleaned: dict[str, Callable] = {}
        for name, handler in actions.items():
            aname = _clean_required(name, "action 名")
            if not callable(handler):
                raise WorldError(f"action「{aname}」必须是可调用对象")
            cleaned[aname] = handler
        url = str(component_url or "")
        url_prefix = f"/plays/{play_id}/web/"
        if not url.startswith(url_prefix):
            raise WorldError(
                f"管理页 component_url 必须指向本站本包资源（{url_prefix}…）"
            )
        pages = self._admin_pages.setdefault(play_id, {})
        if key in pages:
            prev = pages[key]
            raise WorldError(
                f"管理页 key 冲突：{play_id}.{key}（已注册「{prev.title}」）"
            )
        pages[key] = _AdminPageBinding(
            play_id=play_id,
            key=key,
            title=title,
            icon=str(icon or ""),
            component_url=url,
            actions=cleaned,
        )

    def list_admin_pages(self) -> list[dict]:
        """管理页清单（GET /admin/play-pages：管理端导航，按 (play_id, key) 排序）。"""
        return [
            {
                "play_id": pid,
                "key": binding.key,
                "title": binding.title,
                "icon": binding.icon,
                "component_url": binding.component_url,
                "actions": sorted(binding.actions),
            }
            for pid in sorted(self._admin_pages)
            for binding in sorted(self._admin_pages[pid].values(), key=lambda b: b.key)
        ]

    async def call_admin_page_action(
        self, play_id: str, page_key: str, action: str, **params: Any
    ) -> Any:
        """管理端点代理：锁内调用玩法包管理动作（异常隔离，同 call_service）。

        handler 收到的是**提供者自己的 API 实例**（play_id 已绑定，kv/工具/
        服务等均以其身份），数据校验与语义完全由玩法包负责；内核不做裸
        play_data 编辑。

        Raises:
            WorldError: 管理页/action 不存在、提供方未加载、执行异常。
        """
        pages = self._admin_pages.get(play_id) or {}
        binding = pages.get(page_key)
        if binding is None:
            raise WorldError(f"管理页不存在：{play_id}.{page_key}")
        handler = binding.actions.get(action)
        if handler is None:
            raise WorldError(f"管理页 action 不存在：{play_id}.{page_key}.{action}")
        api = self._play_apis.get(play_id)
        if api is None:
            raise WorldError(f"玩法包未加载：{play_id}")
        async with self._lock:
            try:
                return await self._invoke(handler, api, **params)
            except asyncio.CancelledError:
                raise
            except WorldError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worlditor] 管理页 action 异常：%s.%s.%s",
                    play_id,
                    page_key,
                    action,
                )
                raise WorldError("管理页操作执行出错，请稍后再试") from None

    # ---------- 跨包服务（M3：玩法包间同步调用通道） ----------

    def register_service(self, name: str, handler: Callable, play_id: str) -> None:
        """登记玩法包服务（供其他玩法包同步调用）。

        服务 = 玩法包能力边界内的操作（如 items 包的背包读写）；handler
        签名 ``async (api, **params) -> Any``（api 为提供者自己的 API 实例）。
        同包服务名冲突报错（同 D2 风格）；生命周期随包卸载清理。

        Raises:
            WorldError: 服务名非法、handler 不可调用、同名冲突。
        """
        name = _clean_required(name, "服务名")
        if not callable(handler):
            raise WorldError("服务 handler 必须是可调用对象")
        services = self._services.setdefault(play_id, {})
        if name in services:
            raise WorldError(f"服务名冲突：{play_id}.{name}（已注册）")
        services[name] = _ServiceBinding(play_id=play_id, name=name, handler=handler)

    def list_services(self) -> list[dict]:
        """服务列表（管理页可见：谁提供了什么服务）。"""
        return [
            {"play_id": pid, "name": name}
            for pid in sorted(self._services)
            for name in sorted(self._services[pid])
        ]

    async def call_service(
        self, caller_play_id: str, target_play_id: str, name: str, **params: Any
    ) -> Any:
        """跨包同步调用服务（锁内执行 + 异常隔离）。

        Args:
            caller_play_id: 调用方 play_id（API 注入，用于日志）。
            target_play_id: 服务提供方 play_id。
            name: 服务名。
            **params: 服务参数（由提供方定义）。

        Returns:
            服务返回值（Any，JSON 可序列化为宜）。

        Raises:
            WorldError: 服务不存在、提供方未加载、服务执行异常。
        """
        services = self._services.get(target_play_id)
        binding = services.get(name) if services else None
        if binding is None:
            raise WorldError(f"服务不存在：{target_play_id}.{name}")
        api = self._play_apis.get(target_play_id)
        if api is None:
            raise WorldError(f"服务提供方未加载：{target_play_id}")
        async with self._lock:
            try:
                return await self._invoke(binding.handler, api, **params)
            except asyncio.CancelledError:
                raise
            except WorldError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worlditor] 服务执行异常：%s.%s（调用方 %s）",
                    target_play_id,
                    name,
                    caller_play_id,
                )
                raise WorldError("服务执行出错，请稍后再试") from None

    # ---------- 原语分派（D11 / A3 / G14） ----------

    def override_primitive(self, name: str, handler: Callable, play_id: str) -> None:
        """登记原语覆盖（锁内回调 handler(api, *args, **kwargs)）。

        每原语至多一个登记项；已登记（override 或 disable）再登记报错（同 D2）；
        与过滤器链互斥（已挂过滤器时登记报错）。
        """
        name = _check_primitive_name(name)
        if not callable(handler):
            raise WorldError("覆盖 handler 必须是可调用对象")
        self._check_primitive_free(name, "登记 override")
        self._primitive_overrides[name] = _PrimitiveOverride(
            play_id=play_id, handler=handler
        )

    def disable_primitive(self, name: str, play_id: str) -> None:
        """登记原语禁用（调用抛"该能力已被禁用"；与 override/过滤器互斥）。"""
        name = _check_primitive_name(name)
        self._check_primitive_free(name, "登记 disable")
        self._primitive_overrides[name] = _PrimitiveOverride(play_id=play_id)

    def register_primitive_filter(
        self,
        name: str,
        filter: Callable,
        *,
        label: str = "",
        play_id: str = "",
    ) -> None:
        """登记原语过滤器（G14：filter(api, **params) -> dict | ShortCircuit）。

        三态语义：raise WorldError = 否决；返回参数字典 = 参数改写继续链；
        返回 ShortCircuit(value) = 短路（跳过后续过滤器与默认实现）。
        同一包可注册多个过滤器（各带 label）；与 override/disable 互斥；
        链序 = 注册序（加载序）；生命周期随玩法包卸载清理。
        """
        name = _check_primitive_name(name)
        if not callable(filter):
            raise WorldError("过滤器必须是可调用对象")
        self._check_primitive_free(name, "登记过滤器")
        self._primitive_filters.setdefault(name, []).append(
            _PrimitiveFilter(play_id=play_id, filter=filter, label=str(label or ""))
        )

    def _check_primitive_free(self, name: str, what: str) -> None:
        """override/disable 与过滤器互斥检查（过滤器之间不互斥，G14）。"""
        if name in self._primitive_overrides:
            prev = self._primitive_overrides[name]
            raise WorldError(
                f"原语「{name}」已被 {prev.play_id} 登记（override/disable），无法{what}"
            )
        if what == "登记 override" or what == "登记 disable":
            if self._primitive_filters.get(name):
                prev = self._primitive_filters[name][0]
                raise WorldError(
                    f"原语「{name}」已挂过滤器（{prev.play_id} 等），无法{what}"
                )

    def list_primitive_overrides(self) -> list[dict]:
        """覆盖/禁用状态（管理页可见：谁覆盖了什么、谁禁用了什么）。"""
        return [
            {
                "name": name,
                "play_id": ov.play_id,
                "mode": "override" if ov.handler is not None else "disable",
            }
            for name, ov in sorted(self._primitive_overrides.items())
        ]

    def list_primitive_filters(self) -> list[dict]:
        """过滤器链状态（管理页可见：谁挂了什么、顺序）。"""
        return [
            {"name": name, "play_id": f.play_id, "label": f.label}
            for name in sorted(self._primitive_filters)
            for f in self._primitive_filters[name]
        ]

    async def call_default_primitive(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """super 通道：显式调用内核默认实现（绕过分派表；覆盖者前置/后置用）。

        与分派入口同锁（任务级重入）：覆盖者持锁时为重入，锁外调用亦安全。
        """
        name = _check_primitive_name(name)
        async with self._lock:
            return await getattr(self, _PRIMITIVE_DEFAULT_NAMES[name])(*args, **kwargs)

    async def _dispatch_primitive(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """原语统一分派入口（D11/A3/G14）——在引擎锁内执行。

        DESIGN §2.4：override / 过滤器链 / 默认实现的 handler 均锁内回调
        （AsyncRLock 任务级重入，handler 内再调 API 原语安全）。
        优先级：disable → 报错；override → 锁内回调（短路）；过滤器链（按注册序，
        否决/改参/短路）→ 链尾默认实现；无登记 → 默认实现。
        """
        async with self._lock:
            return await self._dispatch_locked(name, *args, **kwargs)

    async def _dispatch_locked(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """分派表主体（调用方持锁；见 _dispatch_primitive）。

        D15 世界过滤：覆盖者/过滤器所属玩法包在**行为主体所在世界**未激活时
        视为不存在（回落内核默认实现）——"给某世界停用一个包 = 该世界失去
        对应行为"，其他世界不受影响。
        """
        params = _primitive_params(name, args, kwargs)
        world_id = self.entity_world(params.get("entity_id") or "")
        ov = self._primitive_overrides.get(name)
        if ov is not None and not self._world_play_active(world_id, ov.play_id):
            ov = None  # 覆盖者不在本世界 → 回到默认实现
        if ov is not None:
            if ov.handler is None:
                raise WorldError(f"该能力已被禁用（{ov.play_id}）")
            api = self._play_apis.get(ov.play_id)
            if api is None:
                raise WorldError(f"覆盖者 {ov.play_id} 未加载")
            try:
                return await self._invoke(ov.handler, api, *args, **kwargs)
            except asyncio.CancelledError:
                raise
            except WorldError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worlditor] 原语覆盖 handler 异常：%s (%s)", name, ov.play_id
                )
                raise WorldError("原语执行出错，请稍后再试") from None
        filters = [
            f
            for f in self._primitive_filters.get(name) or []
            if self._world_play_active(world_id, f.play_id)
        ]
        if filters:
            for f in filters:
                api = self._play_apis.get(f.play_id)
                result = await self._invoke(f.filter, api, **params)
                if isinstance(result, ShortCircuit):
                    return result.value
                if not isinstance(result, dict):
                    raise WorldError(
                        f"原语过滤器必须返回参数对象或 ShortCircuit（{f.play_id}）"
                    )
                params = result
            return await getattr(self, _PRIMITIVE_DEFAULT_NAMES[name])(**params)
        return await getattr(self, _PRIMITIVE_DEFAULT_NAMES[name])(*args, **kwargs)

    # ---------- 交互 ----------

    def register_interaction(
        self,
        action: str,
        handler: InteractionHandler,
        *,
        label: str = "",
        play_id: str = "",
    ) -> None:
        """注册全局交互动作（C3：可用动作 = kind 声明 ∪ 全局注册表）。"""
        action = _clean_required(action, "动作名")
        if not callable(handler):
            raise WorldError("交互 handler 必须是可调用对象")
        self._interactions[action] = _InteractionBinding(
            play_id=play_id, handler=handler, label=str(label or action)
        )

    def register_world_event(
        self,
        event: str,
        handler: WorldEventHandler,
        *,
        interval: float = 0.0,
        play_id: str = "",
    ) -> None:
        """订阅世界事件；on_tick 需给出 interval（各自间隔，A3）。

        事件名开放（D1/G8：任意事件名，语义由玩法包定义）；预置事件见
        model.WORLD_EVENTS。
        """
        event = _clean_required(event, "事件名")
        if not callable(handler):
            raise WorldError("事件 handler 必须是可调用对象")
        if event == "on_tick":
            if interval <= 0:
                raise WorldError("on_tick 需要正的 interval 秒数")
        self._event_bindings.setdefault(event, []).append(
            _EventBinding(play_id=play_id, handler=handler, interval=float(interval))
        )

    def register_ui_component(
        self, name: str, web_entry: str, *, play_id: str = ""
    ) -> None:
        """注册自定义界面组件（B9；WebUI 落地）。"""
        name = _clean_required(name, "组件名")
        if play_id:
            name = f"{play_id}.{name}"
        self._ui_components[name] = _clean_required(web_entry, "组件入口")

    def register_ui_hook(
        self,
        block_kind: str,
        position: str,
        provider: UiHookProvider,
        *,
        play_id: str = "",
    ) -> None:
        """向已有界面块注入子块（B9：before/after/replace；渲染落地）。"""
        if position not in ("before", "after", "replace"):
            raise WorldError("position 必须是 before/after/replace 之一")
        if not callable(provider):
            raise WorldError("钩子 provider 必须是可调用对象")
        key = (block_kind, position)
        self._ui_hooks.setdefault(key, []).append(_UiHookBinding(play_id, provider))

    def attach_play_api(self, play_id: str, api: Any) -> None:
        """绑定玩法包 API 实例（PlayLoader 调用；事件 handler 按 play_id 取）。"""
        self._play_apis[play_id] = api

    def detach_play_api(self, play_id: str) -> None:
        self._play_apis.pop(play_id, None)

    def clear_play_registrations(self, play_id: str) -> None:
        """清理某玩法包的全部注册（kind / interaction / event / ui / 字段 /
        原语分派），供加载失败回滚与卸载使用（C2：重载 = 引擎重建，此为兜底清理）。

        原语分派登记随生命周期清除 → 自动恢复内核默认实现（§2.4 恢复语义）。
        """
        self._tag_specs = {
            k: v for k, v in self._tag_specs.items() if v.play_id != play_id
        }
        self._type_tags = {
            k: v for k, v in self._type_tags.items() if k in self._tag_specs
        }
        self._interactions = {
            k: v for k, v in self._interactions.items() if v.play_id != play_id
        }
        for event in self._event_bindings:
            self._event_bindings[event] = [
                b for b in self._event_bindings[event] if b.play_id != play_id
            ]
        self._ui_components = {
            k: v
            for k, v in self._ui_components.items()
            if not k.startswith(f"{play_id}.")
        }
        self._ui_hooks = {
            k: [b for b in v if b.play_id != play_id]
            for k, v in self._ui_hooks.items()
            if any(b.play_id != play_id for b in v)
        }
        self._tag_fields = {
            k: [a for a in v if a.play_id != play_id]
            for k, v in self._tag_fields.items()
            if any(a.play_id != play_id for a in v)
        }
        self._category_fields = {
            k: [a for a in v if a.play_id != play_id]
            for k, v in self._category_fields.items()
            if any(a.play_id != play_id for a in v)
        }
        self._item_fields = {
            k: [a for a in v if a.play_id != play_id]
            for k, v in self._item_fields.items()
            if any(a.play_id != play_id for a in v)
        }
        # 本包注册的物品定义：内存清理（落库删除由 PlayLoader._teardown_one 负责）
        for item_id in self.item_defs_of_play(play_id):
            self.store.items.pop(item_id, None)
            self._item_def_play.pop(item_id, None)
        self._primitive_overrides = {
            k: v for k, v in self._primitive_overrides.items() if v.play_id != play_id
        }
        self._primitive_filters = {
            k: [f for f in v if f.play_id != play_id]
            for k, v in self._primitive_filters.items()
            if any(f.play_id != play_id for f in v)
        }
        for name in [n for n, b in self._tools.items() if b.play_id == play_id]:
            self._tools.pop(name, None)
            self._sync_tool_remove(name)
        self._views = {k: v for k, v in self._views.items() if v.play_id != play_id}
        self._services.pop(play_id, None)
        self._admin_pages.pop(play_id, None)
        self._play_templates = {
            k: v for k, v in self._play_templates.items() if v.get("play_id") != play_id
        }
        self._invalidate_spec_cache()

    # ---------- 界面扩展（B9：ui_hook before/after/replace 递归展开） ----------

    async def apply_ui_hooks(
        self, block: Any | None, *, entity_id: str | None = None
    ) -> Any | None:
        """把玩法包注册的界面钩子应用到界面块（递归展开子块）。

        before/after：注入子块；replace：整体替换目标块（provider 返回的
        首个子块）。provider 异常被隔离（记日志跳过），不破坏渲染。
        锁内执行（可重入；provider 为玩法包回调，统一「锁内」不变量）。

        Args:
            block: UiBlock 或 None。
            entity_id: 查看者实体（D15：注入方在该实体所在世界未启用 → 不注入；
                None = 不做世界过滤，供无身份场景使用）。

        Returns:
            展开后的 UiBlock；``block`` 为 None 时返回 None。
        """
        async with self._lock:
            return await self._apply_ui_hooks_locked(block, entity_id)

    async def _apply_ui_hooks_locked(
        self, block: Any | None, entity_id: str | None = None
    ) -> Any | None:
        """钩子展开主体（调用方持锁；见 apply_ui_hooks）。"""
        from .model import UiBlock

        if block is None:
            return None
        if not isinstance(block, UiBlock):
            return block
        # 1. 先递归展开子块
        block.blocks = await self._expand_children(block.blocks, entity_id)
        # 2. 本块钩子
        before: list[UiBlock] = []
        after: list[UiBlock] = []
        replaced: UiBlock | None = None
        for position in ("before", "after", "replace"):
            for binding in self._ui_hooks.get((block.kind, position), []):
                if not self.play_active_for_entity(entity_id, binding.play_id):
                    continue  # 注入方不在查看者所在世界 → 不注入（D15）
                api = self._play_apis.get(binding.play_id)
                try:
                    injected = await self._invoke(binding.provider, api, block)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[worlditor] ui_hook(%s/%s) 异常：%s",
                        block.kind,
                        position,
                        binding.play_id,
                    )
                    continue
                if not isinstance(injected, list):
                    continue
                if position == "replace" and injected:
                    replaced = injected[0]
                elif position == "before":
                    before.extend(injected)
                elif position == "after":
                    after.extend(injected)
        if replaced is not None:
            # replace：整体替换；新块的子块递归展开（自身 replace 钩子不再
            # 应用，防 A 的 replace 又返回 A 的循环）
            replaced.blocks = await self._expand_children(replaced.blocks, entity_id)
            return replaced
        block.blocks = before + block.blocks + after
        return block

    async def _expand_children(
        self, blocks: list, entity_id: str | None = None
    ) -> list:
        """递归展开一组子块（None 剔除）。"""
        from .model import UiBlock

        expanded: list[UiBlock] = []
        for child in blocks:
            child = await self.apply_ui_hooks(child, entity_id=entity_id)
            if child is not None:
                expanded.append(child)
        return expanded

    # ---------- 事件总线（单一事件源） ----------

    async def _invoke(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """调用玩法包 handler：兼容 async / 同步函数（同步返回值直接透传）。"""
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def invoke_locked(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """在引擎锁内执行玩法包回调（DESIGN §2.4「handler 锁内执行」）。

        用于锁外入口（MCP 工具回调等）：handler 全程持锁，多段「读-判-写」
        原子。AsyncRLock 为任务级可重入——handler 内再调 API 原语安全。

        红线：handler 内禁止 ``asyncio.create_task`` 后等待子任务——子任务
        不属于当前任务，无法获得本节持有的锁（死锁）；后台任务须遵守 G5
        约定（自管 task 在 ``teardown(api)`` 中取消）。
        """
        async with self._lock:
            return await self._invoke(fn, *args, **kwargs)

    async def emit(self, event: str, data: Any = None, *, log: bool = False) -> None:
        """自定义事件（G8：任意事件名，SSE 推送；默认不写 world_log）。

        Args:
            event: 事件名（说话/广播等自定义语义由玩法包定义，D1）。
            data: 事件数据（dict 或任意 JSON 可序列化值）。
            log: 是否写入 world_log（需回放的事件显式 True）。
        """
        async with self._lock:  # 入口自持锁（可重入）；锁外调用亦安全
            await self._emit(event, data, log=log)

    async def _emit(self, event: str, *args: Any, log: bool = True) -> None:
        """分发事件给订阅者（串行 + 异常隔离），并写入世界日志。

        调用方持锁；handler 内调原语可重入（AsyncRLock）。
        世界激活过滤（D15）：事件带实体时按实体所在世界检查玩法包激活。
        """
        for binding in list(self._event_bindings.get(event, [])):
            if not self._binding_active(event, binding.play_id, args):
                continue
            api = self._play_apis.get(binding.play_id)
            try:
                await self._invoke(binding.handler, api, *args)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worlditor] 事件 handler 异常：%s (%s)", event, binding.play_id
                )
        if log:
            await self._append_log(event, args)
        if event != "on_tick":
            self._push_to_subscribers(self._event_payload(event, args))

    def _binding_active(self, event: str, play_id: str, args: tuple) -> bool:
        """世界激活过滤（D15）：on_tick 与无实体事件不过滤。"""
        if event == "on_tick":
            return True
        entity = next((a for a in args if isinstance(a, Entity)), None)
        if entity is None:
            return True
        world_id = self.store.map_world.get(entity.map_id)
        if world_id is None:
            return True
        return self._world_play_active(world_id, play_id)

    def _world_play_active(self, world_id: str | None, play_id: str) -> bool:
        """世界激活集合判断：世界不存在或 play_ids 为空 = 全部激活（D15）。

        未归属世界的地图按**默认世界**算（`_world_for_activation`）——世界是
        数据边界，"没有归属"不等于"没有规则"。
        """
        world_id = self._world_for_activation(world_id)
        if world_id is None:
            return True
        world = self.store.worlds.get(world_id)
        if world is None or not world.play_ids:
            return True
        return play_id in world.play_ids

    def _world_for_activation(self, world_id: str | None) -> str | None:
        """激活判定用的世界：未归属（None）→ 默认世界；默认世界不存在 → None。"""
        if world_id is not None:
            return world_id
        return DEFAULT_WORLD_ID if DEFAULT_WORLD_ID in self.store.worlds else None

    def play_active_for_entity(self, entity_id: str | None, play_id: str) -> bool:
        """该实体所在世界是否启用了某玩法包（D15；世界未知 = 放行）。

        工具面/视图面按**调用者**所在世界过滤，原语与 kind 行为按**行为主体**
        所在世界过滤——都收敛到这一个判断上。
        """
        return self._world_play_active(self.entity_world(entity_id or ""), play_id)

    async def _append_log(self, event: str, args: tuple) -> None:
        """事件写入 world_log（历史/回放数据源；on_tick 不写）。"""
        entity_id = None
        for arg in args:
            if isinstance(arg, Entity):
                entity_id = arg.id
                break
            if isinstance(arg, InteractionRequest):
                entity_id = arg.entity_id
                break
        data: dict[str, Any] = {}
        for arg in args:
            if isinstance(arg, Entity):
                data["entity"] = arg.to_dict()
            elif isinstance(arg, InteractionRequest):
                data["request"] = {
                    "entity_id": arg.entity_id,
                    "target_id": arg.target.id if arg.target else None,
                    "action": arg.action,
                    "args": arg.args,
                    "item_id": arg.item_id,
                }
            elif isinstance(arg, InteractionResult):
                data["result"] = arg.to_dict()
            elif isinstance(arg, tuple):
                data.setdefault("positions", []).append(list(arg))
            elif isinstance(arg, dict):
                data.setdefault("dicts", []).append(arg)
            elif arg is not None:
                data.setdefault("values", []).append(arg)
        await self.store.append_world_log(
            self._now_ts(), entity_id, event, {"event": event, **data}
        )

    # ---------- 事件流订阅（SSE 出口，B11） ----------

    def subscribe(self) -> asyncio.Queue:
        """订阅世界事件流：返回队列，事件入队（队列满丢最旧）。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _push_to_subscribers(self, payload: dict | None) -> None:
        if payload is None or not self._subscribers:
            return
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)

    def _event_payload(self, event: str, args: tuple) -> dict | None:
        """事件 → SSE payload（WebUI 增量更新用；实体全量序列化）。"""
        entity = next((a for a in args if isinstance(a, Entity)), None)
        payload: dict[str, Any] = {
            "event": event,
            "ts": self._now_ts(),
            "entity": entity.to_dict() if entity else None,
        }
        if event == "on_entity_move":
            payload["from"] = list(args[1])
            payload["to"] = list(args[2])
        elif event == "on_entity_enter":
            payload["map_id"] = args[1]
            payload["row"] = args[2]
            payload["col"] = args[3]
        elif event == "on_interact":
            req, result = args[0], args[1]
            payload["request"] = {
                "action": req.action,
                "target_id": req.target.id if req.target else None,
                "item_id": req.item_id,
            }
            payload["result"] = result.to_dict()
        elif event == "on_item_used":
            # D8：内核无背包——count 由玩法包自管，事件不带持有数
            payload["item_id"] = args[1]
            payload["result"] = (
                args[3].to_dict() if isinstance(args[3], InteractionResult) else None
            )
        elif event == "on_entity_changed":
            payload["changed"] = args[1]
        elif event == "on_entity_removed":
            payload["entity"] = args[0].to_dict()
        elif event == "on_world_edited":
            payload["what"] = args[0]
        else:
            # 自定义事件（G8）：数据原样透传（单参 dict 展开为 data）
            payload["data"] = args[0] if len(args) == 1 else list(args)
        return payload

    # ---------- 心跳（A3：单循环 + 各自间隔 + 串行 + 异常隔离） ----------

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_GRANULARITY_SECONDS)
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("[worlditor] 心跳循环异常")

    async def _tick_once(self) -> None:
        """心跳一轮：到期 on_tick handler 依次执行（各自间隔）。"""
        bindings = [
            b for b in self._event_bindings.get("on_tick", []) if b.interval > 0
        ]
        if not bindings:
            return
        now = self._now_ts()
        async with self._lock:
            for binding in bindings:
                if now - binding.last_run < binding.interval:
                    continue
                dt = now - binding.last_run if binding.last_run else binding.interval
                binding.last_run = now
                api = self._play_apis.get(binding.play_id)
                try:
                    await self._invoke(binding.handler, api, dt)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[worlditor] on_tick handler 异常：%s", binding.play_id
                    )

    # ---------- 只读接口（读内存快照，免锁） ----------

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.store.entities.get(entity_id)

    def list_entities(
        self,
        map_id: str | None = None,
        row: int | None = None,
        col: int | None = None,
        viewer_id: str | None = None,
    ) -> list[Entity]:
        """实体列表；viewer_id 传入时按隐身过滤（G12）。

        实体字段 ``invisible`` 为真时对普通 viewer 隐藏；viewer 自身字段
        ``see_invisible`` 为真（真视）或查看自己时可见。
        """
        entities = list(self.store.entities.values())
        if map_id is not None:
            entities = [e for e in entities if e.map_id == map_id]
        if row is not None:
            entities = [e for e in entities if e.row == row]
        if col is not None:
            entities = [e for e in entities if e.col == col]
        if viewer_id is not None:
            viewer = self.store.entities.get(viewer_id)
            see_all = bool(viewer and viewer.attrs.get(ATTR_SEE_INVISIBLE))
            if not see_all:
                entities = [
                    e
                    for e in entities
                    if e.id == viewer_id or not e.attrs.get(ATTR_INVISIBLE)
                ]
        return entities

    def get_map(self, map_id: str) -> Any | None:
        return self.store.maps.get(map_id)

    def list_maps(self) -> list:
        return list(self.store.maps.values())

    def map_visible_to(
        self, map_id: str, entity_id: str | None, tier: str = ""
    ) -> bool:
        """地图对某身份的可见性（G1）。

        public 全可见；private 仅该图上有自己身份化实体的玩家可见
        （"在场即可见"，零名单概念）+ admin 全见。
        """
        m = self.store.maps.get(map_id)
        if m is None:
            return False
        if tier == "admin" or m.visible == "public":
            return True
        if not entity_id:
            return False
        entity = self.store.entities.get(entity_id)
        return entity is not None and entity.map_id == map_id

    def get_location(self, map_id: str, row: int, col: int) -> Any | None:
        return self.store.loc_by_pos.get((map_id, row, col))

    def list_locations(self) -> list:
        return list(self.store.loc_by_pos.values())

    # ---------- 世界与组织（D15，只读免锁） ----------

    def get_world(self, world_id: str) -> World | None:
        return self.store.worlds.get(world_id)

    def list_worlds(self) -> list[World]:
        return list(self.store.worlds.values())

    def map_world(self, map_id: str) -> str | None:
        """地图所属世界 id（未归属返回 None）。"""
        return self.store.map_world.get(map_id)

    def entity_world(self, entity_id: str) -> str | None:
        """实体所在世界 id（经地图归属推导；实体不存在返回 None）。"""
        entity = self.store.entities.get(entity_id)
        if entity is None:
            return None
        return self.store.map_world.get(entity.map_id)

    def list_folders(self, world_id: str) -> list[WorldFolder]:
        return self.store.list_folders(world_id)

    def list_maps_by_folder(
        self, world_id: str, folder_id: str | None = None
    ) -> list[str]:
        """世界内某组织节点下的地图 id（folder_id=None = 世界根）。"""
        return self.store.list_maps_by_folder(world_id, folder_id)

    def list_world_maps(self, world_id: str) -> list[str]:
        """世界内全部地图 id（含各组织节点下）。"""
        return [
            map_id for map_id, wid in self.store.map_world.items() if wid == world_id
        ]

    # ---------- 世界与组织（写，锁内） ----------

    async def create_world(
        self,
        world_id: str,
        name: str,
        *,
        desc: str = "",
        play_ids: list[str] | None = None,
    ) -> World:
        """新建世界（D15：id = 玩法包激活集合配置边界）。"""
        async with self._lock:
            world_id = _clean_required(world_id, "世界 id")
            name = _clean_required(name, "世界名称")
            try:
                return await self.store.create_world(
                    world_id, name, desc=desc, play_ids=play_ids
                )
            except ValueError as e:
                raise WorldError(str(e)) from None

    async def update_world(
        self,
        world_id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        play_ids: list[str] | None = None,
    ) -> World:
        """更新世界（名称/描述/激活玩法包集合；None = 不变）。"""
        async with self._lock:
            if name is not None:
                name = _clean_required(name, "世界名称")
            try:
                return await self.store.update_world(
                    world_id, name=name, desc=desc, play_ids=play_ids
                )
            except KeyError as e:
                raise WorldError(str(e)) from None

    async def delete_world(self, world_id: str) -> None:
        """删除世界；世界仍有地图归属 → 拒绝（先移走）。"""
        async with self._lock:
            if world_id not in self.store.worlds:
                raise WorldError(f"世界不存在：{world_id}")
            if any(wid == world_id for wid in self.store.map_world.values()):
                raise WorldError("世界仍有地图归属，请先移走或删除地图")
            await self.store.delete_world(world_id)

    async def assign_map(
        self,
        map_id: str,
        world_id: str,
        *,
        folder_id: str | None = None,
        sort: int | None = None,
    ) -> None:
        """把地图归属到世界（及可选组织节点）；覆盖旧归属。

        ``sort=None``：同世界同节点内重挂保留原位，换节点排到末尾。
        """
        async with self._lock:
            try:
                await self.store.assign_map(
                    map_id, world_id, folder_id=folder_id, sort=_clean_sort(sort)
                )
            except (KeyError, ValueError) as e:
                raise WorldError(str(e)) from None

    async def unassign_map(self, map_id: str) -> None:
        """解除地图世界归属（地图本身保留）。"""
        async with self._lock:
            await self.store.unassign_map(map_id)

    async def move_map_folder(
        self, map_id: str, folder_id: str | None, *, sort: int | None = None
    ) -> None:
        """移动地图到世界内组织节点（None = 世界根）。"""
        async with self._lock:
            try:
                await self.store.move_map_folder(
                    map_id, folder_id, sort=_clean_sort(sort)
                )
            except (KeyError, ValueError) as e:
                raise WorldError(str(e)) from None

    async def move_map(
        self,
        map_id: str,
        *,
        world_id: object = _UNSET,
        folder_id: object = _UNSET,
        sort: object = _UNSET,
    ) -> None:
        """地图搬家统一入口（组织树拖拽）：世界 / 组织节点 / 序号三者可任意组合。

        ``world_id=None`` = 解除世界归属；``folder_id=None`` = 世界根。
        跨世界搬家时若只给 folder，旧 folder 必然不属于新世界 → 一并落到世界根。
        """
        async with self._lock:
            if map_id not in self.store.maps:
                raise WorldError(f"地图不存在：{map_id}")
            cur_world = self.store.map_world.get(map_id)
            target_world = cur_world if world_id is _UNSET else world_id
            target_folder = (
                self.store.map_folder.get(map_id) if folder_id is _UNSET else folder_id
            )
            if target_world is not None and target_world not in self.store.worlds:
                raise WorldError(f"世界不存在：{target_world}")
            if target_world is None:
                if target_folder is not None:
                    raise WorldError("未归属世界的地图不能放进组织节点")
                await self.store.unassign_map(map_id)
                return
            if target_world != cur_world and folder_id is _UNSET:
                target_folder = None  # 跨世界：旧组织节点不属于新世界
            try:
                await self.store.assign_map(
                    map_id,
                    str(target_world),
                    folder_id=target_folder,
                    sort=_clean_sort(sort),
                )
            except (KeyError, ValueError) as e:
                raise WorldError(str(e)) from None

    async def set_map_sort(self, map_id: str, sort: int) -> None:
        """设置地图在其组织节点内的序号。"""
        async with self._lock:
            try:
                await self.store.set_map_sort(map_id, _clean_sort(sort))
            except KeyError as e:
                raise WorldError(str(e)) from None

    async def reorder_tree(
        self, world_id: str, parent_id: str | None, items: list[dict]
    ) -> None:
        """批量重排某组织节点下的条目（文件夹与地图共用一个序号空间）。

        ``items`` 为 ``[{"type": "folder"|"map", "id": ...}]``，按给定顺序赋
        序号 0..n-1；未列出的条目排在后面并保持原有相对顺序。跨容器条目报错。
        """
        async with self._lock:
            if world_id not in self.store.worlds:
                raise WorldError(f"世界不存在：{world_id}")
            if parent_id is not None:
                parent = self.store.folders.get(parent_id)
                if parent is None or parent.world_id != world_id:
                    raise WorldError("组织节点不存在或不属于该世界")
            listed: list[tuple[str, str]] = []
            for item in items or []:
                if not isinstance(item, dict):
                    raise WorldError("排序项必须是对象")
                kind = str(item.get("type") or "")
                item_id = str(item.get("id") or "")
                if kind not in ("folder", "map") or not item_id:
                    raise WorldError("排序项需要 type（folder/map）与 id")
                if kind == "folder":
                    f = self.store.folders.get(item_id)
                    if f is None or f.world_id != world_id:
                        raise WorldError(f"文件夹不存在或不属于该世界：{item_id}")
                    if f.parent_id != parent_id:
                        raise WorldError(f"文件夹不在该组织节点下：{item_id}")
                else:
                    if self.store.map_world.get(item_id) != world_id:
                        raise WorldError(f"地图不存在或不属于该世界：{item_id}")
                    if self.store.map_folder.get(item_id) != parent_id:
                        raise WorldError(f"地图不在该组织节点下：{item_id}")
                listed.append((kind, item_id))
            if len({i for _, i in listed}) != len(listed):
                raise WorldError("排序项有重复")
            # 未列出的条目：保持原有顺序跟在后面
            seen = {i for _, i in listed}
            rest = [
                ("folder", f.id)
                for f in self.store.list_folders(world_id)
                if f.parent_id == parent_id and f.id not in seen
            ] + [
                ("map", map_id)
                for map_id in self.store.list_maps_by_folder(world_id, parent_id)
                if map_id not in seen
            ]
            for index, (kind, item_id) in enumerate([*listed, *rest]):
                if kind == "folder":
                    await self.store.set_folder_sort(item_id, index)
                else:
                    await self.store.set_map_sort(item_id, index)

    async def create_folder(
        self,
        world_id: str,
        name: str,
        *,
        parent_id: str | None = None,
        sort: int | None = None,
    ) -> WorldFolder:
        """新建组织文件夹（parent 必须同世界；None = 世界根）。"""
        async with self._lock:
            name = _clean_required(name, "文件夹名称")
            try:
                return await self.store.create_folder(
                    world_id, name, parent_id=parent_id, sort=_clean_sort(sort)
                )
            except (KeyError, ValueError) as e:
                raise WorldError(str(e)) from None

    async def rename_folder(self, folder_id: str, name: str) -> None:
        async with self._lock:
            name = _clean_required(name, "文件夹名称")
            try:
                await self.store.rename_folder(folder_id, name)
            except KeyError as e:
                raise WorldError(str(e)) from None

    async def set_folder_sort(self, folder_id: str, sort: int) -> None:
        """设置文件夹在其父节点内的序号。"""
        async with self._lock:
            try:
                await self.store.set_folder_sort(folder_id, _clean_sort(sort))
            except KeyError as e:
                raise WorldError(str(e)) from None

    async def move_folder(
        self, folder_id: str, parent_id: str | None, *, sort: int | None = None
    ) -> None:
        """移动文件夹到新父节点（同世界；None = 世界根；防环）。"""
        async with self._lock:
            try:
                await self.store.move_folder(
                    folder_id, parent_id, sort=_clean_sort(sort)
                )
            except (KeyError, ValueError) as e:
                raise WorldError(str(e)) from None

    async def delete_folder(self, folder_id: str) -> None:
        """删除组织文件夹；非空（子文件夹/地图）→ 拒绝。"""
        async with self._lock:
            if folder_id not in self.store.folders:
                raise WorldError(f"文件夹不存在：{folder_id}")
            if any(f.parent_id == folder_id for f in self.store.folders.values()):
                raise WorldError("文件夹仍有子文件夹，请先移走")
            if any(fid == folder_id for fid in self.store.map_folder.values()):
                raise WorldError("文件夹仍有地图，请先移走")
            await self.store.delete_folder(folder_id)

    # ---------- 物品原语 ----------

    # D8：持有（背包）全下沉玩法包——内核无 give/take/count/inventories。
    # 物品定义注册见 register_item_def（定义 = 内核注册表，玩法包可追加）。

    # ---------- 实体原语 ----------

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
        user_id: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> Entity:
        """放置实体（地图编辑内容，admin；B8）。

        kind 未注册也可放置（宽松：行为缺失而已）；name 缺省取 kind label。
        实体 id 自动生成 uuid4 hex（B5）；``user_id`` 供身份注册绑定账户
        （B13，仅身份化实体使用）；``tags`` 为实例级标签（D18，可组合出
        "玩家 + 刷怪笼"这类实体，能力见 D19）。

        Raises:
            WorldError: 目标地块不存在 / 参数非法。
        """
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            if (map_id, row, col) not in self.store.loc_by_pos:
                raise WorldError(f"地块不存在：({row}, {col})")
            kind = _clean_required(kind, "kind")
            spec = self._tag_specs.get(kind)
            if name is None or not str(name).strip():
                name = (spec.label if spec and spec.label else kind) if spec else kind
            entity = Entity(
                id=uuid.uuid4().hex,
                map_id=map_id,
                row=row,
                col=col,
                kind=kind,
                name=str(name).strip(),
                desc=str(desc or ""),
                attrs=dict(attrs or {}),
                state=dict(state or {}),
                user_id=user_id,
                last_active_ts=self._now_ts(),
                tags=parse_tags(tags),
            )
            await self.store.save_entity(entity)
            await self._emit(
                "on_world_edited",
                {"op": "place_entity", "entity_id": entity.id, "kind": kind},
            )
            return entity

    async def remove_entity(self, entity_id: str) -> None:
        """移除实体（地图编辑，admin；B8）。

        D14：身份化实体（玩家/agent）**不可**被玩法包移除——账户注销走
        ``delete_identity_entity``（身份服务受控通道）。

        Raises:
            WorldError: 实体不存在 / 身份化实体。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if entity.kind in IDENTITY_KINDS:
                raise WorldError("身份化实体（玩家/agent）不可被移除（注销走身份服务）")
            await self.store.delete_entity(entity_id)
            await self._emit("on_entity_removed", entity)
            await self._emit(
                "on_world_edited", {"op": "remove_entity", "entity_id": entity_id}
            )

    async def delete_identity_entity(self, entity_id: str) -> None:
        """（身份服务受控）删除身份化实体：账户永久注销专用，发事件。

        与 remove_entity 的区别：允许 kind=player/agent（D14 的受控豁免——
        调用方是内核身份服务，非玩法包权限）。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if entity.kind not in IDENTITY_KINDS:
                raise WorldError("只支持身份化实体")
            await self.store.delete_entity(entity_id)
            await self._emit("on_entity_removed", entity)
            await self._emit(
                "on_world_edited", {"op": "remove_entity", "entity_id": entity_id}
            )

    def identity_entity_of(self, account_id: str):
        """账户绑定的身份化实体（user_id == account_id；无则 None）。"""
        for entity in self.store.entities.values():
            if entity.user_id == account_id:
                return entity
        return None

    async def move(
        self, entity_id: str, direction: str, *, path: int | None = None
    ) -> SceneView:
        """路径移动（分派入口，D11；默认实现见 _move_default）。

        Raises:
            WorldError: 实体不存在/非身份化、方向非法、无路径、被阻挡、能力被禁用。
        """
        return await self._dispatch_primitive("move", entity_id, direction, path=path)

    async def _move_default(
        self, entity_id: str, direction: str, *, path: int | None = None
    ) -> SceneView:
        """默认路径移动（死引用剔除 + 加权抽目标；可被覆盖，D11）。"""
        async with self._lock:
            entity = self._require_entity(entity_id)
            if entity.kind not in IDENTITY_KINDS:
                raise WorldError("只有玩家/agent 实体可以按路径移动")
            direction = _check_direction(direction)
            loc = self.store.loc_by_pos.get(entity.pos_key())
            if loc is None:
                raise WorldError(f"实体不在任何地块：{entity_id}")
            slot = loc.connections.get(direction)
            usable = []
            if slot is not None and slot.enabled:
                usable = [
                    (i, p)
                    for i, p in enumerate(slot.paths)
                    if self._resolve_main(p, loc.map_id) is not None
                ]
            if not usable:
                raise WorldError("这个方向没有可走的路径")
            if path is None:
                if len(usable) > 1:
                    raise WorldError("该方向有多条路径，请指定 path 索引")
                path_obj = usable[0][1]
            else:
                if not _is_int(path):
                    raise WorldError("path 必须是整数索引")
                match = [p for i, p in usable if i == path]
                if not match:
                    raise WorldError(f"该方向的路径索引 {path} 不存在")
                path_obj = match[0]
            tgt = self._draw_target(path_obj, loc.map_id)
            blocker = self._blocker_at(tgt.map_id, tgt.row, tgt.col)
            if blocker is not None:
                raise WorldError(f"被「{blocker.name}」挡住了，无法通行")
            from_pos = entity.pos_key()
            entity.map_id, entity.row, entity.col = tgt.map_id, tgt.row, tgt.col
            entity.last_active_ts = self._now_ts()
            await self.store.save_entity(entity)
            await self._emit("on_entity_move", entity, from_pos, entity.pos_key())
            await self._emit(
                "on_entity_enter", entity, entity.map_id, entity.row, entity.col
            )
            return self._build_scene(entity)

    async def move_entity(
        self, entity_id: str, map_id: str, row: int, col: int
    ) -> None:
        """实体直接位移（分派入口，D11；默认实现见 _move_entity_default）。"""
        return await self._dispatch_primitive(
            "move_entity", entity_id, map_id, row, col
        )

    async def _move_entity_default(
        self, entity_id: str, map_id: str, row: int, col: int
    ) -> None:
        """默认直接位移（玩法包行为驱动，B8；传送语义，不做阻挡检查）。"""
        async with self._lock:
            entity = self._require_entity(entity_id)
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            if (map_id, row, col) not in self.store.loc_by_pos:
                raise WorldError(f"地块不存在：({row}, {col})")
            if entity.pos_key() == (map_id, row, col):
                return
            from_pos = entity.pos_key()
            entity.map_id, entity.row, entity.col = map_id, row, col
            entity.last_active_ts = self._now_ts()
            await self.store.save_entity(entity)
            await self._emit("on_entity_move", entity, from_pos, entity.pos_key())
            await self._emit("on_entity_enter", entity, map_id, row, col)

    async def set_attrs(self, entity_id: str, patch: dict) -> None:
        """合并写实体 attrs（玩法数据；C1 装备/格子自管）。"""
        async with self._lock:
            entity = self._require_entity(entity_id)
            if not isinstance(patch, dict):
                raise WorldError("patch 必须是对象")
            if not patch:
                return
            entity.attrs = {**entity.attrs, **patch}
            await self.store.save_entity(entity)
            await self._emit("on_entity_changed", entity, {"attrs": patch})

    def get_attrs(self, entity_id: str) -> dict:
        return dict(self._require_entity(entity_id).attrs)

    async def set_state(self, entity_id: str, patch: dict) -> None:
        """合并写实体 state（门开/关、库存、血量等玩法包自管状态）。"""
        async with self._lock:
            entity = self._require_entity(entity_id)
            if not isinstance(patch, dict):
                raise WorldError("patch 必须是对象")
            if not patch:
                return
            entity.state = {**entity.state, **patch}
            await self.store.save_entity(entity)
            await self._emit("on_entity_changed", entity, {"state": patch})

    def get_state(self, entity_id: str) -> dict:
        return dict(self._require_entity(entity_id).state)

    # ---------- 字段原语（D9：set_data/get_data，可被覆盖/禁用） ----------

    async def set_data(self, entity_id: str, name: str, value: Any) -> None:
        """字段写（分派入口；默认实现见 _set_data_default）。"""
        return await self._dispatch_primitive("set_data", entity_id, name, value)

    async def _set_data_default(self, entity_id: str, name: str, value: Any) -> None:
        """默认字段写：合并写实体玩法字段（容器 = attrs；state 走 set_state，不经分派）。"""
        name = _clean_required(name, "字段名")
        async with self._lock:
            entity = self._require_entity(entity_id)
            entity.attrs = {**entity.attrs, name: value}
            await self.store.save_entity(entity)
            await self._emit("on_entity_changed", entity, {"attrs": {name: value}})

    async def get_data(self, entity_id: str, name: str | None = None) -> Any:
        """字段读（分派入口；默认实现见 _get_data_default）。"""
        return await self._dispatch_primitive("get_data", entity_id, name)

    async def _get_data_default(self, entity_id: str, name: str | None = None) -> Any:
        """默认字段读：单字段或全量（容器 = attrs）。"""
        entity = self._require_entity(entity_id)
        if name is not None:
            name = _clean_required(name, "字段名")
            return entity.attrs.get(name)
        return dict(entity.attrs)

    # ---------- 移动辅助 ----------

    def _resolve_main(self, p: ConnectionPath, from_map_id: str) -> Target | None:
        if not p.targets:
            return None
        return self.store.resolve_target(p.targets[0], from_map_id)

    def _draw_target(self, p: ConnectionPath, from_map_id: str) -> Target:
        """路径内按权重抽目标（主目标 + 意外目标），全部不可达则报错。"""
        candidates = [
            r
            for t in p.targets
            if (r := self.store.resolve_target(t, from_map_id)) is not None
        ]
        if not candidates:
            raise WorldError("该路径的目标都不可达")
        total = sum(c.weight for c in candidates)
        r = self._rand() if self._rand is not None else random.random()
        acc = 0.0
        chosen = candidates[-1]
        for c in candidates:
            acc += c.weight
            if r * total <= acc:
                chosen = c
                break
        return chosen

    def _blocker_at(self, map_id: str, row: int, col: int) -> Entity | None:
        for e in self.store.entities.values():
            if e.pos_key() == (map_id, row, col) and self._is_blocking(e):
                return e
        return None

    def _is_blocking(self, e: Entity) -> bool:
        """阻挡判定（D19）：``state["block_move"]`` 动态覆盖优先，其次看标签并集。

        任一标签声明 block_move 即阻挡（标签写 False 想表达的是"对某些实体开放"，
        该用过滤器/state，而不是抵消别人的 True）。
        D21：声明该标签的玩法包在实体所在世界未激活 → 该标签不参与（不阻挡）。
        """
        if STATE_BLOCK_MOVE in e.state:
            return bool(e.state[STATE_BLOCK_MOVE])
        return any(spec.block_move for spec in self._active_specs(e))

    def _build_scene(self, entity: Entity) -> SceneView:
        loc = self.store.loc_by_pos.get(entity.pos_key())
        if loc is None:
            raise WorldError(f"实体不在任何地块：{entity.id}")
        m = self.store.maps.get(loc.map_id)
        now = self._now_for(m)
        rand = self._rand
        description = loc.description.resolve(now, rand) if loc.description else ""
        paths: list[ScenePath] = []
        for d in DIRECTIONS:
            slot = loc.connections.get(d)
            if slot is None or not slot.enabled:
                continue
            for idx, p in enumerate(slot.paths):
                main = self._resolve_main(p, loc.map_id)
                if main is None:
                    continue  # 死引用：主目标不可解析 → 整条路径不展示
                label = p.label.resolve(now, rand) if p.label else ""
                target_name = None
                if p.reveal_target:
                    target = self.store.loc_by_pos.get(
                        (main.map_id, main.row, main.col)
                    )
                    target_name = target.name if target else None
                paths.append(
                    ScenePath(
                        direction=d,
                        path_index=idx,
                        label=label,
                        reveal_target=p.reveal_target,
                        target_name=target_name,
                    )
                )
        return SceneView(
            player_id=entity.id,
            map_id=loc.map_id,
            row=loc.row,
            col=loc.col,
            location=loc,
            description=description,
            paths=paths,
        )

    # ---------- 交互（WebUI / MCP 的公共入口，A1） ----------

    async def interact(
        self,
        entity_id: str,
        target_id: str,
        action: str,
        args: dict | None = None,
        item_id: str | None = None,
    ) -> InteractionResult:
        """交互通道（分派入口，D11/D12；默认实现见 _interact_default）。"""
        return await self._dispatch_primitive(
            "interact", entity_id, target_id, action, args, item_id
        )

    async def _interact_default(
        self,
        entity_id: str,
        target_id: str,
        action: str,
        args: dict | None = None,
        item_id: str | None = None,
    ) -> InteractionResult:
        """默认交互：校验可用动作（C3）→ 玩法包 handler → 返回结果。

        交互 handler 异常会被隔离并转为可展示的 WorldError（不拖垮内核）。

        Raises:
            WorldError: 实体/目标不存在、动作不可用或未实现、handler 出错。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            target = self._require_entity(target_id)
            action = _clean_required(action, "动作")
            if action not in self._interactions:
                declared = {
                    a for spec in self._active_specs(target) for a in spec.interactions
                }
                if action not in declared:
                    raise WorldError(f"「{target.name}」没有「{action}」这个动作")
                raise WorldError(f"动作「{action}」尚未实现")
            binding = self._interactions[action]
            # 世界激活过滤（D15）：动作注册包在目标世界未激活 → 动作不可用
            if not self._world_play_active(
                self.store.map_world.get(target.map_id), binding.play_id
            ):
                raise WorldError(f"「{target.name}」没有「{action}」这个动作")
            req = InteractionRequest(
                entity_id=entity_id,
                target=target,
                action=action,
                args=dict(args or {}),
                item_id=item_id,
            )
            api = self._play_apis.get(binding.play_id)
            try:
                result = await self._invoke(binding.handler, api, req)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worlditor] 交互 handler 异常：%s (%s)", action, binding.play_id
                )
                raise WorldError("交互执行出错，请稍后再试") from None
            if not isinstance(result, InteractionResult):
                raise WorldError("交互返回结果格式错误")
            # G18：ui_hook 注入——交互弹窗渲染前服务端展开（WebUI 零改动；
            # 注入块随 on_interact 事件同步进 SSE payload）
            if result.ui is not None:
                result.ui = await self.apply_ui_hooks(result.ui, entity_id=entity_id)
            await self._emit("on_interact", req, result)
            if item_id is not None:
                await self._emit("on_item_used", entity, item_id, req.args, result)
            return result

    def available_actions(self, target_id: str) -> list[str]:
        """实体可用动作（C3：标签声明并集 ∪ 全局注册表；未实现的声明剔除）。

        D19：声明 = **全部有效标签的并集**（"玩家 + 刷怪笼"能同时看到两边的动作）。
        D21：动作提供方在**目标所在世界**未激活 → 不出现在可用动作里
        （与 engine.interact 的拒绝判定同源，避免"菜单里有、点了说没有"）。
        """
        target = self.store.entities.get(target_id)
        if target is None:
            raise WorldError(f"实体不存在：{target_id}")
        declared = {a for spec in self._active_specs(target) for a in spec.interactions}
        world_id = self.store.map_world.get(target.map_id)
        return sorted(
            a
            for a in (declared | set(self._interactions))
            if a in self._interactions
            and self._world_play_active(world_id, self._interactions[a].play_id)
        )

    def list_actions(self, target_id: str) -> list[MenuButton]:
        """实体可用动作按钮（UI 菜单生成用）。"""
        return [
            MenuButton(label=self._interactions[a].label, action=a)
            for a in self.available_actions(target_id)
        ]

    # ---------- 地图编辑（B8：地块/地图/实体编辑原语，admin 端点转发） ----------

    async def create_location(
        self,
        map_id: str,
        row: int,
        col: int,
        name: str,
        *,
        description: object = None,
    ) -> Any:
        """新建地块（重复坐标 / 空名称报错）。"""
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            if (map_id, row, col) in self.store.loc_by_pos:
                raise WorldError(f"地块已存在：({row}, {col})")
            name = _clean_required(name, "地块名称")
            desc = parse_text_schedule(description) if description is not None else None
            loc = parse_location(
                {
                    "map_id": map_id,
                    "row": row,
                    "col": col,
                    "name": name,
                    "description": desc.to_dict() if desc else None,
                    "connections": {
                        d: {"direction": d, "enabled": False, "paths": []}
                        for d in DIRECTIONS
                    },
                }
            )
            await self.store.save_location(loc)
            await self._emit(
                "on_world_edited", {"op": "create_location", "pos": [map_id, row, col]}
            )
            return loc

    async def update_location(
        self,
        map_id: str,
        row: int,
        col: int,
        *,
        name: object = _UNSET,
        description: object = _UNSET,
    ) -> Any:
        """更新地块名称 / 描述（坐标只读；``description=None`` 显式清空）。"""
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            loc = self.store.loc_by_pos.get((map_id, row, col))
            if loc is None:
                raise WorldError(f"地块不存在：({row}, {col})")
            if name is not _UNSET:
                loc.name = _clean_required(name, "地块名称")
            if description is not _UNSET:
                loc.description = (
                    None if description is None else parse_text_schedule(description)
                )
            await self.store.save_location(loc)
            await self._emit(
                "on_world_edited", {"op": "update_location", "pos": [map_id, row, col]}
            )
            return loc

    async def move_location(
        self, map_id: str, row: int, col: int, to_row: int, to_col: int
    ) -> Any:
        """移动地块：原子重写自身坐标 + 全图指向旧坐标的连接目标 + 实体位置。"""
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            _check_pos(to_row, to_col)
            src = (map_id, row, col)
            dst = (map_id, to_row, to_col)
            if src not in self.store.loc_by_pos:
                raise WorldError(f"地块不存在：({row}, {col})")
            if dst in self.store.loc_by_pos:
                raise WorldError(f"目标格 ({to_row}, {to_col}) 已被占用")
            # 1. 全图引用重写（含自身自环）：指向旧坐标 → 新坐标
            for other in list(self.store.loc_by_pos.values()):
                changed = False
                for slot in other.connections.values():
                    for p in slot.paths:
                        new_targets = []
                        for t in p.targets:
                            if self._target_key(t, other.map_id) == src:
                                new_targets.append(
                                    Target(
                                        map_id=t.map_id,
                                        row=to_row,
                                        col=to_col,
                                        weight=t.weight,
                                    )
                                )
                                changed = True
                            else:
                                new_targets.append(t)
                        p.targets = new_targets
                if changed:
                    await self.store.save_location(other)
            # 2. 自身坐标迁移
            loc = self.store.loc_by_pos.pop(src)
            loc = replace(loc, row=to_row, col=to_col)
            self.store.loc_by_pos[dst] = loc
            await self.store.save_location(loc)
            # 3. 地块上的实体位置
            for e in self.store.entities.values():
                if e.pos_key() == src:
                    e.map_id, e.row, e.col = map_id, to_row, to_col
                    await self.store.save_entity(e)
            await self._emit(
                "on_world_edited",
                {"op": "move_location", "from": list(src), "to": list(dst)},
            )
            return loc

    async def update_connection(
        self,
        map_id: str,
        row: int,
        col: int,
        direction: str,
        *,
        enabled: object = _UNSET,
        paths: object = _UNSET,
    ) -> Any:
        """更新地块某方向槽位（``paths`` 整体替换，v3 结构）。"""
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            loc = self.store.loc_by_pos.get((map_id, row, col))
            if loc is None:
                raise WorldError(f"地块不存在：({row}, {col})")
            direction = _check_direction(direction)
            slot = loc.connections[direction]
            if enabled is not _UNSET:
                if not isinstance(enabled, bool):
                    raise WorldError("enabled 必须是布尔值")
                slot.enabled = enabled
            if paths is not _UNSET:
                if not isinstance(paths, list):
                    raise WorldError("paths 必须是数组")
                slot.paths = [parse_path(p) for p in paths]
            await self.store.save_location(loc)
            await self._emit(
                "on_world_edited",
                {
                    "op": "update_connection",
                    "pos": [map_id, row, col],
                    "direction": direction,
                },
            )
            return loc

    async def update_entity(
        self,
        entity_id: str,
        *,
        name: object = _UNSET,
        desc: object = _UNSET,
        attrs: object = _UNSET,
        state: object = _UNSET,
        tags: object = _UNSET,
        kind: object = _UNSET,
    ) -> Entity:
        """更新实体字段（admin 编辑；attrs/state/tags 整体替换）。

        类型（基底 kind）可改，但**身份化实体的类型由身份服务管理**（D20）——
        编辑器不能把玩家改成别的东西，也不能把别的东西改成玩家。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if kind is not _UNSET:
                new_kind = _clean_required(kind, "类型")
                if entity.kind in IDENTITY_KINDS and new_kind != entity.kind:
                    raise WorldError(
                        "身份化实体的类型由身份服务管理（D20），不能在编辑器里改"
                    )
                entity.kind = new_kind
            if name is not _UNSET:
                entity.name = _clean_required(name, "名称")
            if desc is not _UNSET:
                entity.desc = str(desc or "")
            if attrs is not _UNSET:
                if not isinstance(attrs, dict):
                    raise WorldError("attrs 必须是对象")
                entity.attrs = dict(attrs)
            if state is not _UNSET:
                if not isinstance(state, dict):
                    raise WorldError("state 必须是对象")
                entity.state = dict(state)
            if tags is not _UNSET:
                if tags is not None and not isinstance(tags, (list, tuple)):
                    raise WorldError("tags 必须是标签数组")
                entity.tags = parse_tags(tags)
            await self.store.save_entity(entity)
            await self._emit("on_entity_changed", entity, {"edited": True})
            return entity

    async def create_map(
        self,
        map_id: str,
        name: str,
        *,
        description: str | None = None,
        timezone: str | None = None,
        spawn_row: int = 0,
        spawn_col: int = 0,
        visible: str = "public",
    ) -> WorldMap:
        """新建地图（id 唯一；visible = public/private，G1 可见性）。"""
        async with self._lock:
            map_id = _clean_required(map_id, "地图 id")
            name = _clean_required(name, "地图名称")
            if map_id in self.store.maps:
                raise WorldError(f"地图已存在：{map_id}")
            if visible not in ("public", "private"):
                raise WorldError("visible 必须是 public 或 private")
            _check_pos(spawn_row, spawn_col)
            m = parse_map(
                {
                    "id": map_id,
                    "name": name,
                    "description": parse_text_schedule(description).to_dict()
                    if description
                    else None,
                    "timezone": timezone,
                    "spawn_row": spawn_row,
                    "spawn_col": spawn_col,
                    "visible": visible,
                }
            )
            await self.store.save_map(m)
            await self._emit("on_world_edited", {"op": "create_map", "map_id": map_id})
            return m

    async def delete_map(self, map_id: str) -> None:
        """删除地图（G2：级联地块/实体/世界归属；图上身份化实体在场 → 拒绝）。

        Raises:
            WorldError: 地图不存在 / 图上仍有玩家/agent 实体。
        """
        async with self._lock:
            map_id = _clean_required(map_id, "地图 id")
            if map_id not in self.store.maps:
                raise WorldError(f"地图不存在：{map_id}")
            for e in self.store.entities.values():
                if e.map_id == map_id and e.kind in IDENTITY_KINDS:
                    raise WorldError("地图上仍有玩家/agent 实体，无法删除")
            await self.store.delete_map(map_id)
            await self._emit("on_world_edited", {"op": "delete_map", "map_id": map_id})

    async def copy_map(
        self,
        map_id: str,
        new_map_id: str,
        *,
        name: str | None = None,
        world_id: object = _UNSET,
        folder_id: object = _UNSET,
        with_entities: bool = False,
    ) -> WorldMap:
        """复制地图（地块 / 描述 / 连接全量另存为新地图；实体可选带过去）。

        语义：
        - 同图目标（``map_id`` 空或等于源地图）→ 重写为"新地图自己"，副本内自洽；
        - 跨图目标（显式指向别的地图）→ 原样保留（那是作者写的跨图连线）；
        - 身份化实体（玩家）**不复制**——人是人，不是布景；
        - 归属默认跟随源地图（同世界同组织节点，排到该节点末尾）。
        """
        async with self._lock:
            src = self.store.maps.get(map_id)
            if src is None:
                raise WorldError(f"地图不存在：{map_id}")
            new_map_id = _clean_required(new_map_id, "地图 id")
            if new_map_id in self.store.maps:
                raise WorldError(f"地图已存在：{new_map_id}")
            new_name = (
                _clean_required(name, "地图名称")
                if name is not None
                else f"{src.name}（副本）"
            )
            dup = parse_map(
                {
                    "id": new_map_id,
                    "name": new_name,
                    "description": src.description.to_dict()
                    if src.description
                    else None,
                    "timezone": src.timezone,
                    "spawn_row": src.spawn_row,
                    "spawn_col": src.spawn_col,
                    "visible": src.visible,
                }
            )
            await self.store.save_map(dup)
            cloned_locs = []
            for loc in [
                x for x in self.store.loc_by_pos.values() if x.map_id == map_id
            ]:
                cloned = parse_location(location_to_dict(loc))
                cloned.map_id = new_map_id
                for slot in cloned.connections.values():
                    for path in slot.paths:
                        for t in path.targets:
                            if t.map_id in ("", map_id):
                                t.map_id = ""  # 同图目标 → 落到副本自己
                cloned_locs.append(cloned)
            # 批量单事务写：复制是引擎锁内的大批量路径，逐行提交会卡住整个世界
            await self.store.save_locations(cloned_locs)
            if with_entities:
                cloned_entities = []
                for e in list(self.store.entities.values()):
                    if e.map_id != map_id or e.kind in IDENTITY_KINDS:
                        continue
                    cloned_entities.append(
                        Entity(
                            id=uuid.uuid4().hex,
                            map_id=new_map_id,
                            row=e.row,
                            col=e.col,
                            kind=e.kind,
                            name=e.name,
                            desc=e.desc,
                            attrs=copy.deepcopy(e.attrs),
                            state=copy.deepcopy(e.state),
                            last_active_ts=0.0,
                        )
                    )
                await self.store.save_entities(cloned_entities)
            # 归属：默认与源地图同世界同节点
            target_world = (
                self.store.map_world.get(map_id) if world_id is _UNSET else world_id
            )
            if target_world is not None:
                target_folder = (
                    self.store.map_folder.get(map_id)
                    if folder_id is _UNSET
                    else folder_id
                )
                try:
                    await self.store.assign_map(
                        new_map_id, str(target_world), folder_id=target_folder
                    )
                except (KeyError, ValueError) as e:
                    raise WorldError(str(e)) from None
            await self._emit(
                "on_world_edited",
                {"op": "copy_map", "map_id": new_map_id, "from": map_id},
            )
            return dup

    # ---------- 地图体检（纯数据检查，无玩法语义；管理端治理视图数据源） ----------

    def lint_map(self, map_id: str) -> dict[str, Any]:
        """单张地图体检：死连接 / 出生点落空 / 实体悬空 / 孤立地块 / 无世界归属。

        只报"作者看不出来、但运行时有后果"的问题——运行时对死引用是**静默剔除**，
        所以体检是唯一能提前告知的通道。
        """
        m = self.store.maps.get(map_id)
        if m is None:
            raise WorldError(f"地图不存在：{map_id}")
        problems: list[dict] = []

        def add(level: str, code: str, text: str, **where: Any) -> None:
            problems.append(
                {"level": level, "code": code, "text": text, "where": where}
            )

        locs = [x for x in self.store.loc_by_pos.values() if x.map_id == map_id]
        entities = [e for e in self.store.entities.values() if e.map_id == map_id]
        has_incoming: set[tuple[str, int, int]] = set()
        out_count: dict[tuple[str, int, int], int] = {}
        for loc in locs:
            usable_exits = 0
            for direction in DIRECTIONS:
                slot = loc.connections.get(direction)
                if slot is None or not slot.enabled:
                    continue
                for index, path in enumerate(slot.paths):
                    main = self._resolve_main(path, loc.map_id)
                    if main is None:
                        head = path.targets[0] if path.targets else None
                        target_txt = (
                            f"{head.map_id or loc.map_id} ({head.row}, {head.col})"
                            if head is not None
                            else "（空路径）"
                        )
                        add(
                            "error",
                            "dead_target",
                            f"({loc.row}, {loc.col})「{loc.name}」{direction} 第 "
                            f"{index + 1} 条路径的主目标 {target_txt} 不存在，"
                            "运行时整条路径不展示",
                            map_id=map_id,
                            row=loc.row,
                            col=loc.col,
                            direction=direction,
                            path=index,
                        )
                        continue
                    usable_exits += 1
                    has_incoming.add((main.map_id, main.row, main.col))
                    for alt in path.targets[1:]:
                        if self.store.resolve_target(alt, loc.map_id) is None:
                            add(
                                "warn",
                                "dead_alt_target",
                                f"({loc.row}, {loc.col})「{loc.name}」{direction} 第 "
                                f"{index + 1} 条路径的意外目标 "
                                f"{alt.map_id or loc.map_id} ({alt.row}, {alt.col}) "
                                "不存在，抽取时会被跳过",
                                map_id=map_id,
                                row=loc.row,
                                col=loc.col,
                                direction=direction,
                                path=index,
                            )
            out_count[(map_id, loc.row, loc.col)] = usable_exits

        for loc in locs:
            key = (map_id, loc.row, loc.col)
            if out_count.get(key, 0) == 0 and key not in has_incoming:
                add(
                    "warn" if len(locs) == 1 else "error",
                    "isolated_location",
                    f"({loc.row}, {loc.col})「{loc.name}」既没有出口也没有入口，"
                    "玩家到不了、也出不去",
                    map_id=map_id,
                    row=loc.row,
                    col=loc.col,
                )
            elif out_count.get(key, 0) == 0:
                add(
                    "warn",
                    "no_exit",
                    f"({loc.row}, {loc.col})「{loc.name}」没有任何可用出口（死胡同）",
                    map_id=map_id,
                    row=loc.row,
                    col=loc.col,
                )
            elif key not in has_incoming:
                add(
                    "warn",
                    "no_entry",
                    f"({loc.row}, {loc.col})「{loc.name}」没有任何路径指向它（只能作为起点）",
                    map_id=map_id,
                    row=loc.row,
                    col=loc.col,
                )

        if not locs:
            add("warn", "empty_map", f"地图「{m.name}」还没有任何地块", map_id=map_id)
        elif (map_id, m.spawn_row, m.spawn_col) not in self.store.loc_by_pos:
            add(
                "error",
                "spawn_missing",
                f"出生点 ({m.spawn_row}, {m.spawn_col}) 没有地块，新玩家会落空",
                map_id=map_id,
                row=m.spawn_row,
                col=m.spawn_col,
            )

        for e in entities:
            if e.pos_key() not in self.store.loc_by_pos:
                add(
                    "error",
                    "dangling_entity",
                    f"实体「{e.name}」（{e.kind}）在 ({e.row}, {e.col}) 但那里没有地块",
                    map_id=map_id,
                    row=e.row,
                    col=e.col,
                    entity_id=e.id,
                )

        if map_id not in self.store.map_world:
            add(
                "warn",
                "no_world",
                "这张地图未归属任何世界——运行时按默认世界的玩法包启停生效",
                map_id=map_id,
            )

        errors = sum(1 for p in problems if p["level"] == "error")
        warns = sum(1 for p in problems if p["level"] == "warn")
        return {
            "map_id": map_id,
            "name": m.name,
            "world_id": self.store.map_world.get(map_id),
            "folder_id": self.store.map_folder.get(map_id),
            "location_count": len(locs),
            "entity_count": len(entities),
            "counts": {"error": errors, "warn": warns},
            "problems": problems,
        }

    def lint_maps(self, map_ids: list[str] | None = None) -> dict[str, Any]:
        """地图总检（全部或指定地图）；按错误数降序，方便治理视图先看要紧的。"""
        targets = list(map_ids) if map_ids is not None else list(self.store.maps.keys())
        results = [
            self.lint_map(map_id) for map_id in targets if map_id in self.store.maps
        ]
        results.sort(
            key=lambda r: (-r["counts"]["error"], -r["counts"]["warn"], r["map_id"])
        )
        return {
            "maps": results,
            "counts": {
                "maps": len(results),
                "error": sum(r["counts"]["error"] for r in results),
                "warn": sum(r["counts"]["warn"] for r in results),
            },
        }

    async def save_template(self, template: WorldTemplate) -> None:
        """写回 / 新建模板（地图编辑；D14 玩法包可调；D22 用 scope 区分地块/实体）。"""
        async with self._lock:
            if not isinstance(template.id, str) or not template.id.strip():
                raise WorldError("模板 id 不能为空")
            if not isinstance(template.name, str) or not template.name.strip():
                raise WorldError("模板名称不能为空")
            if template.scope not in TEMPLATE_SCOPES:
                raise WorldError(f"模板 scope 必须是 {'/'.join(TEMPLATE_SCOPES)}")
            if template.scope == "location":
                template.data = _location_template_payload(template.data)
            else:
                template.data = _entity_template_payload(template.data)
            await self.store.save_template(template)
            await self._emit(
                "on_world_edited",
                {"op": "save_template", "template_id": template.id},
            )

    async def delete_template(self, template_id: str) -> None:
        """删除模板（地图编辑；D14 玩法包可调）。"""
        async with self._lock:
            template_id = _clean_required(template_id, "模板 id")
            if template_id not in self.store.templates:
                raise WorldError(f"模板不存在：{template_id}")
            await self.store.delete_template(template_id)
            await self._emit(
                "on_world_edited",
                {"op": "delete_template", "template_id": template_id},
            )

    def list_templates(self, scope: str | None = None) -> list[dict]:
        """模板清单（D22）：玩法包注册（内存）+ 管理端本地（落库）合并。

        同名 id 时**本地模板优先**（管理员显式存的那份算覆盖）；scope 过滤。
        """
        out: dict[str, dict] = {}
        for entry in self._play_templates.values():
            if scope is not None and entry["scope"] != scope:
                continue
            out[entry["id"]] = dict(entry)
        for t in self.store.templates.values():
            if scope is not None and t.scope != scope:
                continue
            row = t.to_dict()
            row["source"] = "local"
            out[t.id] = row
        return sorted(out.values(), key=lambda t: (t["scope"], t["name"], t["id"]))

    def register_entity_template(
        self,
        template_id: str,
        name: str,
        data: dict,
        *,
        play_id: str = "",
        label: str = "",
    ) -> None:
        """注册玩法包自带的**实体模板**（D22：内存注册表，随包卸载消失）。

        data 形如 ``{kind, tags[], name, desc, attrs, state}``——套用即"照这个建一个
        实体"，建完仍可改。管理端本地模板落库、与这里合并成一个选择列表。
        """
        template_id = _clean_required(template_id, "模板 id")
        name = _clean_required(name, "模板名称")
        self._play_templates[template_id] = {
            "id": template_id,
            "name": name,
            "label": str(label or ""),
            "scope": "entity",
            "data": _entity_template_payload(data),
            "source": "play",
            "play_id": play_id,
        }

    async def apply_location_template(
        self, template_id: str, map_id: str, row: int, col: int
    ) -> Any:
        """套用地块模板（D22）：把模板地块复制到 (row, col)。

        目标语义（模型注释里早就写好、一直没实现）：
        - **同图目标**（存的是 ``{dr, dc}`` 相对偏移）→ 按放置位置平移；
        - **跨图目标**（存 ``{map_id, row, col}``）→ 原样复制；
        - 目标坐标处已有地块 → 拒绝（不覆盖用户内容）。
        """
        async with self._lock:
            template = self._find_template(template_id, "location")
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            if (map_id, row, col) in self.store.loc_by_pos:
                raise WorldError(f"目标格 ({row}, {col}) 已有地块，请换个位置")
            loc = _location_from_template(template["data"], map_id, row, col)
            await self.store.save_location(loc)
            await self._emit(
                "on_world_edited",
                {
                    "op": "apply_template",
                    "template_id": template_id,
                    "pos": [map_id, row, col],
                },
            )
            return loc

    def _find_template(self, template_id: str, scope: str) -> dict:
        template_id = _clean_required(template_id, "模板 id")
        for entry in self.list_templates(scope):
            if entry["id"] == template_id:
                return entry
        raise WorldError(f"模板不存在：{template_id}")

    async def update_map(
        self,
        map_id: str,
        *,
        name: object = _UNSET,
        description: object = _UNSET,
        timezone: object = _UNSET,
        spawn_row: object = _UNSET,
        spawn_col: object = _UNSET,
        visible: object = _UNSET,
    ) -> WorldMap:
        """更新地图属性（``timezone=None`` 显式清空为本地时区；visible 见 G1）。"""
        async with self._lock:
            m = self.store.maps.get(map_id)
            if m is None:
                raise WorldError(f"地图不存在：{map_id}")
            if name is not _UNSET:
                m.name = _clean_required(name, "地图名称")
            if description is not _UNSET:
                m.description = (
                    None if description is None else parse_text_schedule(description)
                )
            if timezone is not _UNSET:
                m.timezone = (
                    None
                    if timezone is None
                    else str(timezone)
                    if str(timezone).strip()
                    else None
                )
            if spawn_row is not _UNSET or spawn_col is not _UNSET:
                sr = m.spawn_row if spawn_row is _UNSET else spawn_row
                sc = m.spawn_col if spawn_col is _UNSET else spawn_col
                _check_pos(sr, sc)
                m.spawn_row, m.spawn_col = sr, sc
            if visible is not _UNSET:
                if visible not in ("public", "private"):
                    raise WorldError("visible 必须是 public 或 private")
                m.visible = visible
            await self.store.save_map(m)
            await self._emit("on_world_edited", {"op": "update_map", "map_id": map_id})
            return m

    # ---------- 地图编辑（B8：删除地块级联删除其上实体） ----------

    async def delete_location(self, map_id: str, row: int, col: int) -> None:
        """删除地块：级联清除全图指向它的连接目标 + 删除其上实体（B8）。

        拒绝删除有身份化实体占据的地块（玩家/agent 在场）。

        Raises:
            WorldError: 地块不存在 / 有身份化实体在场。
        """
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            key = (map_id, row, col)
            if key not in self.store.loc_by_pos:
                raise WorldError(f"地块不存在：({row}, {col})")
            for e in self.store.entities.values():
                if e.pos_key() == key and e.kind in IDENTITY_KINDS:
                    raise WorldError(f"有玩家「{e.name}」位于该地块，无法删除")
            await self._clear_targets_to(key)
            await self.store.delete_location(map_id, row, col)
            for e in list(self.store.entities.values()):
                if e.pos_key() == key:
                    await self.store.delete_entity(e.id)
                    await self._emit("on_entity_removed", e)
            await self._emit(
                "on_world_edited", {"op": "delete_location", "pos": list(key)}
            )

    async def _clear_targets_to(self, key: tuple[str, int, int]) -> None:
        """重写全图：删除指向 ``key`` 的目标（主目标 → 整条路径移除，v3 语义）。"""
        for loc in list(self.store.loc_by_pos.values()):
            changed = False
            for slot in loc.connections.values():
                new_paths: list[ConnectionPath] = []
                for p in slot.paths:
                    main = self._resolve_main(p, loc.map_id)
                    if main is not None and (main.map_id, main.row, main.col) == key:
                        changed = True
                        continue  # 主目标被删 → 整条路径移除
                    kept = [
                        t for t in p.targets if self._target_key(t, loc.map_id) != key
                    ]
                    if len(kept) != len(p.targets):
                        changed = True
                    new_paths.append(
                        ConnectionPath(
                            label=p.label, reveal_target=p.reveal_target, targets=kept
                        )
                    )
                slot.paths = new_paths
            if changed:
                await self.store.save_location(loc)

    def _target_key(self, t: Target, from_map_id: str) -> tuple[str, int, int]:
        return (t.map_id or from_map_id, t.row, t.col)

    # ---------- 玩法数据 KV（play_data 表） ----------

    def kv_get(self, namespace: str, key: str, default: Any = None) -> Any:
        return self.store.play_data.get((namespace, key), default)

    async def kv_set(self, namespace: str, key: str, value: Any) -> None:
        async with self._lock:
            await self.store.set_play_kv(namespace, key, value)

    async def list_world_log(self, limit: int = 100) -> list[dict]:
        """读取世界日志（最新在前；social 日志视图数据源）。"""
        return await self.store.list_world_log(limit)
