"""世界引擎：世界底子的核心动作（协议无关，见 DESIGN.md）。

设计要点：
- **实体统一模型**：玩家/布景实体都是 ``Entity``（entities 表）；
  玩家实体 = 带 ``core:account`` 的普通实体（可认证绑定、位置持久化）——**D42 起没有"身份"这个概念**。
- **物品**：**不在内核**（v2 / D37 取代 D8）——定义与持有都下沉玩法包；
  物品类型用组件声明表达，实例用"实体 + 组件"。见 model.py 顶部说明。
- **交互**：handler 命令式调用内核原语（D12，无 effects 清单）。
- **事件总线**：单一事件源（8 事件），玩法包订阅 + world_log 历史；
  SSE 是事件总线的序列化出口。
- **注册表**：component / interaction / event / ui 组件与钩子，玩法包扩展入口。
- **on_tick 调度**（A3）：单循环按 1s 粒度检查，各 handler 各自间隔，
  串行执行 + 异常隔离。

并发模型：实例级**可重入**异步锁（AsyncRLock）——原语分派（override /
过滤器链 / 默认实现）与玩法包 handler（交互 / 事件 / tick / MCP 工具）均在
锁内执行；handler 内再调 API 原语必须重入（普通 asyncio.Lock 会自锁死锁），
多段「读-判-写」原子（DESIGN §2.4 并发模型）。
时钟与 PRNG 注入（``clock`` / ``rand``），保证时间感知描述与加权抽取可测。

分区地图（**按名字定位，不记行号**——行号随演化漂移，交给 grep/编辑器跳转）：
- 注册表区（kind / 字段 / 工具 / 视图 / 服务 / 原语分派 / 交互 / 事件 / UI / 清理）
- 事件总线区（emit / SSE 推送 / tick 循环）
- 只读查询（实体 / 地图 / 世界 / 组织）
- 世界组织 CRUD（worlds / folders / 归属）
- 实体原语（place / remove / 账户注销的受控删除）
- 移动区（move / move_entity / 默认实现）——**无阻挡检查**（v2/D34 已整体移除）
- 组件与字段区（components / 组件原语 / set·get·remove_data / 内核协议受控入口）
- 场景构建（路径解析 / SceneView）
- 交互区（interact / 可用动作）
- 地图编辑区（地块 / 连接 / 地图 / 模板 / 删除级联）
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .errors import WorldError
from .model import (
    ATTR_INVISIBLE,
    ATTR_SEE_INVISIBLE,
    CORE_ACCOUNT,
    CORE_INFO,
    CORE_PERCEPTION,
    CORE_POSITION,
    DEFAULT_EVENT_PHASE,
    DIRECTIONS,
    EVENT_PHASES,
    PRINCIPAL_EVENTS,
    WORLD_EVENTS,
    ConnectionPath,
    Entity,
    InteractionRequest,
    InteractionResult,
    Location,
    MenuButton,
    Principal,
    ScenePath,
    SceneView,
    ShortCircuit,
    TagSpec,
    Target,
    World,
    WorldFolder,
    WorldMap,
    WorldTemplate,
    is_core_component,
    location_to_dict,
    parse_location,
    parse_map,
    parse_names,
    parse_path,
    parse_text_schedule,
    split_component_key,
)
from .store import DEFAULT_WORLD_ID, WorldStore

logger = logging.getLogger("worlditor")

TICK_GRANULARITY_SECONDS = 1.0
# D42：内核**没有"身份"这个概念**——D14 的红线判据是"**绑定了账户**"（`core:account`），
# 见 `Entity.is_account_bound()`。原 `IDENTITY_KINDS` 已整个删除。

# 哨兵：update 类动作用于区分「参数未提供（不变）」与「显式传 None（清空/重置）」
_UNSET = object()

# 交互 handler 签名：async def handler(api, req: InteractionRequest) -> InteractionResult
InteractionHandler = Callable[[Any, InteractionRequest], Any]
# 事件 handler 签名随事件（见 model.WORLD_EVENTS 注释）
WorldEventHandler = Callable[..., Any]
# UI 钩子 provider：async def provider(api, block: UiBlock) -> list[UiBlock]
UiHookProvider = Callable[..., Any]


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
    """一次事件订阅（play_id 用于取 API 与 namespace）。

    D27：同事件的执行顺序 = ``(phase, order, 注册序)``——阶段与序号都可声明，
    注册序只作为同键时的兜底，所以"跨包顺序"不再是包加载顺序这个隐式事实。
    """

    play_id: str
    handler: WorldEventHandler
    interval: float = 0.0  # on_tick 专用：各自间隔（A3）
    last_run: float = 0.0
    phase: str = DEFAULT_EVENT_PHASE
    order: int = 0
    seq: int = 0  # 注册序（同 phase/order 时稳定排序用）


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
    # 这个工具要不要"身体"（D46）：默认 True（老包假设 api.caller() 一定有值）。
    # 自举类工具（创建第一具化身、选角色）必须显式 False，否则永远调不到。
    requires_entity: bool = True


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
#
# v2（D32）：组件原语并行加入。**只读**的 ``get_component`` / ``list_components``
# **不进分派表**（与 query_entities 同口径，D26——查询是数据面，不是行为面）；
# 写入类（add/set/remove_component）与字段类（set/get/remove_data）一样可被
# 覆盖 / 禁用，但 **``core:`` 组件的写入绕过分派表**（D33，见 `_dispatch_component`）。
OVERRIDABLE_PRIMITIVES = frozenset(
    {
        "move",
        "move_entity",
        "set_data",
        "get_data",
        "remove_data",
        "add_component",
        "set_component",
        "remove_component",
        "interact",
    }
)

# 原语名 → 默认实现方法名（分派表兜底）
_PRIMITIVE_DEFAULT_NAMES = {
    "move": "_move_default",
    "move_entity": "_move_entity_default",
    "set_data": "_set_data_default",
    "get_data": "_get_data_default",
    "remove_data": "_remove_data_default",
    "add_component": "_add_component_default",
    "set_component": "_set_component_default",
    "remove_component": "_remove_component_default",
    "interact": "_interact_default",
}

# 原语命名参数（过滤器收到 **params；位置参数按此规范化）
_PRIMITIVE_PARAM_NAMES = {
    "move": ["entity_id", "direction", "path"],
    "move_entity": ["entity_id", "map_id", "row", "col"],
    "set_data": ["entity_id", "name", "value", "component"],
    "get_data": ["entity_id", "name", "component"],
    "remove_data": ["entity_id", "name", "component"],
    "add_component": ["entity_id", "component", "data"],
    "set_component": ["entity_id", "component", "data"],
    "remove_component": ["entity_id", "component"],
    "interact": ["entity_id", "target_id", "action", "args"],
}


def _primitive_params(name: str, args: tuple, kwargs: dict) -> dict:
    """原语位置/关键字参数 → 命名参数 dict（过滤器与默认实现共用）。"""
    names = _PRIMITIVE_PARAM_NAMES[name]
    params = dict(kwargs)
    for i, value in enumerate(args):
        if i < len(names) and names[i] not in params:
            params[names[i]] = value
    return params


# D27 事件阶段排序：input → simulate → present（未知阶段在校验处就报错）
_PHASE_RANK = {phase: i for i, phase in enumerate(EVENT_PHASES)}


def _binding_sort_key(binding: _EventBinding) -> tuple[int, int, int]:
    """事件执行顺序键（D27）：阶段 → order → 注册序。"""
    return (
        _PHASE_RANK.get(binding.phase, len(_PHASE_RANK)),
        binding.order,
        binding.seq,
    )


_FIELD_TYPES = ("str", "int", "float", "bool", "json")

# 感知字段白名单（``set_perception`` 的受控入口；见该方法的说明）
_PERCEPTION_KEYS = (ATTR_INVISIBLE, ATTR_SEE_INVISIBLE)


def _check_primitive_name(name: object) -> str:
    if not isinstance(name, str) or name not in OVERRIDABLE_PRIMITIVES:
        raise WorldError(f"原语必须是 {'/'.join(sorted(OVERRIDABLE_PRIMITIVES))} 之一")
    return name


def _clean_component(value: object) -> str:
    """组件名校验（``source:name`` 信封）——非法直接报错，不静默兜底。"""
    split_component_key(value)
    return str(value)


def _clean_component_data(component: str, data: object) -> dict:
    """单个组件的整块数据校验（``None`` = 空组件；非对象 → 报错，不静默容忍）。"""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise WorldError(f"组件 {component} 的数据必须是对象")
    return dict(data)


def _clean_components(value: object) -> dict[str, dict]:
    """整块校验组件字典（非法键 / 非对象值 → 报错，**不静默丢弃**，D23 口径）。

    与模型层 ``parse_components`` 的分工：那个用于**容错解析**（存储 / 传输），
    这个用于**API 边界校验**（管理端与玩法包传进来的东西不合法就该报错）。
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WorldError("components 必须是对象（组件名 → 数据）")
    out: dict[str, dict] = {}
    for key, data in value.items():
        component = _clean_component(key)
        if not isinstance(data, dict):
            raise WorldError(f"组件 {component} 的数据必须是对象")
        out[component] = dict(data)
    return out


def _validate_fields(fields: list) -> list[dict]:
    """字段 schema 校验：{name,label,type,default?}；type ∈ str/int/float/bool/json。

    **同一组件内同名字段只能声明一次**（D41：同一地址只能有一个声明）——所以这里
    顺带拒绝"一份声明里写了两遍同一个名字"；跨多次声明（声明 + ``add_tag_fields``
    追加）的重名由调用点按同一把尺子检查。
    """
    if not isinstance(fields, list):
        raise WorldError("fields 必须是列表")
    out: list[dict] = []
    seen: set[str] = set()
    for f in fields:
        if (
            not isinstance(f, dict)
            or not isinstance(f.get("name"), str)
            or not f["name"]
        ):
            raise WorldError("字段 schema 需要 name")
        if f["name"] in seen:
            raise WorldError(f"同一组件内字段名重复声明：{f['name']}")
        seen.add(f["name"])
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


def _clean_component_name(value: object, what: str = "组件名") -> str:
    """校验一个组件名或组件键，不把坏输入静默降级为 ``local:``。"""
    name = _clean_required(value, what)
    if ":" in name:
        source, bare = name.split(":", 1)
        if not source or not bare or ":" in bare:
            raise WorldError(f"{what}必须是 source:name")
    return name


def _clean_tag_list(value: object, what: str) -> tuple[str, ...]:
    """组件筛选参数校验（D26：**不静默丢弃**——非字符串/空串直接报错）。

    与 ``parse_names``（写入边界的容错解析）刻意不同：实体身上的组件是**已有数据**，
    解析要宽容；查询条件是人/包现写的意图，拼错了必须报错而不是"查不到东西"。
    """
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise WorldError(f"{what} 必须是标签数组")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise WorldError(f"{what} 里的标签必须是非空字符串")
        tag = item.strip()
        if tag not in out:
            out.append(tag)
    return tuple(out)


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
    """地块模板负载规范化 + **校验**（v0.5.2：文案结构在保存点就检查）。

    模板 ``data`` 会原样入库，保存时不校验的话，非法结构（含 v0.5.2 起已禁止的
    纯文本文案）会一直躺在库里，直到"套用"时才炸——错误该发生在保存点。
    ``name`` 仍允许留空（"先存个空壳模板、之后再填"的场景保留）：用占位名走一遍
    完整解析，再把名字还原成空。
    """
    if not isinstance(data, dict):
        raise WorldError("地块模板 data 必须是对象")
    name = data.get("name")
    placeholder = not (isinstance(name, str) and name.strip())
    source = {**data, "name": "（未命名）"} if placeholder else data
    loc = parse_location(_template_to_absolute(source, 0, 0))
    out = _absolute_to_template(location_to_dict(loc))
    if placeholder:
        out["name"] = ""  # 名字保持"还没填"
    return out


def _location_from_template(data: dict, map_id: str, row: int, col: int) -> Any:
    """按放置坐标实例化地块模板（同图目标平移、跨图目标原样）。"""
    payload = _template_to_absolute(data, row, col)
    payload["map_id"] = map_id
    return parse_location(payload)


def _entity_template_payload(data: Any) -> dict[str, Any]:
    """实体模板负载校验 + 规范化（D22 / D41：``{name, desc, components}``）。

    **"类型 = 一组组件的预设"就落在这里**（D41）：模板是"照这个建一个实体"的预设，
    建出来的实体只带组件——所以模板里也**没有** ``kind`` / ``tags``，要带能力就在
    ``components`` 里给组件键。
    """
    if not isinstance(data, dict):
        raise WorldError("实体模板 data 必须是对象")
    return {
        "name": str(data.get("name") or "").strip(),
        "desc": str(data.get("desc") or ""),
        "components": _clean_components(data.get("components")),
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
        # D41：**只有一套组件声明**（_tag_specs，键 = 组件键 source:name）——
        # 带某组件即具备该能力，能力解析只有一条路径
        self._tag_specs: dict[str, TagSpec] = {}
        # D41/D44：**归属从键与规格里读**（键带 source、规格带 play_id）——
        # 原来那张 `_tag_owner` 表已删除："另存一份归属"必然会与键/规格走散
        # D21 规格级能力缓存：组件的键集合 → 有序 TagSpec 列表（不含世界过滤）
        self._spec_cache: dict[tuple[str, ...], tuple[TagSpec, ...]] = {}
        self._interactions: dict[str, _InteractionBinding] = {}
        self._event_bindings: dict[str, list[_EventBinding]] = {
            e: [] for e in WORLD_EVENTS
        }
        self._ui_hooks: dict[tuple[str, str], list[_UiHookBinding]] = {}
        # D9/D41 字段设施：**按组件分组**的追加字段声明（组件自身字段在 spec.fields）
        # （v2 / D37：原 `_item_fields` 已随物品移除；D41：`_category_fields` 已删）
        self._tag_fields: dict[str, list[_FieldAppend]] = {}
        # D11/A3 原语分派表：name -> 覆盖登记（无登记 = 内核默认实现）
        self._primitive_overrides: dict[str, _PrimitiveOverride] = {}
        # G14 原语过滤器链：name -> 按注册序的过滤器列表（链尾 = 默认实现）
        self._primitive_filters: dict[str, list[_PrimitiveFilter]] = {}
        # D2/G2 MCP 工具注册表（玩法包 register_tool；MCP server 动态同步）
        self._tools: dict[str, _ToolBinding] = {}
        self._mcp: Any | None = None  # 绑定后工具注册/清理即时 add/remove
        # G56：广播 tools/list_changed 的待执行任务（持引用，防被 GC 提前回收）
        self._tool_notify_tasks: set[asyncio.Task] = set()
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
        self._subscribers: set[tuple[asyncio.Queue, str | None, str]] = set()
        self._tick_task: asyncio.Task | None = None
        self._binding_seq = 0  # D27 事件注册序（同 phase/order 的稳定兜底）

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

    # ---------- 物品定义：已移除（v2 / D37） ----------
    #
    # 原 `register_item_def` / `item_defs_of_play` / `flush_item_defs` / `delete_item_def`
    # 与 `add_item_fields` 全部删除。**物品不在内核**：
    #   - 物品**类型** → 组件声明（`register_entity_tag`；归属与卸载清理沿用注册表既有机制）
    #   - 物品**实例** → 实体 + 组件（"一个苹果在地上" = 一个实体带苹果组件）
    #   - 管理员手工维护的定义 → **实体模板**（`templates` 表 `scope="entity"`，本来就有
    #     "用户数据（本地模板落库）vs 包声明（随卸载消失）"的区分）
    #   - `use_action` → interaction 名；`on_item_used` → 玩法包自定义事件
    # 见 DESIGN §12.8 / D37。

    def declare_component(
        self,
        name: str,
        *,
        interactions: tuple[str, ...] = (),
        label: str = "",
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> str:
        """**声明一个组件**（D41：唯一的一套声明 API）。

        - 组件名 = ``source:name``：来源进名字，所以两个包各声明 ``merchant`` 是
          **两个组件共存**，不存在"后注册覆盖"；
        - 裸名声明时 source 自动取调用者的 ``play_id``（内核/测试直接调 engine 且
          ``play_id=""`` → ``local``）：``register_entity_kind("merchant", …)`` 注册出的
          是 ``<play_id>:merchant``；
        - 显式写全名也行：**自己的包名**与**共享的 ``local:``** 都可以（后者是"内容 +
          行为"对接的公共命名空间——世界内容用 ``local:`` 写实体，行为包声明 ``local:``
          给它行为，见 §12.6），别的包名报错、``core:`` 报错；
        - ``categories`` 只是**选取分组**（D10），不再承载字段（D41 删了分类字段）。
        """
        name = _clean_component_name(name)
        if ":" in name:
            source, bare = name.split(":", 1)
            if source == "core":
                raise WorldError("玩法包不能声明 core: 组件")
            if source not in ("local", play_id or "local"):
                raise WorldError(
                    f"组件声明的 source 必须是调用玩法包自身或共享的 local:（收到 {source}）"
                )
            key = name
        else:
            key = f"{play_id or 'local'}:{name}"
        source = key.split(":", 1)[0]
        self._register_tag(
            key,
            interactions=interactions,
            label=label,
            # 归属跟着**键里的 source** 走（D44 的方向：归属的唯一事实来源就是键）；
            # `local:` 是共享命名空间，没有"内容方 owner"——只有行为包声明它时才有
            play_id=play_id if source == "local" else source,
            fields=fields,
            categories=categories,
        )
        return key

    def _resolve_component_key(self, name: str) -> str:
        """按 D41 在写入/查询边界把裸名解析为稳定组件键。"""
        name = _clean_component_name(name, "组件名")
        if ":" in name:
            return name
        candidates = [key for key in self._tag_specs if key.split(":", 1)[1] == name]
        if len(candidates) > 1:
            raise WorldError(f"组件名有多个声明者：{name}（请使用完整键）")
        return candidates[0] if candidates else f"local:{name}"

    def register_entity_kind(
        self,
        kind: str,
        *,
        interactions: tuple[str, ...] = (),
        label: str = "",
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
        tags: tuple[str, ...] | list[str] = (),
    ) -> str:
        """旧名别名（D41：旧调用点零改动）：声明一个组件。

        ``tags`` 参数**只接受空值**——"类型 = 一组组件的预设"这个角色已归**实体模板**
        （D41 / §12.6）：模板本身就是"照这个建一个实体"，预设组件写在它的
        ``components`` 里。包想在实体上多带组件，就在放置/编辑时给组件键。
        """
        if parse_names(tags):
            raise WorldError(
                "类型预设已归实体模板（D41）：请用 register_entity_template 声明"
                "一组组件，或直接在实体上给组件键"
            )
        return self.declare_component(
            kind,
            interactions=interactions,
            label=label,
            play_id=play_id,
            fields=fields,
            categories=categories,
        )

    def register_entity_type(
        self,
        kind: str,
        *,
        tags: tuple[str, ...] | list[str] = (),
        label: str = "",
        interactions: tuple[str, ...] = (),
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> str:
        """``register_entity_kind`` 的同义名（更好读）；``tags`` 同上只接受空值。"""
        return self.register_entity_kind(
            kind,
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
        interactions: tuple[str, ...] = (),
        play_id: str = "",
        fields: list[dict] | None = None,
        categories: tuple[str, ...] = (),
    ) -> str:
        """旧名别名（D41）：``declare_component`` 的另一个叫法。"""
        return self.declare_component(
            tag,
            interactions=interactions,
            label=label,
            play_id=play_id,
            fields=fields,
            categories=categories,
        )

    def _register_tag(
        self,
        tag: str,
        *,
        interactions: tuple[str, ...] | list[str],
        label: str,
        play_id: str,
        fields: list[dict] | None,
        categories: tuple[str, ...] | list[str],
    ) -> None:
        if not isinstance(interactions, (tuple, list)) or not all(
            isinstance(a, str) and a for a in interactions
        ):
            raise WorldError("interactions 必须是动作名列表")
        self._tag_specs[tag] = TagSpec(
            key=tag,
            interactions=tuple(interactions),
            label=str(label or ""),
            play_id=play_id,
            fields=_validate_fields(fields or []),
            categories=tuple(
                str(c) for c in categories if isinstance(c, str) and c.strip()
            ),
        )
        # D44：这里**不再另记归属**——声明者就是 `spec.play_id`（键里还有 source），
        # 需要"这个组件属于谁"时读规格，别维护第二份真相
        self._invalidate_spec_cache()

    # ---------- 字段设施（D9 / D41：**按组件分组**，不跨组件摊平） ----------

    def _field_names(self, key: str) -> set[str]:
        """某组件**已经**声明过的字段名（自身声明 + 别人追加的）。"""
        spec = self._tag_specs.get(key)
        names = {f["name"] for f in spec.fields} if spec else set()
        names.update(a.field["name"] for a in self._tag_fields.get(key, ()))
        return names

    def add_tag_fields(
        self, tag: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """给**一个组件**追加字段（D41：这就是跨包扩展的正当路径）。

        追加只影响这个组件自己的字段清单；**同名字段重复声明 → 报错**——同一个地址
        只能有一个声明（D41 唯一保留的字段规则）。
        """
        tag = self._resolve_component_key(tag)
        if tag not in self._tag_specs:
            raise WorldError(f"组件未声明：{tag}")
        new = _validate_fields(fields)
        taken = self._field_names(tag) & {f["name"] for f in new}
        if taken:
            raise WorldError(f"组件 {tag} 内字段名重复声明：{'、'.join(sorted(taken))}")
        self._tag_fields.setdefault(tag, []).extend(
            _FieldAppend(play_id=play_id, field=f) for f in new
        )

    def add_kind_fields(
        self, kind: str, fields: list[dict], *, play_id: str = ""
    ) -> None:
        """``add_tag_fields`` 的旧名（D41：旧调用点零改动）。"""
        self.add_tag_fields(kind, fields, play_id=play_id)

    def effective_fields(self, key: str) -> list[dict]:
        """单个组件的有效字段 = 自身声明 + 别人追加的（**按组件分组**，D41）。

        没有"跨组件覆盖顺序"这回事：字段属于声明它的组件；未声明的字段名不存在。
        """
        key = self._resolve_component_key(key)
        spec = self._tag_specs.get(key)
        if spec is None:
            return []  # 未声明组件：无字段、无能力贡献（D19/R6）
        return [*spec.fields, *(a.field for a in self._tag_fields.get(key, ()))]

    def fields_by_component(
        self, keys: list[str] | tuple[str, ...]
    ) -> dict[str, list[dict]]:
        """``{组件键: [字段]}``——能力面报告的字段形态（D41：按组件分组）。"""
        return {
            resolved: self.effective_fields(resolved)
            for resolved in (self._resolve_component_key(k) for k in keys)
            if resolved in self._tag_specs
        }

    def list_kinds(self, category: str | None = None) -> list[dict]:
        """**组件清单**（D41：只有一套声明，所以这是一张清单，不再分"类型 / 标签"）。

        每条 = 一个组件：``key`` / ``source`` / ``name`` / 文案 / 动作 / 字段 schema /
        ``categories``（选取分组，D10 的 ``category`` 过滤仍按它精准选取）。
        """
        out = []
        for tag, spec in self._tag_specs.items():
            if category is not None and category not in spec.categories:
                continue
            out.append(
                {
                    "key": spec.key,
                    "source": spec.source,
                    "name": spec.name,
                    "label": spec.label or spec.name,
                    "interactions": list(spec.interactions),
                    "fields": self.effective_fields(spec.key),
                    "categories": list(spec.categories),
                }
            )
        return sorted(out, key=lambda k: k["key"])

    # ---------- 组件能力解析（D19 / D21 / D41） ----------

    def _invalidate_spec_cache(self) -> None:
        """注册表变动即清空规格缓存（D21：缓存以**实体的组件键集合**为键，不含世界）。"""
        self._spec_cache.clear()

    def entity_components(self, entity: Entity) -> list[str]:
        """实体带的组件键（**这就是它的能力清单**，D41）。

        含 ``core:`` 组件（位置 / 名字 / 账户绑定是内核协议数据，不是能力）——调用方
        要"能力"就用 ``_entity_specs()`` / ``capabilities()``，它们只看有声明的组件。
        """
        return list(entity.components)

    def _entity_specs(self, entity: Entity) -> tuple[TagSpec, ...]:
        """实体带的组件里**有声明**的那些规格（不含世界过滤；规格级缓存，D21/C1）。

        未声明的组件没有规格 → 不贡献任何能力（实体照常存在，D19/R6）——
        这就是**虚构组件**（D41：允许存在、界面标注、不贡献能力）。
        """
        key = tuple(entity.components)
        cached = self._spec_cache.get(key)
        if cached is not None:
            return cached
        specs = tuple(
            spec
            for tag in self.entity_components(entity)
            if (spec := self._tag_specs.get(tag)) is not None
        )
        self._spec_cache[key] = specs
        return specs

    def _active_specs(self, entity: Entity) -> tuple[TagSpec, ...]:
        """按实体**所在世界**过滤后的规格（D21：组件所属包未激活 → 不参与并集）。"""
        world_id = self.store.map_world.get(entity.map_id)
        return tuple(
            spec
            for spec in self._entity_specs(entity)
            if not spec.play_id or self._world_play_active(world_id, spec.play_id)
        )

    def component_origin(self, key: str, world_id: str | None = None) -> str:
        """一个组件键的**来源性质**（D44 四象限的判据）。

        - ``active``：有声明，且声明者在该实体所在世界启用（或声明者无归属）；
        - ``inactive``：有声明，声明者已加载，但该实体所在世界没启用它；
        - ``orphan``：**声明者已经不在了**——要么规格还在但包没加载（停用 / 加载失败），
          要么规格都没了（包被卸载）。⚠ 键里的 source 只是**线索**：一个非 ``local:``
          的键查无声明，也可能是人手写上去的；
        - ``fictional``：``local:`` 且查无声明——**本来就没有行为，不是坏了**（D41）。

        ``world_id`` 传 None = 不按世界过滤（只回答"包在不在"）。
        """
        spec = self._tag_specs.get(key)
        source = key.split(":", 1)[0]
        if spec is None:
            return "fictional" if source == "local" else "orphan"
        owner = spec.play_id
        if owner and owner not in self._play_apis:
            return "orphan"  # 规格在、包没加载（停用 / 加载失败）
        if (
            owner
            and world_id is not None
            and not self._world_play_active(world_id, owner)
        ):
            return "inactive"
        return "active"

    def capabilities(self, entity: Entity) -> dict:
        """实体合并后的能力（D19 / D41 / D44；管理端、编辑器诊断 + 玩法包自查用）。

        ``interactions`` = 各**生效组件**声明的动作并集；``fields`` = **按组件分组**
        （``{组件键: [字段]}``，不跨组件摊平）。

        组件按**四象限**分桶（D44），方便编辑器解释"为什么没效果"：
        ``active_components``（生效）、``inactive_components``（声明在，但该世界未启用）、
        ``orphan_components``（声明它的包没加载 / 已被卸载）、``fictional_components``
        （``local:`` 且没有声明 = 虚构组件：本来就没有行为）。``core:`` 组件是内核协议
        数据，不进这四个桶。
        （诊断路径不做缓存，热路径走 `_active_specs`。）
        """
        world_id = self.store.map_world.get(entity.map_id)
        buckets: dict[str, list[str]] = {
            "active": [],
            "inactive": [],
            "orphan": [],
            "fictional": [],
        }
        for tag in self.entity_components(entity):
            if is_core_component(tag):
                continue  # 内核协议数据（core:position / core:info / …）：不是能力
            buckets[self.component_origin(tag, world_id)].append(tag)
        specs = [self._tag_specs[t] for t in buckets["active"]]
        return {
            "components": self.entity_components(entity),
            "active_components": buckets["active"],
            "inactive_components": buckets["inactive"],
            "orphan_components": buckets["orphan"],
            "fictional_components": buckets["fictional"],
            "interactions": sorted({a for s in specs for a in s.interactions}),
            "fields": self.fields_by_component(buckets["active"]),
        }

    # ---------- 组件诊断与孤儿清理（D44 / G48） ----------

    def component_usage(self) -> list[dict]:
        """实体上出现的组件键，按 **source** 聚合（D44 诊断与清理的共同数据源）。

        每行 = 一个 source：``keys``（该 source 下出现过的组件键）、``entities``
        （带其中任意一个键的实体 id，稳定排序）、``count``。``core:`` 不列
        （那是内核协议数据，不是能力）。
        """
        rows: dict[str, dict] = {}
        for entity in self.store.entities.values():
            for key in entity.components:
                source = key.split(":", 1)[0]
                if source == "core":
                    continue
                row = rows.setdefault(
                    source, {"source": source, "keys": set(), "entities": set()}
                )
                row["keys"].add(key)
                row["entities"].add(entity.id)
        out = []
        for row in rows.values():
            out.append(
                {
                    "source": row["source"],
                    "keys": sorted(row["keys"]),
                    "entities": sorted(row["entities"]),
                    "count": len(row["entities"]),
                }
            )
        return sorted(out, key=lambda r: r["source"])

    def diagnose_components(
        self, package_state: Callable[[str], str] | None = None
    ) -> list[dict]:
        """按 source 的组件诊断（D44 四象限 + **清理资格**）。

        每行：``source`` / ``state``（active / inactive / orphan / fictional）/
        ``package``（loaded / disabled / load_failed / invalid / uninstalled / none）/
        ``purgeable`` / ``keys`` / ``count`` / ``sample``（样例实体 id，最多 3 个）。

        ⚠ **`local:` 一律是 fictional 且不可清理**：键里读不出"哪个包"，用手写数据
        也用它——清理它等于删用户数据。清理只针对**非 local 的 source**，且服务端强制
        ``purgeable``（包目录真的不在 + 当前没有声明）。
        """
        resolver = package_state or self._loaded_state
        out: list[dict] = []
        for row in self.component_usage():
            source = row["source"]
            package = resolver(source)
            state = self._quadrant_of(source, package)
            out.append(
                {
                    "source": source,
                    "state": state,
                    "package": package,
                    "purgeable": state == "orphan" and package == "uninstalled",
                    "keys": row["keys"],
                    "count": row["count"],
                    "sample": row["entities"][:3],
                }
            )
        return out

    def _loaded_state(self, source: str) -> str:
        """默认包状态：引擎只知道加载集合（PlayLoader 会传更细的解析器）。"""
        if source == "local":
            return "none"
        return "loaded" if source in self._play_apis else "uninstalled"

    def _quadrant_of(self, source: str, package: str) -> str:
        """一个 source 的四象限归属（D44）：看包状态 + 声明是否还在。"""
        if source == "local":
            return "fictional"
        if package != "loaded":
            return "orphan"
        declared = any(spec.source == source for spec in self._tag_specs.values())
        if not declared:
            return "orphan"  # 包在、但没有任何声明留下（旧数据 / 手工键）→ 一样是孤儿
        # 包在、声明也在：再看这些实体所在世界用不用它（按实体算，取"至少一处生效"）
        return "active" if self._any_world_uses(source) else "inactive"

    def _any_world_uses(self, source: str) -> bool:
        """该 source 的组件是否在**某个**世界生效（世界为空 = 全部启用）。"""
        for world_id in self.store.worlds:
            if self._world_play_active(world_id, source):
                return True
        return not self.store.worlds  # 没有世界容器 = 不按世界过滤

    def source_components(self, source: str) -> dict:
        """某 source 在实体上的占用：``{keys, entities, count}``（清理前的影响面）。"""
        source = _clean_required(source, "来源")
        keys: set[str] = set()
        entities: list[str] = []
        for entity in self.store.entities.values():
            hit = [k for k in entity.components if k.split(":", 1)[0] == source]
            if hit:
                keys.update(hit)
                entities.append(entity.id)
        return {
            "source": source,
            "keys": sorted(keys),
            "entities": sorted(entities),
            "count": len(entities),
        }

    async def purge_components(
        self,
        source: str,
        *,
        keys: list[str] | tuple[str, ...] | None = None,
        dry_run: bool = True,
        package_state: Callable[[str], str] | None = None,
    ) -> dict:
        """**清理某个已卸载来源的遗留组件**（D44 / G48；管理端手动、默认 dry-run）。

        规则（服务端强制，不能只靠界面藏按钮）：
        - **只有"包真的不在了"（``package == "uninstalled"``）才允许清**：停用
          （``disabled``）与加载失败（``load_failed``）都**不行**——包还在，启用 / 修好
          即恢复，清了就是白删数据；
        - ``local:`` **永不可清**（读不出归属，可能是人手写的数据）；
        - 粒度 = 按 source 全清，或给 ``keys`` 子集（键必须属于该 source）；**不支持按实体挑**；
        - ``dry_run=True``（默认）只回影响面，不落盘。

        ⚠ **清理是双重不可逆**：能力 = 组件的存在——删掉 ``pkg_b:duel`` = 数据没了、
        该实体的这项能力也没了；重装只对**还带着该组件的实体**恢复行为。
        """
        async with self._lock:
            resolver = package_state or self._loaded_state
            report = self.source_components(source)
            package = resolver(report["source"])
            if report["source"] == "local":
                raise WorldError("local: 是共享命名空间，读不出归属，不能清理")
            if package != "uninstalled":
                raise WorldError(
                    f"玩法包 {report['source']} 还在（{package}）——启用 / 修好即恢复，"
                    f"不能清理它的组件"
                )
            wanted = report["keys"] if keys is None else sorted(set(map(str, keys)))
            if keys is not None:
                unknown = [k for k in wanted if k not in report["keys"]]
                if unknown:
                    raise WorldError(
                        f"这些组件不属于 {report['source']}：{'、'.join(unknown)}"
                    )
            payload = {
                **report,
                "keys": wanted,
                "dry_run": bool(dry_run),
                "purged": False,
            }
            if dry_run or not wanted:
                return payload
            changed: list[Entity] = []
            for entity in self.store.entities.values():
                hit = [k for k in wanted if k in entity.components]
                if not hit:
                    continue
                entity.components = {
                    k: v for k, v in entity.components.items() if k not in hit
                }
                changed.append(entity)
            await self.store.save_entities(changed)
            await self._emit(
                "on_world_edited",
                {
                    "op": "purge_components",
                    "source": report["source"],
                    "keys": wanted,
                    "entities": len(changed),
                },
            )
            return {**payload, "purged": True, "count": len(changed)}

    # ---------- MCP 工具注册（D2 / G2） ----------

    def attach_mcp(self, mcp: Any) -> None:
        """绑定 MCP server：此后 register_tool / 清理工具即时同步 add/remove。"""
        self._mcp = mcp
        for name in list(self._tools):
            self._sync_tool_add(name)
        self._refresh_instructions()

    def _refresh_instructions(self) -> None:
        """按当前工具集刷新 MCP instructions。

        真正的存储位是 SDK lowlevel server 的 ``instructions``——``FastMCP.instructions``
        是只读 property，读的就是它。``FastMCP.settings`` **没有** instructions 字段：
        v0.7.0 之前这里写的是 ``settings.instructions = …``，赋值抛 ValueError 又被
        宽 except 吞成 debug 日志，于是"随注册表刷新"事实上从未生效——表现为**工具在、
        说明书不在**（运行期装/启用玩法包后，``tools/list`` 已更新，``initialize`` 的
        instructions 还停在启动时那份，零包启动的部署会一直说"没有任何工具"）。
        """
        server = getattr(self._mcp, "_mcp_server", None)
        if server is None:
            return
        if not hasattr(server, "instructions"):
            logger.warning(
                "[worlditor] MCP instructions 刷新跳过：SDK server 无 instructions 属性"
            )
            return
        from .mcp import build_instructions

        server.instructions = build_instructions(self)

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
        self._notify_tools_changed()

    def _notify_tools_changed(self) -> None:
        """向已连接的 MCP 客户端广播 `tools/list_changed`（G56）。

        装/启用/停用/卸载玩法包都会走到这里——没有它，服务端 `tools/list` 变了而
        客户端还拿着旧清单，只能重连才看得见新工具。

        best-effort：同步上下文（没有事件循环）或没有活跃会话时静默跳过。
        """
        if self._mcp is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        from .mcp import notify_tools_changed

        task = loop.create_task(notify_tools_changed())
        self._tool_notify_tasks.add(task)
        task.add_done_callback(self._tool_notify_tasks.discard)

    def _sync_tool_remove(self, name: str) -> None:
        if self._mcp is not None:
            try:
                self._mcp.remove_tool(name)
            except Exception:  # noqa: BLE001
                logger.debug("[worlditor] MCP 工具移除失败（可能未注册）：%s", name)
            self._refresh_instructions()
            self._notify_tools_changed()

    def register_tool(
        self,
        name: str,
        handler: Callable,
        *,
        description: str = "",
        params: dict[str, str] | None = None,
        requires_entity: bool = True,
        play_id: str = "",
    ) -> None:
        """注册 MCP 工具（G2：handler(api, ctx, **args)，身份经 api.caller()）。

        同名工具冲突**报错拒绝**（D2，避免静默替换）。

        Args:
            requires_entity: 该工具是否要求调用者有化身（D46）——默认 ``True``
                （老包都假设 ``api.caller()`` 有值，改默认值会在运行期炸）。
                "创建第一具化身"这类**自举**工具必须显式传 ``False``，
                否则玩家永远调不到它（没有化身 → 被挡 → 更没化身）。
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
            requires_entity=bool(requires_entity),
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
                "requires_entity": b.requires_entity,
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
          语义（背包 slots 等）只有玩法包自己懂，内核不裸露
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
        if action in self._interactions:
            previous = self._interactions[action]
            raise WorldError(f"交互动作冲突：{action}（已由 {previous.play_id} 注册）")
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
        phase: str = DEFAULT_EVENT_PHASE,
        order: int = 0,
    ) -> None:
        """订阅世界事件；on_tick 需给出 interval（各自间隔，A3）。

        事件名开放（D1/G8：任意事件名，语义由玩法包定义）；预置事件见
        model.WORLD_EVENTS。

        Args:
            interval: on_tick 专用，正秒数（各订阅者各自间隔）。
            phase: 执行阶段（D27）——``input`` → ``simulate`` → ``present``，
                缺省 ``simulate``。跨包顺序由此显式声明，不再依赖包加载序。
            order: 同阶段内的细分序号（越小越先，可负）。同 phase/order 时
                按注册序稳定排序（= 老行为，单包多订阅者顺序不变）。

        Raises:
            WorldError: 事件名空 / handler 不可调用 / on_tick 缺 interval /
                阶段名不在 EVENT_PHASES 内 / order 非整数。
        """
        event = _clean_required(event, "事件名")
        if not callable(handler):
            raise WorldError("事件 handler 必须是可调用对象")
        if event == "on_tick":
            if interval <= 0:
                raise WorldError("on_tick 需要正的 interval 秒数")
        phase = self._clean_phase(phase)
        if not _is_int(order):
            raise WorldError("order 必须是整数")
        self._binding_seq += 1
        bindings = self._event_bindings.setdefault(event, [])
        bindings.append(
            _EventBinding(
                play_id=play_id,
                handler=handler,
                interval=float(interval),
                phase=phase,
                order=int(order),
                seq=self._binding_seq,
            )
        )
        # 顺序在注册时定下来（emit/tick 热路径不排序）
        bindings.sort(key=_binding_sort_key)

    @staticmethod
    def _clean_phase(phase: object) -> str:
        """阶段名校验（D27）：未给/空 = simulate；未知名报错（不静默造新阶段）。"""
        if phase is None or phase == "":
            return DEFAULT_EVENT_PHASE
        if not isinstance(phase, str) or phase not in EVENT_PHASES:
            raise WorldError(
                f"阶段必须是 {'/'.join(EVENT_PHASES)} 之一"
                f"（缺省 {DEFAULT_EVENT_PHASE}）"
            )
        return phase

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

    def clear_play_registrations(self, play_id: str, *, purge: bool = False) -> None:
        """清理某玩法包的全部注册（kind / interaction / event / ui / 字段 /
        原语分派），供加载失败回滚与卸载使用（C2：重载 = 引擎重建，此为兜底清理）。

        原语分派登记随生命周期清除 → 自动恢复内核默认实现（§2.4 恢复语义）。

        ``purge=True``（真卸载）：连**组件归属记忆**（D26）一起清——包目录都没了，
        "这个组件曾由它声明"就不该继续让 query 认为该组件"在本世界不存在"。
        停用（purge=False）**保留**归属：停用的包声明过的组件仍然算"有主且不活跃"，
        否则 query 会把它当纯数据组件匹配到（能力已经没了，数据还在）。
        规格（`_tag_specs`）**停用也不清**：清了会让 `capabilities()` 把"停用"
        误报成"未声明"（C8）。

        v2 / D37：原 ``keep_user_items`` 参数已随物品移除——"用户数据 vs 包声明"
        的区分现在由**存储位置**天然承担（本地实体模板落 `templates` 表、
        包注册的模板在 `_play_templates` 内存表，前者本就不受影响）。
        """
        if purge:
            # 按**声明者**清（`spec.play_id`），不是按键里的 source：共享命名空间
            # `local:` 的声明者也是某个玩法包（D41：世界内容写 local:、行为包声明同键）
            # ——按 source 清会漏掉它们，于是包卸载后规格还在，query 就再也不匹配了
            self._tag_specs = {
                k: v for k, v in self._tag_specs.items() if v.play_id != play_id
            }
        self._interactions = {
            k: v for k, v in self._interactions.items() if v.play_id != play_id
        }
        for event in self._event_bindings:
            self._event_bindings[event] = [
                b for b in self._event_bindings[event] if b.play_id != play_id
            ]
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

    async def emit_principal_event(
        self, event: str, *, account_id: str, username: str = ""
    ) -> None:
        """发主体生命周期事件（D47；**只给身份服务用**，玩法包拿不到这条入口）。

        主体 = 可登录的账户，**不是实体**：它不绑位置、不属于任何世界，所以
        ``_binding_active`` 不会拿它做世界激活过滤（订阅者全都能收到）。

        Raises:
            WorldError: 事件名不在 ``PRINCIPAL_EVENTS`` 内（防手滑发出"半个"事件）。
        """
        if event not in PRINCIPAL_EVENTS:
            raise WorldError(
                f"不是主体生命周期事件：{event}（可用：{'/'.join(PRINCIPAL_EVENTS)}）"
            )
        await self._emit(event, Principal(account_id=account_id, username=username))

    async def _emit(self, event: str, *args: Any, log: bool = False) -> None:
        """分发事件给订阅者（串行 + 异常隔离），默认不写世界日志。

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
            request = next((a for a in args if isinstance(a, InteractionRequest)), None)
            if request is not None:
                entity = self.store.entities.get(request.entity_id) or request.target
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

    def subscribe(self, viewer_id: str | None = None, tier: str = "") -> asyncio.Queue:
        """订阅过滤后的世界事件流；private 地图事件只发给可见查看者。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add((queue, viewer_id, tier))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers = {item for item in self._subscribers if item[0] is not queue}

    def _push_to_subscribers(self, payload: dict | None) -> None:
        if payload is None or not self._subscribers:
            return
        map_id = self._event_map_id(payload)
        for queue, viewer_id, tier in list(self._subscribers):
            if map_id is not None and not self.map_visible_to(map_id, viewer_id, tier):
                continue
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)

    def _event_map_id(self, payload: dict) -> str | None:
        entity = payload.get("entity")
        if isinstance(entity, dict):
            position = entity.get("components", {}).get("core:position", {})
            if isinstance(position, dict):
                return position.get("map_id")
        request = payload.get("request")
        if isinstance(request, dict):
            target_id = request.get("target_id")
            target = self.store.entities.get(target_id)
            return target.map_id if target is not None else None
        return payload.get("map_id")

    def _event_payload(self, event: str, args: tuple) -> dict | None:
        """事件 → SSE payload（WebUI 增量更新用；实体全量序列化）。"""
        entity = next((a for a in args if isinstance(a, Entity)), None)
        payload: dict[str, Any] = {
            "event": event,
            "ts": self._now_ts(),
            "entity": entity.to_dict() if entity else None,
            # D28：给客户端做增量/缓存失效的全局坐标（事件本身的实体也各自带 revision）
            "revision": self.store.revision,
            "tick": self.store.tick,
        }
        if event == "on_entity_move":
            # D36：位置是可选组件 —— `from` / `to` **可能为 None**（"从不在场回到场上"
            # 或"离开世界"）。别用 `list(...)` 硬转，那会在 None 上抛 TypeError。
            payload["from"] = list(args[1]) if args[1] is not None else None
            payload["to"] = list(args[2]) if args[2] is not None else None
        elif event == "on_entity_enter":
            payload["map_id"] = args[1]
            payload["row"] = args[2]
            payload["col"] = args[3]
        elif event == "on_interact":
            req, result = args[0], args[1]
            payload["request"] = {
                "action": req.action,
                "target_id": req.target.id if req.target else None,
                "args": req.args,  # v2/D37：原 item_id 槽位已删；玩法包的标识放这里
            }
            payload["result"] = result.to_dict()
        elif event == "on_entity_changed":
            payload["changed"] = args[1]
        elif event == "on_entity_removed":
            payload["entity"] = args[0].to_dict()
        elif event == "on_world_edited":
            payload["what"] = args[0]
        elif event in PRINCIPAL_EVENTS:
            # 主体生命周期（D47）：**不推 SSE**（返回 None 即不广播）——它的内容是
            # "谁登录了"，广播出去等于把主体名册发给每个订阅者。玩法包要反应就
            # 订阅事件（内核内的通道），不经过公开的只读出口。
            return None
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
        """心跳一轮：到期 on_tick handler 依次执行（各自间隔）。

        D28：**每轮先把 tick 窗口号 +1**（哪怕本轮没有任何 on_tick 订阅者）——
        窗口号是变更检测的时间轴，不能因为"没人订阅心跳"就停住。
        """
        self.store.tick += 1  # 单循环内自增，无需锁（_tick_loop 串行调用）
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
        *,
        include_absent: bool = False,
    ) -> list[Entity]:
        """实体列表（位置筛选，宽松：地图不存在 = 空列表）；viewer_id 按隐身过滤（G12）。

        实体字段 ``invisible`` 为真时对普通 viewer 隐藏；viewer 自身字段
        ``see_invisible`` 为真（真视）或查看自己时可见。

        **默认只返回"在世界上"的实体**（D36）：位置是可选组件，缺失 = 不在场
        （玩家下线等）。要连它们一起拿，传 ``include_absent=True``。
        按位置筛选时，不在场的实体天然不匹配（``None != map_id``）。

        这是**老接口**：只按位置筛、不校验地图存在、保持存储顺序。要按标签/世界/
        变更窗口查一批实体，用 ``query_entities``（D26，严格校验 + 稳定排序）。
        """
        if map_id is not None and row is not None and col is not None:
            entities = self.store.entities_at_position(map_id, row, col)
        else:
            entities = list(self.store.entities.values())
        if not include_absent:
            entities = [e for e in entities if e.has_position()]
        if map_id is not None:
            entities = [e for e in entities if e.map_id == map_id]
        if row is not None:
            entities = [e for e in entities if e.row == row]
        if col is not None:
            entities = [e for e in entities if e.col == col]
        self._filter_perception(entities, viewer_id)
        return entities

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
        where: Callable[[Entity], bool] | None = None,
        limit: int | None = None,
        include_absent: bool = False,
    ) -> list[Entity]:
        """实体查询原语（D26）：**按组件/世界/坐标/变更窗口筛一批实体**。

        玩法包不再需要"全量 list_entities + 自己筛"——"所有带中毒组件的实体"
        就是 ``query_entities(tags=["poison"])``。

        Args:
            tags: 必须**全部**具备的组件（D41：能力 = 组件的存在）。裸名按 D41
                解析（唯一声明者 → 用它；无人声明 → ``local:``；多个 → 报错）。
                匹配按 D21 语义：组件由某玩法包声明、而该包在**实体所在世界**
                未激活时，视为"该能力在本世界不存在"→ 不匹配；**没有声明者**的
                组件（实体自带的纯数据组件，或声明包已被真卸载）照常匹配。
                要跳过激活语义，用 ``where=lambda e: e.has_component("x")``。
            exclude_tags: 任一具备即排除（同一套激活语义）。
            map_id: 限定地图（空串 = 默认地图；不存在报错）。
            world_id: 限定世界（**未归属地图按默认世界算**，与激活判定同源）。
            row / col: 坐标筛选（与 list_entities 一致，可单独用）。
            viewer_id: 感知过滤（G12 隐身）：普通 viewer 看不到 ``invisible``
                实体；viewer 自身与 ``see_invisible`` 真视者例外。未知 viewer
                按普通观察者处理（与 list_entities 一致）。
            changed_since_tick: 只要**变更窗口号 ≥ 该值**的实体（D28）。窗口粒度粗：
                同一窗口内多次变更共享窗口号，所以按窗口查**宁可多报、绝不漏报**
                （重复刷新无害，漏刷新才是错的）。
            changed_since_revision: 只要**变更号 > 该值**的实体（D28 精确游标：
                每次落盘写 +1，既不多报也不漏报）。增量刷新用这个——记住
                ``engine.revision`` 当游标即可。
            where: 额外谓词（进程内用法，不参与 MCP 工具/序列化）。
            limit: 结果条数上限（正整数）。
            include_absent: 是否连**不在世界上**的实体一起查（D36：位置是可选组件，
                缺失 = 不在场）。默认 ``False``——玩法包按标签查一批实体时，
                离线玩家之类的"幽灵"不该被当成处理对象；按位置筛选时它们天然不匹配。

        Returns:
            实体列表，按 ``(map_id, row, col, id)`` 稳定排序（便于 diff/limit）。
            **不在场的实体排在最后**（它们没有位置可排）。

        Raises:
            WorldError: 标签/坐标/上限/变更游标类型非法，或地图/世界不存在
                （**不静默返回空**——拼错的筛选条件必须报错）。

        Note:
            当前为内存全表线性扫描（几千实体 = 微秒级）；若实体规模上万，
            在 store 加"标签 → 实体 id"倒排索引即可，本接口不变（见 GAPS G38）。
        """
        required = tuple(
            self._resolve_component_key(t) for t in _clean_tag_list(tags, "tags")
        )
        excluded = tuple(
            self._resolve_component_key(t)
            for t in _clean_tag_list(exclude_tags, "exclude_tags")
        )
        if map_id is not None:
            map_id = self._map_arg(map_id)
            if map_id not in self.store.maps:
                raise WorldError(f"地图不存在：{map_id}")
        if world_id is not None:
            if world_id not in self.store.worlds:
                raise WorldError(f"世界不存在：{world_id}")
        if row is not None and not _is_int(row):
            raise WorldError("row 必须是整数")
        if col is not None and not _is_int(col):
            raise WorldError("col 必须是整数")
        if changed_since_tick is not None and (
            not _is_int(changed_since_tick) or changed_since_tick < 0
        ):
            raise WorldError("changed_since_tick 必须是非负整数")
        if changed_since_revision is not None and (
            not _is_int(changed_since_revision) or changed_since_revision < 0
        ):
            raise WorldError("changed_since_revision 必须是非负整数")
        if limit is not None and (not _is_int(limit) or limit <= 0):
            raise WorldError("limit 必须是正整数")
        if where is not None and not callable(where):
            raise WorldError("where 必须是可调用对象")

        matched: list[Entity] = []
        for entity in self.store.entities.values():
            # D36：位置是可选组件——默认只查"在世界上"的实体（见 include_absent）
            if not include_absent and not entity.has_position():
                continue
            if map_id is not None and entity.map_id != map_id:
                continue
            if world_id is not None and self._world_of_map(entity.map_id) != world_id:
                continue
            if row is not None and entity.row != row:
                continue
            if col is not None and entity.col != col:
                continue
            if (
                changed_since_tick is not None
                and entity.changed_tick < changed_since_tick
            ):
                continue
            if (
                changed_since_revision is not None
                and entity.revision <= changed_since_revision
            ):
                continue
            if required or excluded:
                live = self._live_components(entity)
                if not set(required) <= live:
                    continue
                if excluded and (set(excluded) & live):
                    continue
            if where is not None and not where(entity):
                continue
            matched.append(entity)
        self._filter_perception(matched, viewer_id)
        # D36：排序键里 map_id/row/col 可能为 None（不在场的实体）——**不能直接进元组**，
        # 否则 None 与 str 比较会抛 TypeError。用哨兵把它们稳定地排到最后。
        matched.sort(
            key=lambda e: (
                e.map_id if e.map_id is not None else "\uffff",
                e.row if e.row is not None else 1 << 30,
                e.col if e.col is not None else 1 << 30,
                e.id,
            )
        )
        return matched[:limit] if limit is not None else matched

    def can_observe_entity(
        self, entity_id: str, viewer_id: str | None, tier: str = ""
    ) -> bool:
        """统一判断查看者是否能观察实体及其所在地图。"""
        entity = self.store.entities.get(entity_id)
        if entity is None or not self.map_visible_to(entity.map_id, viewer_id, tier):
            return False
        if tier == "admin" or viewer_id == entity_id:
            return True
        viewer = self.store.entities.get(viewer_id or "")
        return not entity.component(CORE_PERCEPTION).get(ATTR_INVISIBLE) or bool(
            viewer and viewer.component(CORE_PERCEPTION).get(ATTR_SEE_INVISIBLE)
        )

    def _filter_perception(self, entities: list[Entity], viewer_id: str | None) -> None:
        """就地按隐身规则过滤（G12：list_entities / query / 场景同一套判定）。"""
        if viewer_id is None:
            return
        viewer = self.store.entities.get(viewer_id)
        see_all = bool(
            viewer and viewer.component(CORE_PERCEPTION).get(ATTR_SEE_INVISIBLE)
        )
        if see_all:
            return
        entities[:] = [
            e
            for e in entities
            if e.id == viewer_id or not e.component(CORE_PERCEPTION).get(ATTR_INVISIBLE)
        ]

    def _live_components(self, entity: Entity) -> set[str]:
        """实体身上"活着"的组件键集（D26：激活语义的**唯一**落地点）。

        "活着" = 该组件有声明，且它的**声明者当前已加载**、**实体所在世界启用了它**；
        没有声明的组件（虚构组件，或声明包已被真卸载）算活着——"组件即数据"的用法
        不该因为查不到声明就查不到实体。

        为什么比"世界激活"多一条"已加载"：组件是**留在实体数据上的**，包停用后
        组件还在（不像过滤器/覆盖登记那样随停用消失）。只看世界激活集合时，
        空 ``play_ids``（= 全部激活）会让停用包声明的组件"诈尸"成纯数据组件——
        于是 query 说"这是商贩"，available_actions 却说"它没有任何动作"。
        （D44：归属读 `spec.play_id` 与键里的 source，不再另存 `_tag_owner`。）

        包含与排除用同一份集合判定，所以语义天然对称。
        """
        world_id = self.store.map_world.get(entity.map_id)
        live: set[str] = set()
        for tag in self.entity_components(entity):
            spec = self._tag_specs.get(tag)
            if spec is None:
                live.add(tag)  # 无声明（虚构 / 已卸载）：照常匹配
                continue
            owner = spec.play_id
            if owner and (
                owner not in self._play_apis
                or not self._world_play_active(world_id, owner)
            ):
                continue
            live.add(tag)
        return live

    def _world_of_map(self, map_id: str) -> str | None:
        """地图的有效世界（未归属 → 默认世界；与 ``_world_for_activation`` 同源）。"""
        world_id = self.store.map_world.get(map_id)
        if world_id is not None:
            return world_id
        return DEFAULT_WORLD_ID if DEFAULT_WORLD_ID in self.store.worlds else None

    @property
    def tick(self) -> int:
        """当前 tick 窗口号（D28：每次心跳 +1；配合 changed_since_tick 做增量）。"""
        return self.store.tick

    @property
    def revision(self) -> int:
        """全局变更号（D28：每次落盘写 +1；客户端缓存失效判定用）。"""
        return self.store.revision

    def get_map(self, map_id: str) -> Any | None:
        return self.store.maps.get(map_id)

    def list_maps(self) -> list:
        return list(self.store.maps.values())

    def map_visible_to(
        self, map_id: str, entity_id: str | None, tier: str = ""
    ) -> bool:
        """地图对某身份的可见性（G1）。

        public 全可见；private 仅该图上有**自己那个实体**的玩家可见
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
                world = await self.store.update_world(
                    world_id, name=name, desc=desc, play_ids=play_ids
                )
            except KeyError as e:
                raise WorldError(str(e)) from None
            # 激活集合变了 → 该世界里玩家能看到的视图/工具也跟着变，广播同一条信号
            # （否则站在该世界的玩家要整页刷新才知道 tab 变了；PlayLoader 那条只覆盖
            # 包的生命周期，世界级激活不在其中）
            if play_ids is not None:
                await self.emit(
                    "plays_changed",
                    {
                        "reason": "world_plays",
                        "world_id": world_id,
                        "plays": list(world.play_ids),
                    },
                )
            return world

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

    # ---------- 物品：已移除（v2 / D37） ----------
    #
    # 原来这里写着"持有全下沉玩法包、定义留内核注册表"（D8）。v2 起**定义也下沉**：
    # 内核无物品、无 give/take/count/inventories。物品类型用组件声明表达，
    # 实例用"实体 + 组件"。见 DESIGN §12.8 / D37。

    # ---------- 实体原语 ----------

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
        user_id: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        _persist: bool = True,
    ) -> Entity:
        """放置实体（新实体 = **一个组件字典**，D41）。

        **能力就是组件**：``kind`` / ``tags`` 是**输入便利**（D41 的裸名解析，写入时解析）
        ——``kind="wolf"`` 等于给实体带上 ``bestiary:wolf`` 组件（数据 ``{}``，纯能力标记），
        ``tags=["potion"]`` 等于再带上几个组件。要带数据的组件走 ``components``
        （键必须是自己写的完整 ``source:name``，D33）。

        两者都可以不给：**没有能力组件的实体也合法**（一块石头、一个纯位置标记）。
        ``kind`` 未声明也可放置（裸名解析落 ``local:``——虚构组件，见 D41）。
        name 缺省取该组件的 label（声明过的话）。

        v2 / D32（§12.4）：``name`` / ``desc`` / ``user_id`` 是**输入便利**——它们会被
        折进 ``core:info`` / ``core:account`` 组件，实体本身没有这三样特权字段。

        **位置三参数可选（D36）**：全给 = 放进世界（写 ``core:position``）；
        **全不给 = 造一个不在世界上的实体**（合法状态：物品在容器里、尚未投放的 NPC）。
        **只给一部分 = 报错**——半截位置会被兜底成 `""` / `0`，把"忘了给"变成
        静默出现在 (0,0) 的实体；"全有或全无"这条规则与 ``Entity.from_dict`` 一致。

        Raises:
            WorldError: 位置参数只给了一部分 / 目标地块不存在 / 参数非法 / 裸名有多个声明者。
        """
        async with self._lock:
            has_pos = self._resolve_new_position(map_id, row, col)
            entity, ability = self._compose_entity(
                kind=kind,
                tags=tags,
                components=components,
                name=name,
                desc=desc,
                position=has_pos,
                user_id=user_id,
            )
            if _persist:
                await self.store.save_entity(entity)
                await self._emit(
                    "on_world_edited",
                    {
                        "op": "place_entity",
                        "entity_id": entity.id,
                        "components": ability,
                    },
                )
            return entity

    def _compose_entity(
        self,
        *,
        kind: object,
        tags: object,
        components: object,
        name: object,
        desc: object,
        position: dict[str, Any] | None,
        user_id: str | None = None,
    ) -> tuple[Entity, list[str]]:
        """组装一个新实体（**不落盘、不发事件**）：能力裸名解析 + 组件折叠。

        `place_entity`（单条）与 `import_bundle`（批量导入）共用这一段——能力解析、
        `name`/`desc` → `core:info`、坐标 → `core:position`、账户 → `core:account`
        的规则只有一处实现（分散写早晚两边不一致）。

        Returns:
            ``(实体, 本次由 kind/tags 解析出的能力组件键)``。
        """
        payload = _clean_components(components)
        ability: list[str] = []
        if kind is not None:
            # None = 不带能力组件；空串是**写错了**（`_resolve_component_key` 报"不能为空"），
            # 不静默当成"没有"——"忘了填"该吵，不该悄悄造出一个裸实体
            ability.append(self._resolve_component_key(kind))
        ability.extend(self._resolve_component_key(t) for t in parse_names(tags))
        spec = self._tag_specs.get(ability[0]) if ability else None
        if name is None or not str(name).strip():
            name = (
                (spec.label if spec and spec.label else ability[0]) if ability else ""
            )
        # 能力组件进实体（数据 {} 是"纯能力标记"；components 里已给数据就保留）
        for key in ability:
            payload.setdefault(key, {})
        # D36：位置进 core:position（不再是列）——给了坐标才叫"放进世界"
        if position is not None:
            payload = {**payload, CORE_POSITION: position}
        if str(name).strip() or str(desc or ""):
            info = dict(payload.get(CORE_INFO) or {})
            if str(name).strip():
                info["name"] = str(name).strip()
            if str(desc or ""):
                info["desc"] = str(desc or "")
            payload = {**payload, CORE_INFO: info}
        if user_id is not None:
            payload = {**payload, CORE_ACCOUNT: {"user_id": str(user_id)}}
        return (
            Entity(
                id=uuid.uuid4().hex,
                components=payload,
                last_active_ts=self._now_ts(),
            ),
            ability,
        )

    async def import_bundle(
        self,
        map_data: dict,
        locations: list[dict] | None = None,
        entities: list[dict] | None = None,
        *,
        world_id: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """内容导入（**单事务**）：地图 + 地块 + 实体 + 世界归属一次提交（G55）。

        与逐条 `create_map` / `create_location` / `place_entity` 的区别：

        - **一次 SQLite 提交**（`store.save_map_bundle`）：中途任何校验失败 → 一个
          字节都不落盘。逐条写则"导入到一半抛错"会留下半张世界，而按
          "地图已存在则跳过"的幂等写法重跑时会**假装成功**（这正是 G55 的坑）。
        - **校验先于写入**：地图 / 坐标 / 文案 / 连接 / 信封 / 组件全都先在内存里
          过一遍，全部合法才动库。
        - **不覆盖**：地图 id 已存在 → 报错。"已经导入过就跳过"仍由玩法包自己判断
          （``api.get_map(map_id) is not None``）。
        - 实体 id 由内核生成；``name`` / ``desc`` 折进 ``core:info``，``row`` / ``col``
          折进 ``core:position``（同一条"全给或全不给"规则，缺坐标 = 不在世界上）；
          **不支持 `user_id`**（账户绑定归身份服务，D20/D42）。
        - **不走原语分派**：这是数据面导入（与 `create_map` 同级），不是一次动作；
          完成后只发一条 ``on_world_edited``（``{op: "import_bundle", …}``），
          不为每个实体补发 `place_entity` 事件。

        Args:
            map_data: 地图定义（``{id, name, description?, timezone?, visible?}``）。
            locations: 地块列表（``{row, col, name, description?, connections?}``）。
            entities: 实体列表（``{row?, col?, name?, desc?, kind?, tags?,
                components?}``）。
            world_id: 归属世界（不给 = 未归属；未归属地图按默认世界的激活集合算）。
            folder_id: 归属组织节点（需与 world_id 同给）。

        Returns:
            ``{"map_id", "locations", "entities", "entity_ids"}``。

        Raises:
            WorldError: 地图已存在 / 世界或文件夹不存在 / 逐个地块或实体的校验失败
                （消息里带序号，便于定位是哪一行内容写错了）。
        """
        async with self._lock:
            if not isinstance(map_data, dict):
                raise WorldError("地图数据必须是对象（dict）")
            map_id = _clean_required(str(map_data.get("id") or ""), "地图 id")
            if map_id in self.store.maps:
                raise WorldError(f"地图已存在：{map_id}（导入不覆盖既有地图）")
            try:
                world_map = parse_map({**map_data, "id": map_id})
            except (ValueError, WorldError) as e:
                raise WorldError(f"地图数据非法：{e}") from None
            if world_id is not None:
                if world_id not in self.store.worlds:
                    raise WorldError(f"世界不存在：{world_id}")
                if folder_id is not None and folder_id not in self.store.folders:
                    raise WorldError(f"文件夹不存在：{folder_id}")
            raw_locations = locations or []
            if not isinstance(raw_locations, list):
                raise WorldError("locations 必须是列表")
            parsed: list[Location] = []
            seen: set[tuple[int, int]] = set()
            for index, raw in enumerate(raw_locations, start=1):
                if not isinstance(raw, dict):
                    raise WorldError(f"第 {index} 个地块必须是对象（dict）")
                try:
                    loc = parse_location({**raw, "map_id": map_id})
                except (ValueError, WorldError) as e:
                    raise WorldError(f"第 {index} 个地块非法：{e}") from None
                if (loc.row, loc.col) in seen:
                    raise WorldError(f"地块坐标重复：({loc.row}, {loc.col})")
                seen.add((loc.row, loc.col))
                parsed.append(loc)
            raw_entities = entities or []
            if not isinstance(raw_entities, list):
                raise WorldError("entities 必须是列表")
            built: list[Entity] = []
            for index, raw in enumerate(raw_entities, start=1):
                if not isinstance(raw, dict):
                    raise WorldError(f"第 {index} 个实体必须是对象（dict）")
                row, col = raw.get("row"), raw.get("col")
                position: dict[str, Any] | None = None
                if (row is None) != (col is None):
                    raise WorldError(
                        f"第 {index} 个实体的位置要么全给、要么全不给"
                        "（row / col 收到了半截）——不给坐标 = 不在世界上"
                    )
                if row is not None or col is not None:
                    _check_pos(row, col)
                    # 地块必须存在：本批带来的，或世界里已有的（同 place_entity 的闸门）
                    if (row, col) not in seen and (
                        map_id,
                        row,
                        col,
                    ) not in self.store.loc_by_pos:
                        raise WorldError(
                            f"第 {index} 个实体的地块不存在：({row}, {col})"
                            "（要么写进本批 locations，要么图上是现成的）"
                        )
                    position = {"map_id": map_id, "row": row, "col": col}
                try:
                    entity, _ability = self._compose_entity(
                        kind=raw.get("kind"),
                        tags=raw.get("tags"),
                        components=raw.get("components"),
                        name=raw.get("name"),
                        desc=raw.get("desc"),
                        position=position,
                    )
                except (WorldError, ValueError) as e:
                    raise WorldError(f"第 {index} 个实体非法：{e}") from None
                built.append(entity)
            try:
                await self.store.save_map_bundle(
                    world_map, parsed, built, world_id=world_id, folder_id=folder_id
                )
            except Exception:
                # 半截写入不许留给下一个 _commit 提交（见 store.rollback 的说明）
                await self.store.rollback()
                raise
            await self._emit(
                "on_world_edited",
                {
                    "op": "import_bundle",
                    "map_id": map_id,
                    "locations": len(parsed),
                    "entities": len(built),
                },
            )
            return {
                "map_id": map_id,
                "locations": len(parsed),
                "entities": len(built),
                "entity_ids": [e.id for e in built],
            }

    def _resolve_new_position(
        self, map_id: object, row: object, col: object
    ) -> dict[str, Any] | None:
        """新实体的位置（``core:position`` 的值）；**全不给 = 不进世界 → None**。

        拆出来是因为"全有或全无"这条规则必须只有一处实现——分开写早晚会漏一个分支，
        而漏掉的那支的后果是实体静默出现在 (0,0)（§12.4 的读点策略专门要避免的事）。
        """
        given = [map_id is not None, row is not None, col is not None]
        if not any(given):
            return None
        if not all(given):
            raise WorldError(
                "位置参数要么全给、要么全不给（map_id / row / col 收到了半截）"
                "——不给位置 = 造一个不在世界上的实体"
            )
        map_id = self._map_arg(map_id)
        _check_pos(row, col)
        if (map_id, row, col) not in self.store.loc_by_pos:
            raise WorldError(f"地块不存在：({row}, {col})")
        return {"map_id": map_id, "row": row, "col": col}

    async def remove_entity(self, entity_id: str) -> None:
        """移除实体（地图编辑，admin；B8）。

        D14 / D42：**绑定了账户的实体**（带 ``core:account``）**不可**被玩法包移除
        ——账户注销走 ``delete_account_entity``（身份服务受控通道）。
        判据从"身份化"（`kind == "player"`）换成"账户绑定"，理由见
        ``Entity.is_account_bound()``：那是真正起作用的事实，也更准。

        Raises:
            WorldError: 实体不存在 / 绑定了账户。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if entity.is_account_bound():
                raise WorldError(
                    "绑定了账户的实体不可被移除（账户注销走身份服务，D14 / D42）"
                )
            await self.store.delete_entity(entity_id)
            await self._emit("on_entity_removed", entity)
            await self._emit(
                "on_world_edited", {"op": "remove_entity", "entity_id": entity_id}
            )

    async def delete_account_entity(self, entity_id: str) -> None:
        """（身份服务受控）删除**绑定了账户**的实体：账户永久注销专用，发事件。

        与 ``remove_entity`` 的区别：允许账户绑定的实体（D14 的受控豁免——调用方是
        内核身份服务，非玩法包权限；**玩法包拿不到这条通道**，`play/api.py` 不导出它）。

        原 `delete_identity_entity`（D42 改名）："身份"这个概念已删除，
        它实际管的一直是"账户绑定的实体"。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if not entity.is_account_bound():
                raise WorldError("只支持绑定了账户的实体（账户注销通道）")
            await self.store.delete_entity(entity_id)
            await self._emit("on_entity_removed", entity)
            await self._emit(
                "on_world_edited", {"op": "remove_entity", "entity_id": entity_id}
            )

    def identity_entity_of(self, account_id: str):
        """账户绑定的**第一具**化身（无则 None）。D46 起一个主体可以有多具。

        新代码请用 ``entities_of_account``（全部化身）——这个方法只为"只想要一个
        代表"的展示场景保留，顺序 = 存储载入序，**没有语义**（别拿它当"主角色"）。
        """
        for entity in self.store.entities.values():
            if entity.user_id == account_id:
                return entity
        return None

    def entities_of_account(self, account_id: str) -> list[Entity]:
        """该主体的**全部化身**（``core:account.user_id == account_id``；D46）。

        内核唯一按账户找实体的入口：注销级联、账户页展示、D14 保护都走它。
        **与位置无关**（下线/不在世界上的化身同样算数）——这正是 v2/D36 那个
        "用 ``list_entities()`` 按账户找实体 → 下线玩家被当成没有实体 → 又造一具"
        的坑的修法：直接扫 ``store.entities``，绕开"在不在世界上"这个维度。
        """
        return [e for e in self.store.entities.values() if e.user_id == account_id]

    async def move(
        self, entity_id: str, direction: str, *, path: int | None = None
    ) -> SceneView:
        """路径移动（分派入口，D11；默认实现见 _move_default）。

        Raises:
            WorldError: 实体不存在、方向非法、不在任何地块、无路径、能力被禁用。
            （**不再有"被阻挡"**——v2/D34 已整体移除阻挡机制；
            **也不再有"只有玩家能走"**——v2/D42 已删除身份概念。）
        """
        return await self._dispatch_primitive("move", entity_id, direction, path=path)

    async def _move_default(
        self, entity_id: str, direction: str, *, path: int | None = None
    ) -> SceneView:
        """默认路径移动（死引用剔除 + 加权抽目标；可被覆盖，D11）。

        D42：**不再限"只有玩家能走"**——身份概念已删除，"谁能移动"是**能力问题**
        （组件声明 / 玩法包 override / disable，D11）。这也修掉了一处旧的不一致：
        `move_entity`（传送）本来就不限身份。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            direction = _check_direction(direction)
            # D36：路径移动要求"必须在场"——不在世界上的实体没有地块可读
            key = entity.require_position()
            loc = self.store.loc_by_pos.get(key)
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
            from_pos = entity.pos_key()
            entity.set_position(tgt.map_id, tgt.row, tgt.col)
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
            # D36：直接位移同样写 core:position——**也让"从不在场到在场"成为一条合法路径**
            # （把离线实体放回世界：pos_key() 是 None，这里写入即回到场上）
            entity.set_position(map_id, row, col)
            entity.last_active_ts = self._now_ts()
            await self.store.save_entity(entity)
            await self._emit("on_entity_move", entity, from_pos, entity.pos_key())
            await self._emit("on_entity_enter", entity, map_id, row, col)

    async def clear_position(self, entity_id: str) -> None:
        """让实体**离开世界**（整体移除 `core:position`）——D36 的"下线"通道。

        与 ``remove_entity`` 的区别：**实体还在**——组件、标签、账户绑定、`revision`
        全部保留，只是不在任何地块上（找不到它的是"按位置/按场景"的视角，不是内核）。

        **为什么必须有这条入口**：`core:` 是内核保留命名空间（D33），玩法包写不进
        `core:position`。既然 D36 让"不在世界上"成了合法状态（玩家下线、物品收进容器、
        传送中间态，正是**玩法包**最需要的那几种），就必须给玩法包一条走得通的路——
        否则"能造出不在世界上的实体、却永远送不回去"，那是个单向门。
        这与 ``set_perception`` 是同一种做法（§12.2：规则不放宽，能力不丢失）。

        **再放回来**用 ``move_entity``（它接受不在场的实体，D36 已放开这条路径）。
        幂等：本来就不在世界上 = 无操作。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            from_pos = entity.pos_key()
            if from_pos is None:
                return
            entity.clear_position()
            await self.store.save_entity(entity)
            # `to` 为 None（离开世界）——事件负载两侧都做了空值守卫（§12.0 补记）
            await self._emit("on_entity_move", entity, from_pos, None)

    # ---------- 组件原语（D32 / D33：实体唯一的数据单位） ----------
    #
    # 信封：组件名 = ``source:name``（``split_component_key`` 校验）。**``core:`` 是内核
    # 保留命名空间**——它的**写入不经分派表**（玩法包既写不进、也拦不住，D33），其余
    # 组件的写入走分派表（可被覆盖/禁用，D11）。**只读**的 ``get_component`` /
    # ``list_components`` 不进分派表（同 ``query_entities``，D26 口径）。

    def list_components(self, entity_id: str) -> list[str]:
        """该实体的组件名列表（只读；稳定排序，便于 diff）。"""
        return sorted(self._require_entity(entity_id).components)

    def get_component(self, entity_id: str, component: str) -> dict | None:
        """整块读组件数据（不存在返回 ``None``；只读，不进分派表）。"""
        component = _clean_component(component)
        data = self._require_entity(entity_id).components.get(component)
        return dict(data) if isinstance(data, dict) else None

    async def add_component(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        """整块新建组件（分派入口；**已存在 → 报错**——要整体替换用 ``set_component``）。"""
        component = _clean_component(component)
        return await self._dispatch_component_write(
            "add_component", component, (entity_id, component, data)
        )

    async def _add_component_default(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        component = _clean_component(component)
        payload = _clean_component_data(component, data)
        async with self._lock:
            entity = self._require_entity(entity_id)
            if component in entity.components:
                raise WorldError(
                    f"组件已存在：{component}（要整体替换请用 set_component）"
                )
            entity.components = {**entity.components, component: payload}
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed", entity, {"components_added": [component]}
            )

    async def set_component(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        """整块写组件（分派入口；建或**整体替换**）。"""
        component = _clean_component(component)
        return await self._dispatch_component_write(
            "set_component", component, (entity_id, component, data)
        )

    async def _set_component_default(
        self, entity_id: str, component: str, data: dict | None = None
    ) -> None:
        component = _clean_component(component)
        payload = _clean_component_data(component, data)
        async with self._lock:
            entity = self._require_entity(entity_id)
            existed = component in entity.components
            entity.components = {**entity.components, component: payload}
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed",
                entity,
                {"components_set" if existed else "components_added": [component]},
            )

    async def remove_component(self, entity_id: str, component: str) -> bool:
        """整块删组件（分派入口；幂等）。"""
        component = _clean_component(component)
        return await self._dispatch_component_write(
            "remove_component", component, (entity_id, component)
        )

    async def _remove_component_default(self, entity_id: str, component: str) -> bool:
        """整块删组件；不存在 → False（幂等，不报错、不发事件、不落盘）。

        Returns:
            是否真的删掉了。
        """
        component = _clean_component(component)
        async with self._lock:
            entity = self._require_entity(entity_id)
            if component not in entity.components:
                return False
            components = dict(entity.components)
            del components[component]
            entity.components = components
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed", entity, {"components_removed": [component]}
            )
            return True

    async def _dispatch_component_write(
        self, primitive: str, component: str, args: tuple
    ) -> Any:
        """组件写入的统一入口：**``core:`` 跳过玩法包分派表**（D33）。

        参数按 ``_PRIMITIVE_PARAM_NAMES`` 的规范顺序传（位置参数即命名参数）。
        """
        component = _clean_component(component)
        if is_core_component(component):
            return await getattr(self, _PRIMITIVE_DEFAULT_NAMES[primitive])(*args)
        return await self._dispatch_primitive(primitive, *args)

    # ---------- 字段原语（D9 的开放模型保留：字段 = **组件内**的一个键） ----------

    async def set_data(
        self, entity_id: str, name: str, value: Any, *, component: str
    ) -> None:
        """字段写（分派入口；默认实现见 ``_set_data_default``）。

        ``component`` 必填：v2 起**没有**扁平命名空间，字段一律归属某个组件
        （``core:`` 之外的组件名可以由玩法包自由虚构；写在未建组件上会隐式建出来）。
        """
        component = _clean_component(component)
        return await self._dispatch_component_write(
            "set_data", component, (entity_id, name, value, component)
        )

    async def _set_data_default(
        self, entity_id: str, name: str, value: Any, component: str
    ) -> None:
        """默认字段写：合并写组件内的一个字段（组件不存在则隐式建出）。"""
        name = _clean_required(name, "字段名")
        component = _clean_component(component)
        async with self._lock:
            entity = self._require_entity(entity_id)
            data = dict(entity.component(component))
            data[name] = value
            entity.components = {**entity.components, component: data}
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed", entity, {"fields": {component: {name: value}}}
            )

    async def remove_data(self, entity_id: str, name: str, *, component: str) -> bool:
        """字段删除（分派入口，D11；默认实现见 ``_remove_data_default``）。"""
        component = _clean_component(component)
        return await self._dispatch_component_write(
            "remove_data", component, (entity_id, name, component)
        )

    async def _remove_data_default(
        self, entity_id: str, name: str, component: str
    ) -> bool:
        """默认字段删除：删掉某组件内的一个字段（D23 / D29 的另一半）。

        D23 的另一半：字段**能被显式删掉**，而不是只能"整体覆盖组件"顺手丢
        （整体覆盖会连别的包写的字段一起丢，那正是要根除的静默丢字段）。

        **删掉最后一个字段后组件仍然存在**（`{}`）——空组件是**纯能力标记**
        （§12.6：带某组件 = 具备该能力），顺手删组件等于静默摘掉能力。
        要删整个组件请显式调 ``remove_component``。

        Returns:
            是否真的删掉了；字段/组件不存在 → False（幂等，不报错、不发事件、不落盘）。
        """
        name = _clean_required(name, "字段名")
        component = _clean_component(component)
        async with self._lock:
            entity = self._require_entity(entity_id)
            data = entity.components.get(component)
            if not isinstance(data, dict) or name not in data:
                return False
            new_data = dict(data)
            del new_data[name]
            entity.components = {**entity.components, component: new_data}
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed", entity, {"fields_removed": {component: [name]}}
            )
            return True

    async def get_data(
        self, entity_id: str, name: str | None = None, *, component: str
    ) -> Any:
        """字段读（分派入口；默认实现见 ``_get_data_default``）。

        ``name=None`` 返回该组件的**整块数据**（``dict``）；组件不存在返回 ``{}``。
        """
        component = _clean_component(component)
        return await self._dispatch_primitive("get_data", entity_id, name, component)

    async def _get_data_default(
        self, entity_id: str, name: str | None = None, component: str = ""
    ) -> Any:
        """默认字段读：组件内单字段，或``name=None`` 时整块（组件缺失 → ``{}``）。"""
        component = _clean_component(component)
        data = self._require_entity(entity_id).components.get(component)
        data = data if isinstance(data, dict) else {}
        if name is None:
            return dict(data)
        name = _clean_required(name, "字段名")
        return data.get(name)

    # ---------- 内核协议组件的受控入口 ----------
    #
    # ``core:`` 组件玩法包不能直写（D33），否则它既能拦下内核自己的写入，也能伪造
    # 身份组件。但有些协议字段**本来就是玩法包的正当能力**（让实体隐身），所以给
    # 一个**窄口、内核拥有**的入口——与 D20"NPC 升格必须经身份服务这个受控通道"
    # 是同一种做法：规则不放宽（`core:` 仍然只有内核能直写），能力不丢失。

    async def set_perception(self, entity_id: str, patch: dict) -> None:
        """设置感知（``core:perception``）——**玩法包唯一的受控入口**。

        ``patch`` 只接受 ``invisible`` / ``see_invisible``（布尔）：
        普通 viewer 看不到 ``invisible`` 实体；``see_invisible`` 为真的 viewer 能看到
        （G1 / G12，判定点单一：``list_entities`` / ``query_entities`` 同源）。
        """
        if not isinstance(patch, dict):
            raise WorldError("patch 必须是对象")
        clean: dict[str, bool] = {}
        for key, value in patch.items():
            if key not in _PERCEPTION_KEYS:
                raise WorldError(
                    f"感知只支持 {' / '.join(_PERCEPTION_KEYS)}（收到 {key!r}）"
                )
            if not isinstance(value, bool):
                raise WorldError(f"感知字段 {key} 必须是布尔值")
            clean[key] = value
        if not clean:
            return
        async with self._lock:
            entity = self._require_entity(entity_id)
            data = dict(entity.component(CORE_PERCEPTION))
            data.update(clean)
            entity.components = {**entity.components, CORE_PERCEPTION: data}
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed", entity, {"fields": {CORE_PERCEPTION: clean}}
            )

    async def set_acting_entity(self, token: str, entity_id: str) -> None:
        """写"这份凭据以哪具实体行动"（D46；唯一调用方 = ``api.act_as``）。

        存**凭据行**（``tokens.entity_id``）而不是账户行：一个主体可以同时在多台
        设备/多个客户端上玩，各指各的化身；写账户行会让多端互相踩（方案 D-a）。

        **不校验归属**：内核不知道"谁有哪些化身"（roster 归玩法包，D46）。调用方
        （玩法包）必须先用自己的名单确认这具实体属于当前主体，**绝不能**把客户端
        传来的 entity_id 原样交上来。

        Args:
            token: 当前请求的凭据（``api.act_as`` 从连接上下文取）。
            entity_id: 目标实体 id；空串 = 解除指向（回到"没有化身"）。

        Raises:
            WorldError: 实体不存在 / 凭据已失效。
        """
        async with self._lock:
            entity_id = str(entity_id or "")
            if entity_id and entity_id not in self.store.entities:
                raise WorldError(f"实体不存在：{entity_id}")
            if not await self.store.set_token_entity(token, entity_id):
                raise WorldError("凭据已失效，无法切换行动实体")

    async def claim_avatar(self, entity_id: str, account_id: str) -> None:
        """把某具实体登记为某主体的化身（写 ``core:account``）——**唯一写入入口**（D46）。

        与 ``set_perception`` / ``clear_position`` 同一种做法（D33：``core:`` 玩法包
        写不了 → 内核给窄口，规则不放宽、能力不丢失）。为什么内核必须拥有这个写入
        点：``core:account`` 是 **D14 红线**（绑账户的实体玩法包不可删）的判据，
        让包自由写等于让包自己决定"什么不可删"。走这里写进去的化身一律受保护。

        语义：
        - 只能认领给 ``account_id`` 这个主体（调用方从连接上下文取当前主体，
          **不接受客户端指定的账户 id**——否则可以替别人认领/抢注）；
        - 已属于**同一**主体 → 幂等无操作；已属于**别人** → 报错（不改绑）；
        - 一旦认领，账户注销会级联删它（``entities_of_account``），
          ``remove_entity`` / ``delete_map`` / ``delete_location`` / ``copy_map``
          四处都会拒绝。

        Raises:
            WorldError: 实体不存在 / 没有主体（空 account_id）/ 已属于另一个主体。
        """
        if not str(account_id or ""):
            raise WorldError("没有主体上下文，无法认领化身（围观凭据不能认领）")
        async with self._lock:
            entity = self._require_entity(entity_id)
            owner = entity.user_id
            if owner == account_id:
                return  # 幂等：本来就是我的
            if owner is not None:
                raise WorldError(
                    "这具实体已经属于另一个主体，不能改绑（先经账户注销通道释放）"
                )
            entity.components = {
                **entity.components,
                CORE_ACCOUNT: {"user_id": str(account_id)},
            }
            await self.store.save_entity(entity)
            await self._emit(
                "on_entity_changed",
                entity,
                {"fields": {CORE_ACCOUNT: {"user_id": str(account_id)}}},
            )

    async def release_avatar(self, entity_id: str, account_id: str) -> int:
        """**退掉自己的化身**：摘掉 ``core:account`` 绑定——``claim_avatar`` 的反向（D46）。

        为什么必须有这条通道：D14 让"绑了账户的实体"谁都删不掉，这是对的
        （防 token 悬空、防别人把你的身体删了）——但**本人想删掉自己多余的化身**
        时它同样拦着。于是把"解绑"这一步显式化，而不是给玩法包开一个删除后门：

        - 只允许解绑**属于 ``account_id``** 的实体（别人的化身一律拒绝——D14 对
          别人依然完全有效，包仍然删不掉任何一个不属于本次调用主体的化身）；
        - 顺手清空**指向它的凭据指针**（``tokens.entity_id``）——否则"解绑 + 删除"
          之后会留下悬空指针，玩家下次请求拿着一个不存在的实体 id；
        - **不删实体**：调用方随后自己 ``remove_entity``（那时它不绑账户了，
          D14 不再拦）。两步分开是为了让"解绑"在事件流里留下痕迹。

        Returns:
            被清空指针的凭据数（0 = 本来没有凭据指着它）。

        Raises:
            WorldError: 实体不存在 / 没绑账户 / 绑的是**别人**的账户 / 空 account_id。
        """
        if not str(account_id or ""):
            raise WorldError("没有主体上下文，无法退掉化身")
        async with self._lock:
            entity = self._require_entity(entity_id)
            owner = entity.user_id
            if owner is None:
                raise WorldError("这具实体没有绑定账户，不需要解绑")
            if owner != account_id:
                raise WorldError("只能退掉自己的化身（这具属于另一个主体，D14）")
            entity.components = {
                k: v for k, v in entity.components.items() if k != CORE_ACCOUNT
            }
            await self.store.save_entity(entity)
            cleared = await self.store.clear_token_entities(entity_id)
            await self._emit(
                "on_entity_changed", entity, {"components_removed": [CORE_ACCOUNT]}
            )
            return cleared

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

    # ---------- 阻挡：v2 已整体移除（D34） ----------
    #
    # 「所有实体都不阻挡」——原 ``_blocker_at`` / ``_is_blocking`` / ``TagSpec.block_move``
    # / ``core:state`` 全部删除。门的开关、机关、墙、NPC 挡路归**玩法包**
    # （``override_primitive("move")`` 或过滤器链，D11 早已支持）。
    # 将来若需要，另立一个"描述阻挡能力"的内核组件（GAPS G44）。

    def _build_scene(self, entity: Entity) -> SceneView:
        # D36：场景构建要求"必须在场"（不在世界上的实体没有"当前地块"可讲）
        loc = self.store.loc_by_pos.get(entity.require_position())
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
        *,
        viewer_id: str | None = None,
        tier: str = "",
    ) -> InteractionResult:
        """交互通道（分派入口，D11/D12；默认实现见 _interact_default）。

        v2 / D37：原 ``item_id`` 参数已删除——物品不在内核，玩法包把它的标识放进
        ``args``（如 ``args={"item": "apple"}``），内核不解释其内容。
        """
        if viewer_id is not None and not self.can_observe_entity(
            target_id, viewer_id, tier
        ):
            raise WorldError("目标不可见")
        return await self._dispatch_primitive(
            "interact", entity_id, target_id, action, args
        )

    async def _interact_default(
        self,
        entity_id: str,
        target_id: str,
        action: str,
        args: dict | None = None,
    ) -> InteractionResult:
        """默认交互：校验可用动作（C3）→ 玩法包 handler → 返回结果。

        交互 handler 异常会被隔离并转为可展示的 WorldError（不拖垮内核）。

        Raises:
            WorldError: 实体/目标不存在、动作不可用或未实现、handler 出错。
        """
        async with self._lock:
            self._require_entity(entity_id)  # 发起者必须存在（校验，结果本身不用）
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

    def list_actions(
        self,
        target_id: str,
        *,
        viewer_id: str | None = None,
        tier: str = "",
    ) -> list[MenuButton]:
        """实体可用动作按钮；传 viewer 时先经过观察权限。"""
        if viewer_id is not None and not self.can_observe_entity(
            target_id, viewer_id, tier
        ):
            return []
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
            # 1. 先在内存副本中重写全部引用，事务失败时不污染现有对象。
            updated_locations = []
            for original in list(self.store.loc_by_pos.values()):
                other = copy.deepcopy(original)
                changed = False
                for slot in other.connections.values():
                    for path in slot.paths:
                        new_targets = []
                        for target in path.targets:
                            if self._target_key(target, original.map_id) == src:
                                new_targets.append(
                                    Target(
                                        map_id=target.map_id,
                                        row=to_row,
                                        col=to_col,
                                        weight=target.weight,
                                    )
                                )
                                changed = True
                            else:
                                new_targets.append(target)
                        path.targets = new_targets
                if changed:
                    updated_locations.append(other)
            original = self.store.loc_by_pos[src]
            moved = copy.deepcopy(original)
            moved.row = to_row
            moved.col = to_col
            updated_locations.append(moved)
            updated_entities = []
            entity_pairs = []
            for original_entity in self.store.entities.values():
                if original_entity.pos_key() == src:
                    moved_entity = copy.deepcopy(original_entity)
                    moved_entity.set_position(map_id, to_row, to_col)
                    updated_entities.append(moved_entity)
                    entity_pairs.append((original_entity, moved_entity))
            await self.store.move_location_bundle(
                map_id, src, dst, updated_locations, updated_entities
            )
            for original_entity, moved_entity in entity_pairs:
                original_entity.components = moved_entity.components
                original_entity.revision = moved_entity.revision
                original_entity.changed_tick = moved_entity.changed_tick
                self.store.entities[original_entity.id] = original_entity
            loc = moved
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
        components: object = _UNSET,
    ) -> Entity:
        """更新实体（admin 编辑；``components`` **整体替换**）。

        D41：**能力就是组件**，所以"改类型 / 改标签"这两个动作不存在——要加能力就
        往 ``components`` 里加一个组件键，要摘能力就把它删掉（空组件是纯能力标记，
        "顺手删空组件"等于静默摘掉能力，所以删除必须显式）。加/删单个组件请用
        ``add_component`` / ``remove_component`` 原语，免得整块替换时丢数据。

        v2 / D32（§12.4）：``name`` / ``desc`` 写在 ``core:info`` 里（★只动这两个键，
        不碰同一组件下的其它数据）；传空串等于把该键删掉（``name`` 随即回落到
        ``id`` 前 8 位的兜底）——**不静默丢**同一组件的其它字段。
        """
        async with self._lock:
            entity = self._require_entity(entity_id)
            if components is not _UNSET:
                entity.components = _clean_components(components)
            if name is not _UNSET or desc is not _UNSET:
                info = dict(entity.component(CORE_INFO))
                if name is not _UNSET:
                    new_name = _clean_required(name, "名称")
                    info["name"] = new_name
                if desc is not _UNSET:
                    new_desc = str(desc or "")
                    if new_desc:
                        info["desc"] = new_desc
                    else:
                        info.pop("desc", None)
                if info:
                    entity.components = {**entity.components, CORE_INFO: info}
                else:
                    entity.components = {
                        k: v for k, v in entity.components.items() if k != CORE_INFO
                    }
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
        visible: str = "public",
        world_id: str | None = None,
        folder_id: str | None = None,
    ) -> WorldMap:
        """新建地图（id 唯一；visible = public/private，G1 可见性）。

        ⚠ **没有"出生点"参数**（D45）：内核不指定"人从哪来"——落点是玩法包的事。
        """
        async with self._lock:
            map_id = _clean_required(map_id, "地图 id")
            name = _clean_required(name, "地图名称")
            if map_id in self.store.maps:
                raise WorldError(f"地图已存在：{map_id}")
            if visible not in ("public", "private"):
                raise WorldError("visible 必须是 public 或 private")
            m = parse_map(
                {
                    "id": map_id,
                    "name": name,
                    "description": parse_text_schedule(description).to_dict()
                    if description
                    else None,
                    "timezone": timezone,
                    "visible": visible,
                }
            )
            if world_id is not None:
                if world_id not in self.store.worlds:
                    raise WorldError(f"世界不存在：{world_id}")
                if folder_id is not None and folder_id not in self.store.folders:
                    raise WorldError(f"文件夹不存在：{folder_id}")
                await self.store.save_map_bundle(
                    m, [], [], world_id=world_id, folder_id=folder_id
                )
            else:
                await self.store.save_map(m)
            await self._emit("on_world_edited", {"op": "create_map", "map_id": map_id})
            return m

    async def delete_map(self, map_id: str) -> None:
        """删除地图（G2：级联地块/实体/世界归属；图上还有**绑定了账户**的实体 → 拒绝）。

        D42：判据从 `kind == "player"` 换成 `core:account`——这条闸门真正想问的是
        "这张图上还有绑着账户的人吗"（删了会让 token 悬空），而不是"有没有身份实体"。

        Raises:
            WorldError: 地图不存在 / 图上仍有绑定了账户的实体。
        """
        async with self._lock:
            map_id = _clean_required(map_id, "地图 id")
            if map_id not in self.store.maps:
                raise WorldError(f"地图不存在：{map_id}")
            for e in self.store.entities.values():
                if e.map_id == map_id and e.is_account_bound():
                    raise WorldError(
                        f"地图上仍有绑定了账户的实体「{e.name}」，无法删除"
                    )
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
        - 绑定了账户的实体（`core:account`）**不复制**——人是人，不是布景（D42）；
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
                    "visible": src.visible,
                }
            )
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
            if with_entities:
                cloned_entities = []
                for e in list(self.store.entities.values()):
                    # D42：**绑定了账户的实体永不复制**（判据从 kind 换成 core:account）
                    # ——复制一份"别人账户的实体"会造出两个都指向同一账户的实体
                    if e.map_id != map_id or e.is_account_bound():
                        continue
                    # v2：位置也在 components 里（core:position）→ 深拷贝组件即复制位置；
                    # 但目标地图是**副本**，所以只把 map_id 指过去（行列不变）
                    cloned = copy.deepcopy(e)
                    cloned.id = uuid.uuid4().hex
                    cloned.set_position(
                        new_map_id, e.require_position()[1], e.require_position()[2]
                    )
                    cloned.last_active_ts = 0.0
                    # D41：**能力就是组件**——深拷贝已把组件（含能力组件与数据）整份带走，
                    # 不再有"实例标签"这一项要单独补（原 `cloned.tags = list(e.tags)` 已删）
                    cloned_entities.append(cloned)
            else:
                cloned_entities = []
            # 归属：默认与源地图同世界同节点
            target_world = (
                self.store.map_world.get(map_id) if world_id is _UNSET else world_id
            )
            target_folder = None
            if target_world is not None:
                target_folder = (
                    self.store.map_folder.get(map_id)
                    if folder_id is _UNSET
                    else folder_id
                )
                if str(target_world) not in self.store.worlds:
                    raise WorldError(f"世界不存在：{target_world}")
                if (
                    target_folder is not None
                    and target_folder not in self.store.folders
                ):
                    raise WorldError(f"文件夹不存在：{target_folder}")
            await self.store.save_map_bundle(
                dup,
                cloned_locs,
                cloned_entities,
                world_id=str(target_world) if target_world is not None else None,
                folder_id=target_folder,
            )
            await self._emit(
                "on_world_edited",
                {"op": "copy_map", "map_id": new_map_id, "from": map_id},
            )
            return dup

    # ---------- 地图体检（纯数据检查，无玩法语义；管理端治理视图数据源） ----------

    def lint_map(self, map_id: str) -> dict[str, Any]:
        """单张地图体检：死连接 / 实体悬空 / 孤立地块 / 无世界归属。

        只报"作者看不出来、但运行时有后果"的问题——运行时对死引用是**静默剔除**，
        所以体检是唯一能提前告知的通道。

        ⚠ **没有"出生点落空"这一项**（D45 已删除）：内核不存在出生点，也就没有
        "新玩家会落在哪、那格在不在"这个问题——它是玩法包自己的落点策略的事。
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

        for e in entities:
            # D36：位置是可选组件——**不在场不是"悬空"**。上面的 `e.map_id == map_id`
            # 过滤其实已经排除了它们（None != map_id），这里再挡一道：这条检查是
            # "数据坏了要报错"的断言，误报一个离线玩家会让人去查根本没坏的数据。
            if not e.has_position():
                continue
            if e.pos_key() not in self.store.loc_by_pos:
                add(
                    "error",
                    "dangling_entity",
                    f"实体「{e.name}」（{e.id[:8]}）在 ({e.row}, {e.col}) 但那里没有地块",
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

        data 形如 ``{name, desc, components}``（D41：**"类型 = 一组组件的预设"就落在这里**
        ——所以没有 ``kind`` / ``tags``，要带能力就在 ``components`` 里给组件键）——
        套用即"照这个建一个实体"，建完仍可改。
        管理端本地模板落库、与这里合并成一个选择列表（D37：这条"包声明 vs 本地数据"
        的区分顶替了原"管理员手工物品定义"的位置）。
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

        拒绝删除**有绑定了账户的实体**占据的地块（D42：判据是账户绑定，不是身份）。

        Raises:
            WorldError: 地块不存在 / 有绑定了账户的实体在场。
        """
        async with self._lock:
            map_id = self._map_arg(map_id)
            _check_pos(row, col)
            key = (map_id, row, col)
            if key not in self.store.loc_by_pos:
                raise WorldError(f"地块不存在：({row}, {col})")
            for e in self.store.entities.values():
                # D42：判据换成"绑定了账户"（这块地上还站着一个绑账户的人 → 别删）
                if e.pos_key() == key and e.is_account_bound():
                    raise WorldError(
                        f"有绑定了账户的实体「{e.name}」位于该地块，无法删除"
                    )
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
