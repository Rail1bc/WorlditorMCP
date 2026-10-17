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

import copy
import json
import math
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .errors import WorldError

DIRECTIONS = ("up", "right", "down", "left")

# ---------- 组件信封（D32 / D33；DESIGN §12.2） ----------
#
# 组件是实体**唯一的数据单位**：实体 = id + components（D32，取代 D9 的"字段化"）。
# 组件 key = ``source:name``——key 即身份，组件内部**不重复存** source/name。
COMPONENT_CORE = "core"
"""内核保留命名空间：**玩法包写入报错**（§12.2）；``core:`` 组件的写入不经分派表。"""
COMPONENT_LOCAL = "local"
"""编辑器 / 人手写的本地命名空间——虚构组件的落点（保证"信封必填"无例外）。"""

CORE_POSITION = "core:position"
"""内核协议组件：``{map_id, row, col}``——实体**在世界的哪里**（原三列表）。

**可选组件**（D36）：缺失 = 实体**不在世界上**（合法状态：玩家下线、收进容器、传送中）。
缺失语义：``Entity.map_id`` / ``row`` / ``col`` / ``pos_key()`` 一律返回 ``None``
（**不兜底成 ``""`` / ``0``**）；"必须在场"的路径用 ``require_position()``。
"""
CORE_PERCEPTION = "core:perception"
"""内核协议组件：感知（``invisible`` / ``see_invisible``，G1 / G12）。"""
CORE_INFO = "core:info"
"""内核协议组件：``name`` / ``desc``（原 ``entities.name`` / ``desc`` 列）。

缺失语义（§12.4）：``name`` 兜底为 ``id`` 前 8 位、``desc`` 为空。它主要供**内核自己的
文案**（lint / 删除保护 / 世界日志）使用；客户端要不要用它显示归玩法（D40）。
"""
CORE_ACCOUNT = "core:account"
"""内核协议组件：``{user_id}``——实体与账户的绑定（原 ``entities.user_id`` 列）。"""


@dataclass(frozen=True)
class CoreComponent:
    """``core:`` 组件的写入策略（K-7：**按组件声明**，不再按命名空间一刀切）。

    判据是"**写它有没有语义**"，不是"它在不在 ``core:`` 里"：

    - **数据组件**（``core:info``）：写它就是改数据——和写任何玩法包组件完全一样
      （合并 + 存储 + 发 ``on_entity_changed``），**没有任何不变量**，所以**可直写**。
    - **协议 / 动作组件**（``core:position`` / ``core:account`` / ``core:perception``）：
      直写会绕过语义（移动不发 ``on_entity_move``、账户绑定绕过两本账、感知绕过
      G12），所以**只能走内核的动作入口**——``use`` 就是"该用哪个"。
    """

    writable: bool = False
    use: str = ""


CORE_COMPONENTS: dict[str, CoreComponent] = {
    CORE_INFO: CoreComponent(writable=True),
    CORE_POSITION: CoreComponent(writable=False, use="move_entity / clear_position"),
    CORE_ACCOUNT: CoreComponent(writable=False, use="claim_avatar / release_avatar"),
    CORE_PERCEPTION: CoreComponent(writable=False, use="set_perception"),
}
"""内核组件的写入策略表。**缺省拦截**（fail-closed）：未列出的 ``core:`` 组件一律
拒绝——守卫的意义就是防"忘了声明"，而失败模式必须是"少一个能力"，
不能是"多一个后门"。"""


CORE_SHELL_MENU = "core:shell.menu"
"""**壳层挂载点**：页眉抽屉的列表（K-1）。

内核保留的**块 kind**（沿用 D33 的命名空间规则）。玩法包用
``register_ui_hook(CORE_SHELL_MENU, "after", provider)`` 往里放条目——例如玩家包
放一条「我」。**壳层自己不放内容**：

- 没有包 hook → 列表为空，但抽屉本体、遮罩、底部「退出登录」**照常工作**。那三样是
  壳层写死的、**不给玩法包**（退出登录被挪走就没有出口了）；
- 于是内核**永远不需要知道"玩家包"存在**——否则壳层就得硬编码调用 ``player:me``
  这个工具名，等于内核硬依赖一个玩法包（D48 想避免的事）。

**条目协议**（写法约定，内核不强制）：``title`` = 列表上显示的字；``icon`` = 图标；
``data["view"]`` = 点它跳哪个视图 key。⚠ **不是 ``action``**——``UiBlock.action``
至今没有执行者（渲染器只 ``emit``，壳层无人消费）。
"""

ATTR_INVISIBLE = "invisible"
"""``core:perception`` 内的字段：实体对普通 viewer 隐藏（G1 可见性通道）。"""
ATTR_SEE_INVISIBLE = "see_invisible"
"""``core:perception`` 内的字段：真视——viewer 带此字段为真时可看见 invisible 实体。"""

_COMPONENT_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def split_component_key(key: object) -> tuple[str, str]:
    """组件 key → ``(source, name)``；非法信封抛 ``WorldError``。

    source 可以是 ``core`` / ``local`` / 玩法包 id（``^[A-Za-z0-9_-]+$``，不含冒号）；
    name 允许字母数字与 ``_ . -``。分隔符用 ``:`` 是安全的（play_id 不含冒号）。
    """
    if not isinstance(key, str) or not key:
        raise WorldError("组件名必须是非空字符串")
    source, sep, name = key.partition(":")
    if not sep or not source or not name:
        raise WorldError(f"组件名必须是『来源:名字』形式（收到 {key!r}）")
    if not _COMPONENT_PART_RE.match(source) or not _COMPONENT_PART_RE.match(name):
        raise WorldError(f"组件名只允许字母/数字/下划线/点/连字符（收到 {key!r}）")
    return source, name


def is_core_component(key: object) -> bool:
    """是否内核保留组件（写入**不经分派表**，且玩法包不得写，§12.2 / D33）。"""
    return isinstance(key, str) and key.startswith(COMPONENT_CORE + ":")


def parse_components(value: Any) -> dict[str, dict]:
    """容错解析组件字典：key 必须是合法信封、值必须是对象，否则丢弃该条。

    用于 ``from_dict``（API 输入）与列解析；**落库路径**的坏值由 store 的
    ``IncompatibleDataError`` 单独处理（拒绝启动，不静默丢弃，D13）。
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict] = {}
    for key, data in value.items():
        try:
            split_component_key(key)
        except WorldError:
            continue
        if isinstance(data, dict):
            out[str(key)] = dict(data)
    return out


# 方向 ↔ 坐标偏移（行, 列）：up=行-1 / down=行+1 / left=列-1 / right=列+1。
# 权威定义；前端视图组件按此约定渲染网格（参考实现：
# tests/fixtures/plays/worlditor_play_demo/web/view.js——原生内置视图组件已随
# 内置玩法包一并废弃，v0.7.0）。
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


_SCHEDULE_HINT = (
    '文案格式：{"periods": [{"start": "00:00", "end": "24:00", '
    '"items": [{"text": "文本", "weight": 1}]}]}'
)


def parse_text_schedule(value: Any) -> TextSchedule:
    """解析结构化文案（TextSchedule）。**只认一种格式**（v0.5.2 起）。

    接受：``None``（= 无文案，返回默认空调度）、``{"periods": [...]}``。
    拒绝：**纯字符串**（历史上是"全天单条"的简写——同一份数据两种写法，
    必然引出"读进来是文本、存回去结构变了"这类静默丢失，故取消）、
    以及任何结构非法的值（**报错，不再静默丢弃条目**——静默丢字段正是
    D23/G24 要根除的那类问题）。

    读取路径不存在需要容忍的历史形态：库里写的一律是 ``TextSchedule.to_dict()``
    的产物（写入前必经本函数）。
    """
    if value is None:
        return TextSchedule()
    if not isinstance(value, dict):
        raise WorldError(f"{_SCHEDULE_HINT}（收到 {type(value).__name__}）")
    raw_periods = value.get("periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        raise WorldError(f"periods 必须是非空数组。{_SCHEDULE_HINT}")
    periods: list[TextPeriod] = []
    for index, raw_period in enumerate(raw_periods, 1):
        if not isinstance(raw_period, dict):
            raise WorldError(f"第 {index} 个时段必须是对象。{_SCHEDULE_HINT}")
        start = str(raw_period.get("start") or "00:00")
        end = str(raw_period.get("end") or "24:00")
        try:
            _parse_minutes(start)
            _parse_minutes(end)
        except ValueError:
            raise WorldError(
                f"第 {index} 个时段的时间非法：{start}–{end}（需 HH:MM，00:00–24:00）"
            ) from None
        raw_items = raw_period.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise WorldError(f"第 {index} 个时段的 items 必须是非空数组")
        items: list[TextItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise WorldError(f"第 {index} 个时段的 items 条目必须是对象")
            text = raw_item.get("text")
            if not isinstance(text, str) or not text:
                raise WorldError(f"第 {index} 个时段有条目缺少非空 text")
            weight = raw_item.get("weight", 1.0)
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise WorldError(f"第 {index} 个时段的 weight 必须是数字")
            parsed_weight = float(weight)
            if not math.isfinite(parsed_weight) or parsed_weight <= 0:
                raise WorldError(f"第 {index} 个时段的 weight 必须是正的有限数字")
            items.append(TextItem(text, parsed_weight))
        periods.append(TextPeriod(start, end, items))
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

    visible（G1）：public = 所有人可见；private = 仅该图上有自己那个实体
    的玩家（+admin）可见——家地图/对局地图用 private 隐藏内容。

    ⚠ **没有"出生点"**（D45）：原 ``spawn_row`` / ``spawn_col`` 两个字段已删除。
    内核不指定"新角色落在哪"——落点是**玩法包**的事（它自己挑地块再
    ``place_entity`` / ``move_entity``），内核连"新角色"这个概念都没有。
    """

    id: str
    name: str
    description: TextSchedule | None = None
    timezone: str | None = None
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
    return WorldMap(
        id=id_,
        name=name.strip(),
        description=description,
        timezone=str(tz) if isinstance(tz, str) and tz else None,
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
    """模板（D22：地块与实体共用一个"模板"概念，用 scope 区分）。

    - ``scope="location"``：地块预设（复制预设，非继承）。目标存储策略：
      **同图目标存方向相对偏移**（{dr, dc}，放置时按地块位置平移）；
      **跨图目标存绝对 map_id+坐标**（{map_id, row, col}）原样复制。
    - ``scope="entity"``：实体预设。data = ``{name, desc, components}``
      （v2/D32：原 attrs/state 两容器已取消；**D41：类型预设 = 一组组件的预设**，
      所以"类型"这个概念在这里而不是在实体上；套用后仍可改）；玩法包注册的实体模板
      在内存注册表（随包卸载消失），管理端本地模板落这张表——这条"包声明 vs 本地数据"
      的区分正好顶替了 D37 之前"管理员手工物品定义"的位置。
    """

    id: str
    name: str
    data: dict[str, Any]
    scope: str = "location"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "data": self.data,
            "scope": self.scope,
        }


# ---------- 世界与组织（D15） ----------


@dataclass
class World:
    """世界：玩法包激活集合 + 数据边界（身份/账户全局，跨世界）。

    Attributes:
        id: 世界标识（如 "default"）。
        name: 显示名。
        desc: 描述。
        play_ids: 激活玩法包列表——**三种状态各自可表达**（v0.9 / D55）：
            ``None`` = **全部启用**（新世界的默认）；``[]`` = **一个都不启用**；
            非空列表 = 只启用这些。旧版用"空列表"同时表达"还没配"和"全部"，
            那正是 D36 反对的"把缺失当语义"。
    """

    id: str
    name: str
    desc: str = ""
    play_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "play_ids": None if self.play_ids is None else list(self.play_ids),
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

    **组件（D32）**：``components`` 是实体**唯一的数据单位**——``{组件名: 数据}``，
    组件名 = ``source:name`` 信封（D33）。``attrs`` / ``state`` 两个扁平容器已取消，
    内核自己的协议数据放 ``core:`` 命名空间（``core:position`` / ``core:info`` /
    ``core:perception`` / ``core:account``）。

    **位置**（``core:position``，D36）：**可选**组件——缺失 = 实体**不在世界上**
    （合法状态，如玩家下线）。``map_id`` / ``row`` / ``col`` / ``pos_key()`` 是**只读
    派生视图**，缺失时返回 ``None``（**不返回 ``""`` / ``0`` 兜底**——那会把"缺失"变成
    静默错误）。"必须在场"的路径请用 ``require_position()``。

    **名字与描述**（``core:info``）：同样是组件；``name`` / ``desc`` 以只读 property
    暴露，缺失时 ``name`` 兜底为 ``id`` 前 8 位（§12.4）。

    **能力 = 组件的存在**（D41）：实体带了某个组件键就具备那条能力——纯能力组件的数据
    是 ``{}``（合法且常见）。所以**没有** ``kind`` / ``tags`` 这类"基底类型"字段：
    想表达"这是一头狼"，就带上 ``bestiary:wolf`` 组件；"类型 = 一组组件的预设"归
    **实体模板**（D22）。
    """

    id: str  # uuid4 hex（B5）
    components: dict[str, dict] = field(default_factory=dict)
    last_active_ts: float = 0.0  # 在线状态（动作/SSE 活动维护）
    # 变更检测（D28）：内核在**落库那一刻**盖章，玩法包/客户端据此刻画增量
    revision: int = 0  # 全局单调变更号（每次写 +1；重启后从库里最大值续号）
    changed_tick: int = 0  # 最近一次变更所在的 tick 窗口（query(changed_since_tick=)）

    # ---------- 位置：``core:position`` 的只读派生视图（D36） ----------

    @property
    def map_id(self) -> str | None:
        """所在地图；**实体不在世界上时返回 ``None``**（不是空串）。"""
        value = self.component(CORE_POSITION).get("map_id")
        return value if isinstance(value, str) and value else None

    @property
    def row(self) -> int | None:
        """所在行；不在世界上时返回 ``None``（不是 0）。"""
        value = self.component(CORE_POSITION).get("row")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def col(self) -> int | None:
        """所在列；不在世界上时返回 ``None``（不是 0）。"""
        value = self.component(CORE_POSITION).get("col")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def has_position(self) -> bool:
        """实体是否**在世界上**（三个字段齐全）。"""
        return self.map_id is not None and self.row is not None and self.col is not None

    def pos_key(self) -> tuple[str, int, int] | None:
        """``(map_id, row, col)``；**不在世界上时返回 ``None``**。

        调用方必须显式处理 ``None``——这是 D36 的核心语义，别用 ``or (0, 0)`` 之类兜底。
        """
        if not self.has_position():
            return None
        return (self.map_id, self.row, self.col)  # type: ignore[return-value]

    def require_position(self) -> tuple[str, int, int]:
        """取位置，**缺失即报错**——给"必须在场"的路径用（`move` / 场景构建 / lint 定位）。

        用显式的 ``require_`` 而不是让属性抛错：这样"哪些路径要求在场"在代码里一眼可辨，
        而不是靠读每个 ``map_id`` 的用法去猜。
        """
        key = self.pos_key()
        if key is None:
            raise WorldError(f"实体不在任何地块：{self.id}")
        return key

    def set_position(self, map_id: str, row: int, col: int) -> None:
        """写 ``core:position``（原地改组件；落库由调用方的 ``save_entity`` 负责）。"""
        self.components = {
            **self.components,
            CORE_POSITION: {"map_id": map_id, "row": row, "col": col},
        }

    def clear_position(self) -> None:
        """清掉位置 = 让实体**离开世界**（下线/收进容器/hold；D36）。"""
        self.components = {
            k: v for k, v in self.components.items() if k != CORE_POSITION
        }

    def component(self, key: str) -> dict:
        """读取组件数据的副本；调用方不能通过返回值修改实体。"""
        data = self.components.get(key)
        return copy.deepcopy(data) if isinstance(data, dict) else {}

    def has_component(self, key: str) -> bool:
        """是否带某个组件 —— **这就是"有没有这条能力"**（D41）。

        不能用 ``component(key) == {}`` 代替：纯能力组件的数据本来就是 ``{}``，
        "带了一个空组件"与"没有这个组件"必须分得开。
        """
        return key in self.components

    @property
    def name(self) -> str:
        """显示名 = ``core:info.name``；缺失 → **``id`` 前 8 位**（§12.4 的兜底语义）。

        这是**只读派生视图**：写入请用 ``set_data(..., "name", component=CORE_INFO)``
        或 ``update_entity(name=…)``。之所以留这个 property：内核自己的文案
        （lint / 删除保护 / 世界日志）必须有名字可用，兜底逻辑只该有一份。
        """
        value = self.component(CORE_INFO).get("name")
        return value if isinstance(value, str) and value else self.id[:8]

    @property
    def desc(self) -> str:
        """描述 = ``core:info.desc``；缺失 → 空串。只读派生视图（同 ``name``）。"""
        value = self.component(CORE_INFO).get("desc")
        return value if isinstance(value, str) else ""

    @property
    def user_id(self) -> str | None:
        """账户绑定 = ``core:account.user_id``；缺失 → ``None``（这个实体没有账户）。

        只读派生视图：写入请用 ``place_entity(user_id=…)`` 或身份服务的受控通道。
        """
        value = self.component(CORE_ACCOUNT).get("user_id")
        return value if isinstance(value, str) and value else None

    def is_account_bound(self) -> bool:
        """**绑定了账户的实体**（带 ``core:account``）——D14 红线（v2 / D42 起）的判据。

        **不是"身份"**：内核没有"身份"这个概念（D42 已把 `IDENTITY_KINDS` 整个删除）。
        这条只回答一个数据事实：它绑着一个可登录的账户吗？绑了就不许玩法包删
        （删掉会让 token 悬空），`delete_map` / `copy_map` / `delete_location`
        也用它避免误伤"有人操作的实体"。

        为什么比原来的 `kind == "player"` 更准：那是**代理判据**——
        一个没绑账户的 `player` 实体会白挡删图，而一个绑了账户却换了 kind 的实体反而不挡。
        账户绑定本来就是真正起作用的事实（`identity_entity_of` / `delete_account` 一直按它找）。
        """
        return self.user_id is not None

    def to_dict(self) -> dict[str, Any]:
        """线上投影＝**模型实况**（D41：**5 键**）：``id`` + ``components`` + 三个元信息。

        名字/描述/账户绑定/位置都在 ``components`` 里，不在顶层（§12.4）；能力也在
        ``components`` 里（组件的存在即能力，D41）——所以没有 ``kind`` / ``tags``。
        内核自己的文案与"在不在场"走 ``Entity.name`` / ``Entity.map_id`` 这些带缺失
        语义的只读 property。
        """
        return {
            "id": self.id,
            "components": self.components,
            "last_active_ts": self.last_active_ts,
            "revision": self.revision,
            "changed_tick": self.changed_tick,
        }

    @staticmethod
    def from_dict(value: Any) -> Entity | None:
        """从存储/API dict 容错解析实体；非法返回 None。

        **输入便利**：顶层 ``name`` / ``desc`` / ``user_id`` 折进 ``core:info`` /
        ``core:account``；顶层 ``map_id`` + ``row`` + ``col`` 折进 ``core:position``
        （三者**要么都给、要么都不给**——只给一半说明数据坏了 → None）。
        内部与落库只有一种形态——组件；不会出现"两处存同一事实"。

        **位置是可选的**（D36）：三个键都不给 = 实体不在世界上，这是合法输入。
        **能力也是组件**（D41）：没有 ``kind`` / ``tags`` 这类输入键，要带能力就在
        ``components`` 里给组件键。
        """
        if not isinstance(value, dict):
            return None
        if not isinstance(value.get("id"), str) or not value["id"]:
            return None
        components = parse_components(value.get("components"))
        map_id = value.get("map_id")
        row, col = value.get("row"), value.get("col")
        given = [map_id is not None, row is not None, col is not None]
        if any(given):
            if not all(given):
                return None  # 位置只给了一半 → 坏数据
            if not isinstance(map_id, str) or not map_id:
                return None
            if (
                not isinstance(row, int)
                or isinstance(row, bool)
                or not isinstance(col, int)
                or isinstance(col, bool)
            ):
                return None
            components = {
                **components,
                CORE_POSITION: {"map_id": map_id, "row": row, "col": col},
            }
        info: dict[str, Any] = {}
        if isinstance(value.get("name"), str) and value["name"]:
            info["name"] = value["name"]
        if isinstance(value.get("desc"), str) and value["desc"]:
            info["desc"] = value["desc"]
        if info:
            components = {
                **components,
                CORE_INFO: {**components.get(CORE_INFO, {}), **info},
            }
        if isinstance(value.get("user_id"), str) and value["user_id"]:
            components = {
                **components,
                CORE_ACCOUNT: {"user_id": value["user_id"]},
            }
        return Entity(
            id=value["id"],
            components=components,
            last_active_ts=value.get("last_active_ts", 0.0)
            if isinstance(value.get("last_active_ts"), (int, float))
            else 0.0,
            revision=_nonneg_int(value.get("revision")),
            changed_tick=_nonneg_int(value.get("changed_tick")),
        )


def _nonneg_int(value: Any) -> int:
    """非负整数解析（布尔/负数/坏类型 → 0；D28 变更号容错）。"""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def parse_names(value: Any) -> list[str]:
    """组件名/键列表解析（写入边界的裸名输入）：非字符串 / 空串丢弃，去重保序。

    **去重保序**很重要——`place_entity(tags=[...])` 的顺序就是组件在实体字典里的顺序，
    不能随便排序（同一份输入要落出同一份组件字典）。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in out:
            out.append(name)
    return out


# ---------- 物品：**已不在内核**（v2 / D37 取代 D8） ----------
#
# 这里原来有 `ItemDef`（物品类型定义），内核另有一张 `items` 表。v2 起**物品定义与持有
# 都下沉玩法包**——内核只有实体：
#   - 物品**类型** → 用**组件声明**表达（`register_entity_tag`：名字 + 字段 schema + 归属；
#     归属与卸载清理沿用注册表既有机制）
#   - 物品**实例** → **实体 + 组件**（"一个苹果在地上" = 一个实体带苹果组件）
#   - `use_action` → **interaction 名**（`TagSpec.interactions` 完全覆盖）
#   - `stackable` / `icon` → 组件声明的属性与字段
#   - 管理员手工维护的物品 → **实体模板**（`templates` 表 `scope="entity"`，已持久化、可编辑）
#   - `InteractionRequest.item_id` 槽位 → **`args`**（自由 dict）
#   - `on_item_used` 内核事件 → 玩法包**自定义事件**（事件总线本就支持任意事件名）
# 理由与逐项对照见 DESIGN §12.8 / D37；**落点是"组件声明"，不是包私有 KV**
# （否则跨包共享能力会真的丢失，回到 G6/G39 那个"包间契约没有系统表示"的坑）。


# ---------- 组件声明（玩法包扩展点，D41） ----------


@dataclass
class TagSpec:
    """**组件声明**（D41：原来"类型 / 标签"两套声明合并成这一套）。

    **组件名自带来源**：``key = source:name``——来源进名字，所以两个包各声明
    ``merchant`` 是**两个组件共存**，不存在"后注册覆盖"，也没有"同名"这回事。
    ``source`` / ``name`` 从键里派生（归属的唯一事实来源就是键，D44）。

    字段语义：
    - ``interactions``：该组件默认可用的动作名（C3：可用动作 = 组件声明 ∪ 全局注册表）；
    - ``label``：文案（B1）；
    - ``play_id``：声明者——能力面按**世界激活**逐个组件过滤（D21）；
    - ``fields``：组件声明的字段 schema（D9：{name,label,type,default?}，UI 通用渲染）；
      字段清单**按组件分组**，不跨组件摊平（D41）——同一组件内同名字段只能声明一次；
    - ``categories``：选取分组（D10：宽松，无需预注册；**不再承载字段**，D41）。
    """

    key: str
    interactions: tuple[str, ...] = ()
    label: str = ""
    play_id: str = ""
    fields: list[dict] = field(default_factory=list)
    categories: tuple[str, ...] = ()

    @property
    def source(self) -> str:
        """组件来源；组件键是唯一事实来源。"""
        return self.key.split(":", 1)[0]

    @property
    def name(self) -> str:
        """组件的裸名部分。"""
        return self.key.split(":", 1)[1]


# ---------- 交互协议（玩法与 UI 之间的契约） ----------


@dataclass
class InteractionRequest:
    """一次交互请求：发起者与目标都是实体（含自己，如物品 use）。"""

    entity_id: str  # 发起者（带 core:account 的实体）
    target: Entity | None  # 目标实体（含玩家/agent 实体，如查看角色卡）
    action: str
    args: dict = field(default_factory=dict)
    # v2 / D37：原 `item_id` 槽位已删除——物品不在内核，玩法包把它的标识放进 `args`
    # （如 `args={"item": "apple"}`）。内核不解释 args 的内容。


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
      "fallback_text": "..."}——**仅保留 fallback 数据结构**：前端渲染器当前只显示
      fallback_text，``component`` / ``props`` 无人消费。要自定义界面请用
      ``register_view``（provider 组件）；要往块里加内容用 ``register_ui_hook``。
    blocks 为子块（B9 界面钩子注入点；内核渲染时按序展开）。

    ``icon``（v0.9）：**给宿主用的标签图标**（抽屉条目、底栏 tab 等）。内核不解释它；
    留空 = 不显示。之所以放在块上而不是 ``data`` 里，是因为"块被当成一个标签条目
    渲染"是宿主侧的通用模式（``title`` + ``icon``），不该让每个宿主各自约定。
    """

    kind: str
    title: str = ""
    icon: str = ""  # 图标（emoji / 短字符）；宿主按需使用，内核不解释
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
            "icon": self.icon,
            "text": self.text,
            "fields": self.fields,
            "items": self.items,
            "actions": [a.to_dict() for a in self.actions],
            "data": self.data,
            "blocks": [b.to_dict() for b in self.blocks],
        }


@dataclass
class Principal:
    """**主体**（可登录的账户）——**不是实体**（D46/D47）。

    主体有哪些化身是**玩法包**的事；内核只在主体生命周期事件里把它原样递过去，
    让包能按稳定的键去清/建自己的 roster。``username`` 是显示名（与 ``accounts``
    表同一份数据），``account_id`` 才是键。
    """

    account_id: str
    username: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "username": self.username}


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
#   on_entity_removed: (api, entity)
#   on_entity_changed: (api, entity, changed)
#   on_world_edited:   (api, what)
#   on_principal_login / _logout / _deleted: (api, principal)   principal = Principal
# （原 `on_item_used` 已随 D37 移除——物品不在内核，"用了一个东西"由玩法包发自定义事件）
WORLD_EVENTS: tuple[str, ...] = (
    "on_tick",
    "on_entity_move",
    "on_entity_enter",
    "on_interact",
    "on_entity_removed",
    "on_entity_changed",
    "on_world_edited",
)

# 主体生命周期事件（D47；7 → 10）。**主体 = 可登录的账户，不是实体**：
#   on_principal_login:   登录成功（凭据已发；玩法包可据此"让化身入场"/记住选中项）
#   on_principal_logout:  一份凭据被吊销（玩法包可据此"让化身离场"）
#   on_principal_deleted: 账户永久注销（内核已删该主体的全部化身，玩法包清自己的 roster）
# 三条都**不做世界激活过滤**（主体不绑位置、不属于任何世界）也**不推 SSE**
# （"谁登录了"广播给所有订阅者 = 把名册发给每个玩家）。
PRINCIPAL_EVENTS: tuple[str, ...] = (
    "on_principal_login",
    "on_principal_logout",
    "on_principal_deleted",
)

# 事件执行的阶段（D27：跨包顺序声明化，不再依赖"包加载序"这个隐式事实）。
# 同一事件内排序键 = (阶段, order, 注册序)；未给阶段 → simulate。
EVENT_PHASES: tuple[str, ...] = ("input", "simulate", "present")
DEFAULT_EVENT_PHASE = "simulate"

# 实体 / 组件序列化辅助（组件字典）


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
    """entities 表写入行（与 store SQL 列序一致；D28 两列在末尾、表 v11 共 4 列）。

    v2：名字/描述/账户绑定/位置都已进 ``components``（``core:info`` / ``core:account``
    / ``core:position``），**能力同样是组件**（D41）——所以这张表**只有** ``id`` /
    ``components_json`` / ``revision`` / ``changed_tick``。
    """
    return (
        entity.id,
        _dump_json(entity.components),
        entity.revision,
        entity.changed_tick,
    )


def entity_from_row(row: Any) -> Entity | None:
    """从 aiosqlite Row 解析实体（容错：json 损坏按空 dict；缺列按 0）。

    ``last_active_ts`` **不在表里**（v11：在线状态只在内存），重开后从 0 起。
    """
    return Entity.from_dict(
        {
            "id": row["id"],
            "components": _load_json(row["components_json"], {}),
            # D28 后加列：老库 / 测试假行可能没有这两列
            "revision": _row_get(row, "revision", 0),
            "changed_tick": _row_get(row, "changed_tick", 0),
        }
    )


def _row_get(row: Any, key: str, default: Any) -> Any:
    """行取值容错（缺列 → 默认值；老库与测试假行都要能读）。"""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default
