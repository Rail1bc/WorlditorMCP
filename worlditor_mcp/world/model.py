"""世界数据模型（设计见 DESIGN.md）。

纯数据层：地图 / 地块 / 连接 / 模板（Location 系）与 世界 / 组织 / 实体 / 物品 /
交互（Entity 系）统一于此；无版本前缀（历史 v3/v4 模型已合并）。

核心：
- 地块身份 = (map_id, 行, 列)；地图唯一，地块不唯一。
- 连接内嵌于地块：固定 4 方向槽位，每槽多条平行路径；路径内 targets 有序
  （首个 = 主目标 / 展示名，其余 = 意外路径加权随机）。
- 文本分时段加权（TextSchedule）：按当前时间命中时段，再按权重抽一条文本；
  地块描述 / 路径 label / 地图描述复用。
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DIRECTIONS = ("up", "right", "down", "left")

# 方向 ↔ 坐标偏移（行, 列）：up=行-1 / down=行+1 / left=列-1 / right=列+1。
# 权威定义；前端视图组件（worlditor_play_movement/web/view.js）按此约定渲染网格。
DIR_OFFSETS: dict[str, tuple[int, int]] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}

OPPOSITE_DIR: dict[str, str] = {
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
}

# 注入的随机源：返回 [0,1) 的均匀随机数（默认 random.random；测试注入定值）。
Rand = Callable[[], float]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_minutes(value: str) -> int:
    """把 "HH:MM" 解析为当日分钟数（0..1440）。"""
    try:
        h, m = value.split(":")
        minutes = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        raise ValueError(f"无效的时段时间：{value!r}") from None
    if not 0 <= minutes <= 1440:
        raise ValueError(f"无效的时段时间：{value!r}")
    return minutes


def _period_matches(period: TextPeriod, minutes: int) -> bool:
    start = _parse_minutes(period.start)
    end = _parse_minutes(period.end)
    if end == 0:
        end = 1440  # 终点 00:00 视为当日 24:00
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # 跨午夜窗口


@dataclass
class TextItem:
    text: str
    weight: float = 1.0


@dataclass
class TextPeriod:
    start: str  # "HH:MM"，每日循环钟点窗口起点
    end: str  # "HH:MM"，终点（可跨午夜；00:00 视为当日 24:00）
    items: list[TextItem] = field(default_factory=list)


@dataclass
class TextSchedule:
    """分时段加权文本：取当前时间命中的时段，再按权重抽一条文本。

    归一化：缺省 = 单时段全天（00:00–24:00）+ 单条文本权重 1；
    重叠时段按列表顺序先命中者优先；无命中 / 无有效条目返回空串。
    """

    periods: list[TextPeriod] = field(
        default_factory=lambda: [TextPeriod("00:00", "24:00", [TextItem("", 1.0)])]
    )

    def resolve(self, now: datetime, rand: Rand | None = None) -> str:
        """返回当前时间命中的文本；无命中 / 无有效条目返回空串。"""
        minutes = now.hour * 60 + now.minute
        for period in self.periods:
            if not _period_matches(period, minutes):
                continue
            items = [it for it in period.items if it.text and it.weight > 0]
            if not items:
                return ""
            total = sum(it.weight for it in items)
            r = (rand() if rand else random.random()) * total
            acc = 0.0
            for it in items:
                acc += it.weight
                if r <= acc:
                    return it.text
            return items[-1].text
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "periods": [
                {
                    "start": p.start,
                    "end": p.end,
                    "items": [{"text": it.text, "weight": it.weight} for it in p.items],
                }
                for p in self.periods
            ]
        }


def parse_text_schedule(value: Any) -> TextSchedule:
    """把存储值解析为 TextSchedule。

    接受：None（返回默认空调度）、纯字符串（单时段全天单条）、
    {"periods": [...]} 结构。非法条目静默丢弃；全部非法 → 默认空调度。
    """
    if value is None:
        return TextSchedule()
    if isinstance(value, str):
        return TextSchedule(
            periods=[TextPeriod("00:00", "24:00", [TextItem(value, 1.0)])]
        )
    if not isinstance(value, dict):
        return TextSchedule()
    periods: list[TextPeriod] = []
    raw_periods = value.get("periods")
    if isinstance(raw_periods, list):
        for p in raw_periods:
            if not isinstance(p, dict):
                continue
            try:
                start = str(p.get("start") or "00:00")
                end = str(p.get("end") or "24:00")
                _parse_minutes(start)
                _parse_minutes(end)
            except ValueError:
                continue
            items: list[TextItem] = []
            raw_items = p.get("items")
            if isinstance(raw_items, list):
                for it in raw_items:
                    if not isinstance(it, dict):
                        continue
                    text = it.get("text")
                    if not isinstance(text, str) or not text:
                        continue
                    weight = it.get("weight", 1.0)
                    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                        continue
                    w = float(weight)
                    if not math.isfinite(w) or w <= 0:
                        continue
                    items.append(TextItem(text, w))
            if items:
                periods.append(TextPeriod(start, end, items))
    if not periods:
        return TextSchedule()
    return TextSchedule(periods=periods)


@dataclass
class Target:
    """一个目标坐标（地块引用）：map_id 空 = 当前地图；weight 为意外抽取权重。"""

    row: int
    col: int
    map_id: str = ""
    weight: float = 1.0


@dataclass
class ConnectionPath:
    """一条路径（可选出口）：label 为语义文本，targets 有序（首个=主目标，其余=意外）。"""

    label: TextSchedule | None = None
    reveal_target: bool = True
    targets: list[Target] = field(default_factory=list)


@dataclass
class ConnectionSlot:
    """固定方向槽位：enabled 为总开关；paths 多条 = 平行可选路径。"""

    direction: str
    enabled: bool = False
    paths: list[ConnectionPath] = field(default_factory=list)


@dataclass
class Location:
    """地块：身份 = (map_id, row, col)；connections 固定键 up/right/down/left。"""

    map_id: str
    row: int
    col: int
    name: str
    description: TextSchedule | None = None
    connections: dict[str, ConnectionSlot] = field(default_factory=dict)

    def offset(self, direction: str) -> Target:
        """该地块向 direction 偏移 1 的相邻目标。"""
        dr, dc = DIR_OFFSETS[direction]
        return Target(row=self.row + dr, col=self.col + dc)


@dataclass
class WorldMap:
    """地图：地图唯一，地块不唯一。timezone 为地图级时区，None = 服务器本地。

    visible（G1）：public = 所有人可见；private = 仅该图上有自己身份化实体
    的玩家（+admin）可见——家地图/对局地图用 private 隐藏内容。
    """

    id: str
    name: str
    description: TextSchedule | None = None
    timezone: str | None = None
    spawn_row: int = 0
    spawn_col: int = 0
    visible: str = "public"


# ---------- 序列化 / 解析（存储与 API 用；非法条目尽可能容错丢弃） ----------


def target_to_dict(t: Target) -> dict[str, Any]:
    d: dict[str, Any] = {"row": t.row, "col": t.col, "weight": t.weight}
    if t.map_id:
        d["map_id"] = t.map_id
    return d


def _norm_weight(value: Any) -> float:
    """权重归一化：非数字 / 布尔 / 非正 / 非有限数 → 1.0。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    w = float(value)
    return w if math.isfinite(w) and w > 0 else 1.0


def parse_target(value: Any) -> Target | None:
    if not isinstance(value, dict):
        return None
    row = value.get("row")
    col = value.get("col")
    if not _is_int(row) or not _is_int(col):
        return None
    map_id = value.get("map_id")
    return Target(
        map_id=str(map_id) if isinstance(map_id, str) else "",
        row=row,
        col=col,
        weight=_norm_weight(value.get("weight", 1.0)),
    )


def path_to_dict(p: ConnectionPath) -> dict[str, Any]:
    d: dict[str, Any] = {"reveal_target": p.reveal_target}
    if p.label:
        d["label"] = p.label.to_dict()
    d["targets"] = [target_to_dict(t) for t in p.targets]
    return d


def parse_path(value: Any) -> ConnectionPath:
    if not isinstance(value, dict):
        return ConnectionPath()
    label = (
        parse_text_schedule(value.get("label"))
        if value.get("label") is not None
        else None
    )
    reveal = value.get("reveal_target", True)
    targets = []
    raw = value.get("targets")
    if isinstance(raw, list):
        for t in raw:
            parsed = parse_target(t)
            if parsed is not None:
                targets.append(parsed)
    return ConnectionPath(
        label=label,
        reveal_target=reveal if isinstance(reveal, bool) else True,
        targets=targets,
    )


def slot_to_dict(s: ConnectionSlot) -> dict[str, Any]:
    return {
        "direction": s.direction,
        "enabled": s.enabled,
        "paths": [path_to_dict(p) for p in s.paths],
    }


def parse_slot(direction: str, value: Any) -> ConnectionSlot:
    if direction not in DIRECTIONS:
        raise ValueError(f"无效方向：{direction}")
    if not isinstance(value, dict):
        return ConnectionSlot(direction=direction)
    enabled = value.get("enabled", False)
    paths = []
    raw = value.get("paths")
    if isinstance(raw, list):
        for p in raw:
            paths.append(parse_path(p))
    return ConnectionSlot(
        direction=direction,
        enabled=enabled if isinstance(enabled, bool) else False,
        paths=paths,
    )


def default_connections() -> dict[str, ConnectionSlot]:
    """新地块的默认连接：4 个方向槽位全部禁用。"""
    return {d: ConnectionSlot(direction=d, enabled=False, paths=[]) for d in DIRECTIONS}


def location_to_dict(loc: Location) -> dict[str, Any]:
    return {
        "map_id": loc.map_id,
        "row": loc.row,
        "col": loc.col,
        "name": loc.name,
        "description": loc.description.to_dict() if loc.description else None,
        "connections": {d: slot_to_dict(s) for d, s in loc.connections.items()},
    }


def parse_location(value: Any) -> Location:
    if not isinstance(value, dict):
        raise ValueError("地块数据必须是对象")
    map_id = value.get("map_id", "")
    row = value.get("row")
    col = value.get("col")
    if not _is_int(row) or not _is_int(col):
        raise ValueError("地块坐标必须是整数")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("地块名称不能为空")
    description = None
    if value.get("description") is not None:
        description = parse_text_schedule(value.get("description"))
    conns = default_connections()
    raw = value.get("connections")
    if isinstance(raw, dict):
        for d, v in raw.items():
            if d in DIRECTIONS:
                conns[d] = parse_slot(d, v)
    return Location(
        map_id=str(map_id) if isinstance(map_id, str) else "",
        row=row,
        col=col,
        name=name.strip(),
        description=description,
        connections=conns,
    )


def map_to_dict(m: WorldMap) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description.to_dict() if m.description else None,
        "timezone": m.timezone,
        "spawn_row": m.spawn_row,
        "spawn_col": m.spawn_col,
        "visible": m.visible,
    }


def parse_map(value: Any) -> WorldMap:
    if not isinstance(value, dict):
        raise ValueError("地图数据必须是对象")
    id_ = value.get("id")
    name = value.get("name")
    if (
        not isinstance(id_, str)
        or not id_
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise ValueError("地图 id 与名称不能为空")
    description = None
    if value.get("description") is not None:
        description = parse_text_schedule(value.get("description"))
    tz = value.get("timezone")
    spawn_row = value.get("spawn_row", 0)
    spawn_col = value.get("spawn_col", 0)
    if not _is_int(spawn_row) or not _is_int(spawn_col):
        raise ValueError("出生点必须是整数坐标")
    return WorldMap(
        id=id_,
        name=name.strip(),
        description=description,
        timezone=str(tz) if isinstance(tz, str) and tz else None,
        spawn_row=spawn_row,
        spawn_col=spawn_col,
        visible=value.get("visible", "public")
        if value.get("visible") in ("public", "private")
        else "public",
    )


# ---------- 场景视图（移动 / 展示用） ----------


@dataclass
class ScenePath:
    """场景中可见的一条路径（槽内索引即移动句柄；隐藏目标 target_name 为 None）。"""

    direction: str
    path_index: int
    label: str
    reveal_target: bool
    target_name: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "path": self.path_index,
            "label": self.label,
            "reveal_target": self.reveal_target,
            "target_name": self.target_name,
        }


@dataclass
class SceneView:
    """玩家当前场景：所在地块 + 已解析描述 + 可用路径列表（死引用已剔除）。"""

    player_id: str
    map_id: str
    row: int
    col: int
    location: Location
    description: str
    paths: list[ScenePath] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "map_id": self.map_id,
            "row": self.row,
            "col": self.col,
            "location": location_to_dict(self.location),
            "description": self.description,
            "paths": [p.to_dict() for p in self.paths],
        }


# ---------- 模板（复制预设） ----------


@dataclass
class WorldTemplate:
    """地块模板：复制预设，非继承。data 为模板负载 dict。

    目标存储策略：**同图目标存方向相对偏移**（{dr, dc}，放置时按地块位置平移）；
    **跨图目标存绝对 map_id+坐标**（{map_id, row, col}）原样复制。
    """

    id: str
    name: str
    data: dict[str, Any]


# ---------- 世界与组织（D15） ----------


@dataclass
class World:
    """世界：玩法包激活集合 + 数据边界（身份/账户全局，跨世界）。

    Attributes:
        id: 世界标识（如 "default"）。
        name: 显示名。
        desc: 描述。
        play_ids: 激活玩法包列表；空列表 = 全部激活。
    """

    id: str
    name: str
    desc: str = ""
    play_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "play_ids": list(self.play_ids),
        }


@dataclass
class WorldFolder:
    """组织树节点：世界内的多层纯管理组织（不参与玩法逻辑）。

    Attributes:
        id: 文件夹标识（uuid4 hex）。
        world_id: 所属世界。
        name: 显示名。
        parent_id: 父文件夹 id；None = 世界根。
        sort: 同层排序（小在前）。
    """

    id: str
    world_id: str
    name: str
    parent_id: str | None = None
    sort: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_id": self.world_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "sort": self.sort,
        }


# ---------- 实体（世界唯一居民概念，B12） ----------


@dataclass
class Entity:
    """世界中的实体：玩家 / agent / 布景实体统一模型。

    attrs 为玩法数据（hp/exp/gold/equipped...），state 为实体状态
    （门开/关、库存、血量...），内核都不解释，由玩法包自管。
    """

    id: str  # uuid4 hex（B5）
    map_id: str
    row: int
    col: int
    kind: str  # player / agent（内置）或玩法包注册的 kind
    name: str
    desc: str = ""
    attrs: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    user_id: str | None = None  # 身份化实体：账户/实例标识（联邦预留）
    last_active_ts: float = 0.0  # 在线状态（动作/SSE 活动维护）

    def pos_key(self) -> tuple[str, int, int]:
        return (self.map_id, self.row, self.col)

    def is_identity(self) -> bool:
        """身份化实体（可认证绑定、有背包、位置持久化）。"""
        return self.kind in ("player", "agent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "map_id": self.map_id,
            "row": self.row,
            "col": self.col,
            "kind": self.kind,
            "name": self.name,
            "desc": self.desc,
            "attrs": self.attrs,
            "state": self.state,
            "user_id": self.user_id,
            "last_active_ts": self.last_active_ts,
        }

    @staticmethod
    def from_dict(value: Any) -> Entity | None:
        """从存储/API dict 容错解析实体；非法返回 None。"""
        if not isinstance(value, dict):
            return None
        for key in ("id", "map_id", "kind", "name"):
            if not isinstance(value.get(key), str) or not value[key]:
                return None
        row, col = value.get("row"), value.get("col")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or not isinstance(col, int)
            or isinstance(col, bool)
        ):
            return None
        return Entity(
            id=value["id"],
            map_id=value["map_id"],
            row=row,
            col=col,
            kind=value["kind"],
            name=value["name"],
            desc=value.get("desc") if isinstance(value.get("desc"), str) else "",
            attrs=value.get("attrs") if isinstance(value.get("attrs"), dict) else {},
            state=value.get("state") if isinstance(value.get("state"), dict) else {},
            user_id=value.get("user_id")
            if isinstance(value.get("user_id"), str)
            else None,
            last_active_ts=value.get("last_active_ts", 0.0)
            if isinstance(value.get("last_active_ts"), (int, float))
            else 0.0,
        )


# ---------- 物品（定义与持有分离） ----------


@dataclass
class ItemDef:
    """物品定义：由玩法包注册（register_item_def），持久化到 items 表。"""

    id: str  # uuid4 hex（B5）
    name: str
    desc: str = ""
    icon: str = ""  # 可选，后议（B1：UI 以名称 + kind 标签展示）
    stackable: bool = True
    use_action: str | None = (
        None  # 玩法包注册的 use 交互动作（如 "eat"/"craft"/"equip"）
    )
    attrs: dict = field(default_factory=dict)  # 玩法数据（价格/属性/配方钩子）
    fields: list[dict] = field(default_factory=list)  # D9 字段 schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "icon": self.icon,
            "stackable": self.stackable,
            "use_action": self.use_action,
            "attrs": self.attrs,
            "fields": self.fields,
        }

    @staticmethod
    def from_dict(value: Any) -> ItemDef | None:
        if not isinstance(value, dict):
            return None
        for key in ("id", "name"):
            if not isinstance(value.get(key), str) or not value[key]:
                return None
        return ItemDef(
            id=value["id"],
            name=value["name"],
            desc=value.get("desc") if isinstance(value.get("desc"), str) else "",
            icon=value.get("icon") if isinstance(value.get("icon"), str) else "",
            stackable=value.get("stackable", True)
            if isinstance(value.get("stackable"), bool)
            else True,
            use_action=value.get("use_action")
            if isinstance(value.get("use_action"), str) and value["use_action"]
            else None,
            attrs=value.get("attrs") if isinstance(value.get("attrs"), dict) else {},
        )


# ---------- 实体 kind 注册（玩法包扩展点） ----------


@dataclass
class EntityKindSpec:
    """玩法包注册的实体 kind 元数据（register_entity_kind）。

    block_move 为内核级物理规则（移动阻挡）；interactions 为该 kind 默认可用的
    动作名列表（C3：可用动作 = kind 声明 ∪ 全局注册表）；tick 为行为状态机开关
    （玩法包同时订阅 on_tick 驱动状态）。label 为 kind 标签文案（B1）。
    fields 为 kind 声明字段 schema（D9：{name,label,type,default?}，UI 通用渲染）；
    categories 为分类标签（D10：宽松，无需预注册）。
    """

    kind: str
    block_move: bool = False
    interactions: tuple[str, ...] = ()
    tick: bool = False
    label: str = ""
    play_id: str = ""
    fields: list[dict] = field(default_factory=list)
    categories: tuple[str, ...] = ()


# ---------- 交互协议（玩法与 UI 之间的契约） ----------


@dataclass
class InteractionRequest:
    """一次交互请求：发起者与目标都是实体（含自己，如物品 use）。"""

    entity_id: str  # 发起者（身份化实体）
    target: Entity | None  # 目标实体（含玩家/agent 实体，如查看角色卡）
    action: str
    args: dict = field(default_factory=dict)
    item_id: str | None = None  # 物品交互（use）


@dataclass
class MenuButton:
    """交互结果中的动作按钮：label 展示，action/args 为下一次交互。"""

    label: str
    action: str
    args: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "action": self.action, "args": self.args}


@dataclass
class UiBlock:
    """界面块：内核按 schema 渲染，玩法包不画界面。

    kind 取值（B1 / B9）：text / menu / form / list / confirm / character /
    custom。character 与 custom 的结构数据放 ``data``：
    - character: {"avatar": str, "attrs": [{"label", "value"}]}（角色卡）
    - custom: {"component": "namespace.name", "props": {...},
      "fallback_text": "..."}（自定义界面组件，MCP 侧取 fallback_text 降级）
    blocks 为子块（B9 界面钩子注入点；内核渲染时按序展开）。
    """

    kind: str
    title: str = ""
    text: str = ""
    fields: list[dict] = field(default_factory=list)  # form: {name,label,type,required}
    items: list[dict] = field(default_factory=list)  # list: {label,value,action?,args?}
    actions: list[MenuButton] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # character/custom 附加结构
    blocks: list[UiBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "fields": self.fields,
            "items": self.items,
            "actions": [a.to_dict() for a in self.actions],
            "data": self.data,
            "blocks": [b.to_dict() for b in self.blocks],
        }


@dataclass
class InteractionResult:
    """交互结果（D12：仅 text + ui，无 effects——handler 命令式调原语）。"""

    text: str = ""
    ui: UiBlock | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "ui": self.ui.to_dict() if self.ui else None,
        }

    @staticmethod
    def from_dict(value: Any) -> InteractionResult | None:
        if not isinstance(value, dict):
            return None
        return InteractionResult(
            text=value.get("text") if isinstance(value.get("text"), str) else "",
            ui=None,  # UiBlock 解析（UI 协议层）
        )


class ShortCircuit:
    """原语过滤器短路值（G14）：包装直接作为原语结果返回。

    过滤器返回 ``ShortCircuit(value)`` 时，跳过后续过滤器与内核默认实现，
    ``value`` 即本次原语调用的结果（完全替换/遮蔽语义）。
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


# ---------- 事件表（内核唯一事件总线，单一事件源） ----------

# 事件名 → 订阅 handler 签名（均为 async，api 为 WorlditorPlayAPI 或 None）：
#   on_tick:           (api, dt)                          dt = 距上次执行秒数
#   on_entity_move:    (api, entity, from_pos, to_pos)
#   on_entity_enter:   (api, entity, map_id, row, col)
#   on_interact:       (api, request, result)
#   on_item_used:      (api, entity, item_id, args, result)   # D8：无 count
#   on_entity_removed: (api, entity)
#   on_entity_changed: (api, entity, changed)
#   on_world_edited:   (api, what)
WORLD_EVENTS: tuple[str, ...] = (
    "on_tick",
    "on_entity_move",
    "on_entity_enter",
    "on_interact",
    "on_item_used",
    "on_entity_removed",
    "on_entity_changed",
    "on_world_edited",
)

# 实体 id 序列化辅助（attrs/state JSON）


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def entity_db_row(entity: Entity) -> tuple:
    """entities 表写入行（与 store SQL 列序一致）。"""
    return (
        entity.id,
        entity.map_id,
        entity.row,
        entity.col,
        entity.kind,
        entity.name,
        entity.desc,
        entity.user_id,
        _dump_json(entity.attrs),
        _dump_json(entity.state),
        entity.last_active_ts,
    )


def entity_from_row(row: Any) -> Entity | None:
    """从 aiosqlite Row 解析实体（容错：json 损坏按空 dict）。"""
    return Entity.from_dict(
        {
            "id": row["id"],
            "map_id": row["map_id"],
            "row": row["row"],
            "col": row["col"],
            "kind": row["kind"],
            "name": row["name"],
            "desc": row["desc"],
            "user_id": row["user_id"],
            "attrs": _load_json(row["attrs_json"], {}),
            "state": _load_json(row["state_json"], {}),
            "last_active_ts": row["last_active_ts"],
        }
    )


def item_db_row(item: ItemDef) -> tuple:
    """items 表写入行。"""
    return (
        item.id,
        item.name,
        item.desc,
        item.icon,
        1 if item.stackable else 0,
        item.use_action,
        _dump_json(item.attrs),
    )


def item_from_row(row: Any) -> ItemDef | None:
    return ItemDef.from_dict(
        {
            "id": row["id"],
            "name": row["name"],
            "desc": row["desc"],
            "icon": row["icon"],
            "stackable": bool(row["stackable"]),
            "use_action": row["use_action"],
            "attrs": _load_json(row["attrs_json"], {}),
        }
    )
