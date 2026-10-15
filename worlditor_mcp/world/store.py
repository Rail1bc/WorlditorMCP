"""SQLite 持久化层（aiosqlite，真异步；设计见 DESIGN.md）。

全部表（地图/地块/连接/模板 + 实体/数据 KV/日志 + 世界/组织/身份/凭据）
建在同一个 world.db；启动时全量载入内存（读路径快、免锁），写操作由调用方
（WorldEngine）在实例锁内执行，本类不自行加锁。

内核不播种世界内容；地图与实体由玩法包或管理端创建。
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from .errors import IncompatibleDataError, WorldError
from .identity import Account, TokenInfo
from .model import (
    Entity,
    Location,
    Target,
    World,
    WorldFolder,
    WorldMap,
    WorldTemplate,
    entity_db_row,
    entity_from_row,
    location_to_dict,
    parse_location,
    parse_map,
    parse_text_schedule,
    split_component_key,
)

# 表结构版本（D13：**无迁移逻辑**——读到别的版本直接拒绝启动，见 ``_check_schema``）。
# v5 = world_maps.sort：组织树内地图与文件夹共用一个排序空间
# v6 = entities.tags_json（D18 实体标签）+ templates.scope（D22 模板统一）
# v7 = entities.revision / changed_tick（D28 变更检测）+ world_meta['revision']
# v8 = entities.components_json（D32：实体 = id + 组件；attrs_json/state_json 取消）
# v9 = entities 去掉 name / desc / user_id 三列（D32 §12.4：它们进 core:info / core:account）
# v10 = entities 去掉 map_id / row / col 三列（D36 §12.4：位置进 core:position，可为缺失）
# v11 = entities 去掉 kind / tags_json 两列（D41：能力 = 组件的存在，表 4 列）
SCHEMA_VERSION = "11"
DEFAULT_MAP_ID = "default"

# 后加列清单——**不是用来补的，是用来检查的**（`_check_schema`）。
# 这是原 `_ensure_columns`（缺列就 ALTER 补上）的替代物：补列会把旧数据静默改成
# 新形态（v2 尤其致命——补出来的 components_json 是空默认值 = 实体数据被清空），
# 所以改成"缺任何一列 = 明确拒绝启动，指名删哪个文件"。
_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "world_maps": ("sort",),
    "entities": ("revision", "changed_tick", "components_json"),
    "templates": ("scope",),
}

# 「**不该存在**」的列（同样只在启动闸里用）。它们守的是**静默丢数据**的另一半：
# 一个没有版本记录的库如果还带着更早版本的列（name/desc/user_id、map_id/row/col，
# 或 v11 之前的 kind/tags_json），只查"需要的列在不在"是查不出来的——载入会成功，
# 而名字/描述/账户绑定或**能力归属**被无声丢掉。所以显式拒绝。
_FORBIDDEN_COLUMNS: dict[str, tuple[str, ...]] = {
    "entities": (
        "name",
        "desc",
        "user_id",
        "map_id",
        "row",
        "col",
        "kind",
        "tags_json",
    ),
}

# 世界日志保留上限（超出后裁掉最旧记录；防高频事件刷爆库）
WORLD_LOG_LIMIT = 5000

# 内核不内置任何世界内容（v0.2.0）：地图/地块/实体由玩法包导入
# （参考世界包 worlditor_play_demo_world）或用户经管理端地图编辑器创建。


def _int_or_zero(value: object) -> int:
    """world_meta 里的数字串 → int（坏值按 0）。"""
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


# ---------- 不兼容数据的定位（只在启动失败路径调用） ----------
#
# 语义：**严格拒绝，不做迁移**（D13）。这一组函数不改变"拒绝"这个结论，只负责把
# 「哪一行、哪个字段读不了」指出来——否则运维拿到的是一屏 60 行 traceback，而真正
# 有用的信息只有最后一句"（收到 str）"。
#
# 做法：把该行**逐字段单独解析一遍**，谁抛错就报谁。只在已经确定失败时执行，
# 所以正常启动路径上一分钱不花。

_PARSE_ERRORS = (WorldError, ValueError, TypeError)


def _bad_map_field(description: Any) -> str:
    """地图行里的坏字段名（`description` 或"整行"= 行本身不合法）。"""
    if description is not None:
        try:
            parse_text_schedule(description)
        except _PARSE_ERRORS:
            return "description"
    return "整行（id / 名称 / 出生点等）"


def _bad_location_field(payload: dict) -> str:
    """地块行里的坏字段名（描述 → 各方向路径的 label → 整行）。"""
    description = payload.get("description")
    if description is not None:
        try:
            parse_text_schedule(description)
        except _PARSE_ERRORS:
            return "description"
    connections = payload.get("connections")
    if isinstance(connections, dict):
        for direction, slot in connections.items():
            if not isinstance(slot, dict):
                continue
            for index, path in enumerate(slot.get("paths") or []):
                if not isinstance(path, dict) or path.get("label") is None:
                    continue
                try:
                    parse_text_schedule(path["label"])
                except _PARSE_ERRORS:
                    return f"connections.{direction}.paths[{index}].label"
    return "整行（行列号 / 名称 / 连接结构等）"


# ---------- 表 SQL ----------

# 实体/身份/世界层：实体、物品、玩法数据、日志、账户、凭据、世界与组织
_ENTITY_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    components_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 0,
    changed_tick INTEGER NOT NULL DEFAULT 0
);
-- v2（D32）：实体表只留"存储与治理"需要的列——位置/名字/描述/账户绑定都在 components 里
-- （``core:position`` / ``core:info`` / ``core:account``，D36/§12.4）。
-- v11（D41）：``kind`` / ``tags_json`` 两列删除——**能力 = 组件的存在**，
-- 实体带某组件即具备该能力（纯能力组件的数据是 ``{}``）。
-- ``last_active_ts`` 也**不落库**：它是"在线状态"（内存里由动作/SSE 活动维护），
-- 重启后从 0 重新计——这与"实体数据"不同，没必要让进程生命周期以外的人看见。
-- 原 idx_entities_pos 已删——实测**无任何 SQL 使用它**（实体相关 SQL 只有 SELECT * 与
-- DELETE WHERE id），位置筛选一律走内存（索引策略见 D39 / GAPS G42）。
-- v2 / D37：原 `items` 表已删除——物品不在内核（定义 → 组件声明，实例 → 实体 + 组件）。
CREATE TABLE IF NOT EXISTS play_data (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE TABLE IF NOT EXISTS world_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    entity_id TEXT,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_log_entity ON world_log(entity_id);
-- 身份（B13 自助注册 / B4 token 三档）
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    kind TEXT NOT NULL,
    account_id TEXT,
    username TEXT,
    created_ts REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    used INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL
);
-- 世界与组织（D15）：世界 = 玩法包激活集合；组织树纯管理；地图归属
CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    play_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS world_folders (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    parent_id TEXT,
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS world_maps (
    map_id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    folder_id TEXT,
    sort INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_WORLD_ID = "default"

# 地图层：地图 / 地块 / 模板 / 世界元数据
_MAP_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS maps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description_json TEXT,
    timezone TEXT,
    spawn_row INTEGER NOT NULL DEFAULT 0,
    spawn_col INTEGER NOT NULL DEFAULT 0,
    visible TEXT NOT NULL DEFAULT 'public'
);
CREATE TABLE IF NOT EXISTS locations (
    map_id TEXT NOT NULL,
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    name TEXT NOT NULL,
    description_json TEXT,
    conns_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (map_id, row, col)
);
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'location'
);
CREATE TABLE IF NOT EXISTS world_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class WorldStore:
    """worlditor SQLite 持久化 + 内存态（启动时全量载入）。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        # 内存态快照
        self.maps: dict[str, WorldMap] = {}
        self.loc_by_pos: dict[tuple[str, int, int], Location] = {}
        self.templates: dict[str, WorldTemplate] = {}
        self.entities: dict[str, Entity] = {}
        self.play_data: dict[tuple[str, str], Any] = {}
        self.accounts: dict[str, Account] = {}
        self.tokens: dict[str, TokenInfo] = {}
        self.invite_codes: dict[str, dict] = {}
        # 世界与组织（D15）
        self.worlds: dict[str, World] = {}
        self.folders: dict[str, WorldFolder] = {}
        self.map_world: dict[str, str] = {}  # map_id -> world_id
        self.map_folder: dict[str, str | None] = {}  # map_id -> folder_id | None
        self.map_sort: dict[str, int] = {}  # map_id -> 组织树内的序号
        self.world_meta: dict[str, str] = {}  # world_meta 表内存态
        # D28 变更检测：全局单调变更号 + 当前 tick 窗口（_load_all 从库中续号）
        self.revision = 0
        self.tick = 0

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        """打开连接、建表、**版本闸**、幂等播种、全量载入内存。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(_MAP_TABLES_SQL)
        await self._conn.executescript(_ENTITY_TABLES_SQL)
        # D13 版本闸：**先于一切读与写**。旧版本库在这里就被拒绝——绝不能让后续步骤
        # 用"ALTER 补列"或默认值把旧数据悄悄改成新形态（v2 起实体列变了，
        # 补出来的 components_json 是空默认值 = 旧实体数据被静默清空）
        await self._check_schema()
        # D28：**在任何启动写之前**续号——迁移/播种的提交也会推进变更号，
        # 先读旧号才能保证"结构变更多于实体变更"的库重启后号不回退
        await self._resume_revision()
        await self._seed_if_empty()
        await self._load_all()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---------- 变更检测（D28） ----------

    def next_revision(self) -> int:
        """推进并返回全局变更号（不落盘；``_commit`` 在同一事务里写 world_meta）。"""
        self.revision += 1
        return self.revision

    async def _resume_revision(self) -> None:
        """启动时从 world_meta 续变更号（在任何写之前调用；表不存在则按 0）。"""
        assert self._conn is not None
        try:
            cur = await self._conn.execute(
                "SELECT value FROM world_meta WHERE key = 'revision'"
            )
            row = await cur.fetchone()
        except Exception:  # noqa: BLE001 —— 老库/表缺失：从 0 起算
            row = None
        self.revision = _int_or_zero(row["value"]) if row is not None else 0

    async def _commit(self) -> None:
        """提交当前写事务，并把变更号一起落盘（D28）。

        变更号在**同一事务**里 UPSERT 到 world_meta，所以重启后单调不回退——
        客户端拿着旧 revision 也不会因为"重启后计数归零"而误判"世界没变"
        （漏报是这类机制里唯一不可接受的错）。
        """
        assert self._conn is not None
        self.revision += 1
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_meta(key, value) VALUES('revision', ?)",
            (str(self.revision),),
        )
        await self._conn.commit()

    async def _check_schema(self) -> None:
        """版本闸（D13）：库的表结构版本或**表形态**与本版本不符 → **拒绝启动**。

        两道检查，缺一不可：

        1. ``world_meta.schema_version`` 记录不符 → 拒绝；
        2. **后加列清单**（``_REQUIRED_COLUMNS``）缺任何一列 → 拒绝。
           第 2 道是给"**连版本记录都没有的极老库 / 手造库**"兜底的——只靠第 1 道的话，
           那种库会一路走到 ``_load_all`` 撞出裸 ``IndexError``（一屏栈、没有可操作的
           指引），正好违背 D13 承诺的"读到不兼容内容就指明删哪个文件"。

        为什么必须有这道闸：v2 起 ``entities`` 的列变了（``components_json`` 取代
        ``attrs_json`` / ``state_json``）。若沿用"缺列就 ALTER 补上"的旧做法
        （原 ``_ensure_columns``），补出来的列是**空默认值**——旧实体的数据会被
        **静默清空**，比拒绝启动危险得多（D23"不静默丢数据"的同一条原则）。
        所以那个补列函数**已被删除，改成这里的检查**。

        空库 / 全新库（无版本记录、表由本版本 DDL 建出）放行。
        """
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT value FROM world_meta WHERE key = 'schema_version'"
        )
        row = await cur.fetchone()
        if row is not None:
            found = str(row["value"])
            if found != SCHEMA_VERSION:
                raise self._refuse(
                    f"库的表结构版本是 v{found}，本版本需要 v{SCHEMA_VERSION}"
                    f"（实体数据形态已在 v2 变更：实体 = id + 组件，DESIGN D32）"
                )
        missing: list[str] = []
        for table, columns in _REQUIRED_COLUMNS.items():
            cur = await self._conn.execute(f"PRAGMA table_info({table})")
            existing = {r["name"] for r in await cur.fetchall()}
            if not existing:
                continue  # 表不存在/刚由本版本 DDL 建出
            missing.extend(f"{table}.{c}" for c in columns if c not in existing)
        if missing:
            raise self._refuse(
                f"库缺本版本需要的列：{', '.join(missing)}"
                f"——库是更早版本的形态（实体数据形态已在 v2 变更："
                f"实体 = id + 组件，DESIGN D32）"
            )
        stale: list[str] = []
        for table, columns in _FORBIDDEN_COLUMNS.items():
            cur = await self._conn.execute(f"PRAGMA table_info({table})")
            existing = {r["name"] for r in await cur.fetchall()}
            stale.extend(f"{table}.{c}" for c in columns if c in existing)
        if stale:
            raise self._refuse(
                f"库还带着 v9 之前已被取消的列：{', '.join(stale)}"
                f"——名字/描述/账户绑定已进 core:info / core:account 组件（DESIGN §12.4），"
                f"继续启动会把它们静默丢掉"
            )

    async def _seed_if_empty(self) -> None:
        """空库只建「默认世界」这一结构性容器（幂等）。

        v0.2.0：内核不播种地图/地块/实体/物品——世界内容由玩法包导入
        （如世界包 worlditor_play_demo_world）或用户经管理端创建。
        """
        assert self._conn is not None
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM worlds")
        if (await cur.fetchone())["n"] == 0:
            await self._conn.execute(
                "INSERT INTO worlds(id, name, desc, play_ids_json) VALUES(?, ?, ?, ?)",
                (DEFAULT_WORLD_ID, "默认世界", "", "[]"),
            )
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        await self._commit()

    # ---------- 全量载入 ----------

    def _refuse(self, headline: str) -> IncompatibleDataError:
        """构造「数据不兼容」的启动错误（D13：拒绝 + 指明删哪个文件，不迁移）。"""
        return IncompatibleDataError(
            f"数据不兼容：{headline}\n"
            f"本版本不迁移历史数据（DESIGN D13）。"
            f"处理：删除 {self.db_path} 后重新启动"
            f"（想先留档就 mv 到 {self.db_path}.old）。\n"
            "注意：删除会一并清空地图、地块、实体与账户，重建后需重新注册管理员。"
        )

    def _incompatible_error(
        self, where: str, field: str, cause: Exception
    ) -> IncompatibleDataError:
        """构造「某行某字段读不了」的启动错误：指明位置 + 处理方式（不迁移）。"""
        return self._refuse(f"{where} 的 {field} 读不了 —— {cause}")

    def _load_json_field(self, raw: Any, where: str, field: str) -> Any:
        """启动期读 JSON 列：坏值 → 不兼容错误（而不是裸 JSONDecodeError）。"""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as e:
            raise self._incompatible_error(where, f"{field}（不是合法 JSON）", e) from e

    def _check_components(self, raw: Any, where: str) -> None:
        """启动期校验组件字典（D13：坏数据拒绝启动，**不静默丢弃**）。

        ``parse_components``（模型层）对非法条目是"丢弃"，那适合 API 输入容错；
        落库读回时丢弃等于**吃掉这个实体的数据**，所以这里改为拒绝并指名位置。
        """
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise self._incompatible_error(
                where, "components（不是对象）", TypeError("收到非对象")
            )
        for key, data in raw.items():
            try:
                split_component_key(key)
            except WorldError as e:
                raise self._incompatible_error(
                    where, f"components[{key!r}]（组件名非法）", e
                ) from e
            if not isinstance(data, dict):
                raise self._incompatible_error(
                    where,
                    f"components[{key!r}]（组件数据不是对象）",
                    TypeError("收到非对象"),
                )

    async def _load_all(self) -> None:
        assert self._conn is not None
        self.maps = {}
        self.loc_by_pos = {}
        cur = await self._conn.execute("SELECT * FROM maps")
        for row in await cur.fetchall():
            where = f"maps.id={row['id']!r}"
            description = self._load_json_field(
                row["description_json"], where, "description"
            )
            try:
                m = parse_map(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "description": description,
                        "timezone": row["timezone"],
                        "spawn_row": row["spawn_row"],
                        "spawn_col": row["spawn_col"],
                        "visible": row["visible"],
                    }
                )
            except _PARSE_ERRORS as e:
                raise self._incompatible_error(
                    where, _bad_map_field(description), e
                ) from e
            self.maps[m.id] = m
        cur = await self._conn.execute("SELECT * FROM locations")
        for row in await cur.fetchall():
            where = (
                f"locations(map_id={row['map_id']!r}, "
                f"row={row['row']}, col={row['col']})"
            )
            payload = {
                "map_id": row["map_id"],
                "row": row["row"],
                "col": row["col"],
                "name": row["name"],
                "description": self._load_json_field(
                    row["description_json"], where, "description"
                ),
                "connections": self._load_json_field(
                    row["conns_json"], where, "connections"
                )
                or {},
            }
            try:
                loc = parse_location(payload)
            except _PARSE_ERRORS as e:
                raise self._incompatible_error(
                    where, _bad_location_field(payload), e
                ) from e
            self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc
        cur = await self._conn.execute("SELECT * FROM templates")
        for row in await cur.fetchall():
            where = f"templates.id={row['id']!r}"
            self.templates[row["id"]] = WorldTemplate(
                id=row["id"],
                name=row["name"],
                data=self._load_json_field(row["data_json"], where, "data") or {},
                scope=row["scope"] or "location",
            )
        cur = await self._conn.execute("SELECT * FROM entities")
        for row in await cur.fetchall():
            where = f"entities.id={row['id']!r}"
            # D13：组件列坏值 → 拒绝启动（不静默当空处理——那等于吃掉这个实体的数据）
            self._check_components(
                self._load_json_field(
                    row["components_json"], where, "components（组件）"
                ),
                where,
            )
            entity = entity_from_row(row)
            if entity is None:
                raise self._incompatible_error(
                    where,
                    "整行（id / 位置 / 类型 / 名称 / 坐标）",
                    ValueError("行不合法"),
                )
            self.entities[entity.id] = entity
        cur = await self._conn.execute("SELECT * FROM play_data")
        for row in await cur.fetchall():
            where = f"play_data({row['namespace']!r}, {row['key']!r})"
            try:
                value = json.loads(row["value_json"])
            except (ValueError, TypeError) as e:
                raise self._incompatible_error(where, "value_json", e) from e
            self.play_data[(row["namespace"], row["key"])] = value
        cur = await self._conn.execute("SELECT * FROM accounts")
        for row in await cur.fetchall():
            self.accounts[row["id"]] = Account(
                id=row["id"],
                username=row["username"],
                password_hash=row["password_hash"],
                role=row["role"],
                created_ts=row["created_ts"],
            )
        # 世界与组织（D15）
        cur = await self._conn.execute("SELECT * FROM worlds")
        for row in await cur.fetchall():
            where = f"worlds.id={row['id']!r}"
            try:
                play_ids = json.loads(row["play_ids_json"] or "[]")
            except (ValueError, TypeError) as e:
                raise self._incompatible_error(where, "play_ids_json", e) from e
            if not isinstance(play_ids, list) or not all(
                isinstance(play_id, str) and play_id for play_id in play_ids
            ):
                raise self._incompatible_error(
                    where, "play_ids_json", ValueError("必须是非空字符串数组")
                )
            self.worlds[row["id"]] = World(
                id=row["id"],
                name=row["name"],
                desc=row["desc"] or "",
                play_ids=play_ids,
            )
        cur = await self._conn.execute("SELECT * FROM world_folders")
        for row in await cur.fetchall():
            self.folders[row["id"]] = WorldFolder(
                id=row["id"],
                world_id=row["world_id"],
                parent_id=row["parent_id"],
                name=row["name"],
                sort=row["sort"],
            )
        cur = await self._conn.execute("SELECT * FROM world_maps")
        for row in await cur.fetchall():
            self.map_world[row["map_id"]] = row["world_id"]
            self.map_folder[row["map_id"]] = row["folder_id"]
            self.map_sort[row["map_id"]] = row["sort"]
        cur = await self._conn.execute("SELECT * FROM world_meta")
        for row in await cur.fetchall():
            self.world_meta[row["key"]] = row["value"]
        cur = await self._conn.execute("SELECT * FROM tokens WHERE revoked = 0")
        for row in await cur.fetchall():
            self.tokens[row["token"]] = TokenInfo(
                token=row["token"],
                entity_id=row["entity_id"],
                tier=row["tier"],
                kind=row["kind"],
                account_id=row["account_id"],
                username=row["username"],
            )
        cur = await self._conn.execute("SELECT * FROM invite_codes")
        for row in await cur.fetchall():
            self.invite_codes[row["code"]] = {
                "used": bool(row["used"]),
                "created_ts": row["created_ts"],
            }
        # D28：变更号/tick 窗口**从库中续号**（world_meta 记全局号，实体记窗口），
        # 取三者较大值——含启动时已续的号（self.revision），绝不回退
        self.revision = max(
            self.revision,
            _int_or_zero(self.world_meta.get("revision")),
            max((e.revision for e in self.entities.values()), default=0),
        )
        self.tick = max((e.changed_tick for e in self.entities.values()), default=0)

    # ---------- 目标解析（死引用判定，同 v3） ----------

    def resolve_target(self, t: Target, from_map_id: str) -> Target | None:
        """目标解析：map_id 空 = 当前地图；目标地图/地块不存在 → None（不可解析）。"""
        map_id = t.map_id or from_map_id
        if map_id not in self.maps:
            return None
        if (map_id, t.row, t.col) not in self.loc_by_pos:
            return None
        return Target(map_id=map_id, row=t.row, col=t.col, weight=t.weight)

    # ---------- 地图（表写操作） ----------

    async def save_map(self, m: WorldMap) -> None:
        """写回 / 新建一张地图。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO maps("
            "id, name, description_json, timezone, spawn_row, spawn_col, visible"
            ") VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                m.id,
                m.name,
                json.dumps(m.description.to_dict()) if m.description else None,
                m.timezone,
                m.spawn_row,
                m.spawn_col,
                m.visible,
            ),
        )
        await self._commit()
        self.maps[m.id] = m

    async def save_location(self, loc: Location) -> None:
        """写回 / 新建一个地块（整体替换对象）。"""
        await self.save_locations([loc])

    async def save_map_bundle(
        self,
        world_map: WorldMap,
        locations: list[Location],
        entities: list[Entity],
        *,
        world_id: str | None = None,
        folder_id: str | None = None,
    ) -> None:
        """一次事务写入地图、副本地块、实体和可选世界归属。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO maps(id, name, description_json, timezone, spawn_row, spawn_col, visible) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                world_map.id,
                world_map.name,
                json.dumps(world_map.description.to_dict())
                if world_map.description
                else None,
                world_map.timezone,
                world_map.spawn_row,
                world_map.spawn_col,
                world_map.visible,
            ),
        )
        if locations:
            await self._conn.executemany(
                "INSERT INTO locations(map_id, row, col, name, description_json, conns_json) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [self._location_row(loc) for loc in locations],
            )
        entity_snapshots = []
        if entities:
            revision = self.revision + 1
            rows = []
            for entity in entities:
                snapshot = copy.deepcopy(entity)
                snapshot.revision = revision
                snapshot.changed_tick = self.tick
                entity_snapshots.append(snapshot)
                rows.append(entity_db_row(snapshot))
            await self._conn.executemany(
                "INSERT INTO entities(id, components_json, revision, changed_tick) VALUES(?, ?, ?, ?)",
                rows,
            )
        if world_id is not None:
            await self._conn.execute(
                "INSERT INTO world_maps(map_id, world_id, folder_id, sort) VALUES(?, ?, ?, ?)",
                (world_map.id, world_id, folder_id, 0),
            )
        await self._commit()
        self.maps[world_map.id] = world_map
        for loc in locations:
            self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc
        for entity, snapshot in zip(entities, entity_snapshots):
            entity.revision = snapshot.revision
            entity.changed_tick = snapshot.changed_tick
            self.entities[entity.id] = entity
        if world_id is not None:
            self.map_world[world_map.id] = world_id
            self.map_folder[world_map.id] = folder_id
            self.map_sort[world_map.id] = 0

    def _location_row(self, loc: Location) -> tuple:
        data = location_to_dict(loc)
        return (
            loc.map_id,
            loc.row,
            loc.col,
            loc.name,
            json.dumps(data["description"]) if data["description"] else None,
            json.dumps(data["connections"]),
        )

    async def save_locations(self, locs: list[Location]) -> None:
        """批量写回地块（**单事务**）。

        地图复制这类批量路径必须走它：逐行提交在 WAL 下每行一次 fsync，
        而调用方（引擎）持着实例锁——几千行的地图会把整个世界卡住。
        """
        assert self._conn is not None
        if not locs:
            return
        await self._conn.executemany(
            "INSERT OR REPLACE INTO locations"
            "(map_id, row, col, name, description_json, conns_json) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            [self._location_row(loc) for loc in locs],
        )
        await self._commit()
        for loc in locs:
            self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc

    async def move_location_bundle(
        self,
        map_id: str,
        src: tuple[str, int, int],
        dst: tuple[str, int, int],
        locations: list[Location],
        entities: list[Entity],
    ) -> None:
        """一次事务提交地块坐标、连接引用和实体位置迁移。"""
        assert self._conn is not None
        await self._conn.execute(
            "DELETE FROM locations WHERE map_id = ? AND row = ? AND col = ?",
            src,
        )
        if locations:
            await self._conn.executemany(
                "INSERT OR REPLACE INTO locations(map_id, row, col, name, description_json, conns_json) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [self._location_row(loc) for loc in locations],
            )
        snapshots = []
        if entities:
            revision = self.revision + 1
            rows = []
            for entity in entities:
                snapshot = copy.deepcopy(entity)
                snapshot.revision = revision
                snapshot.changed_tick = self.tick
                snapshots.append(snapshot)
                rows.append(entity_db_row(snapshot))
            await self._conn.executemany(
                "INSERT OR REPLACE INTO entities(id, components_json, revision, changed_tick) VALUES(?, ?, ?, ?)",
                rows,
            )
        await self._commit()
        self.loc_by_pos.pop(src, None)
        for loc in locations:
            self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc
        for entity, snapshot in zip(entities, snapshots):
            entity.revision = snapshot.revision
            entity.changed_tick = snapshot.changed_tick
            self.entities[entity.id] = entity

    async def delete_location(self, map_id: str, row: int, col: int) -> None:
        """删除地块（引用清理由引擎负责）。"""
        assert self._conn is not None
        await self._conn.execute(
            "DELETE FROM locations WHERE map_id = ? AND row = ? AND col = ?",
            (map_id, row, col),
        )
        await self._commit()
        self.loc_by_pos.pop((map_id, row, col), None)

    async def delete_map(self, map_id: str) -> None:
        """删除地图及其内容，全部 SQL 在一个事务中提交。"""
        assert self._conn is not None
        if map_id not in self.maps:
            raise KeyError(f"地图不存在：{map_id}")
        entity_ids = [e.id for e in self.entities.values() if e.map_id == map_id]
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            await self._conn.execute(
                f"DELETE FROM entities WHERE id IN ({placeholders})", entity_ids
            )
        await self._conn.execute("DELETE FROM locations WHERE map_id = ?", (map_id,))
        await self._conn.execute("DELETE FROM maps WHERE id = ?", (map_id,))
        await self._conn.execute("DELETE FROM world_maps WHERE map_id = ?", (map_id,))
        await self._commit()
        for entity_id in entity_ids:
            self.entities.pop(entity_id, None)
        self.maps.pop(map_id, None)
        self.loc_by_pos = {k: v for k, v in self.loc_by_pos.items() if k[0] != map_id}
        self.map_world.pop(map_id, None)
        self.map_folder.pop(map_id, None)
        self.map_sort.pop(map_id, None)

    async def save_template(self, template: WorldTemplate) -> None:
        """写回 / 新建一个模板（D22：scope = location / entity）。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO templates(id, name, data_json, scope) "
            "VALUES(?, ?, ?, ?)",
            (
                template.id,
                template.name,
                json.dumps(template.data, ensure_ascii=False),
                template.scope,
            ),
        )
        await self._commit()
        self.templates[template.id] = template

    async def delete_template(self, template_id: str) -> None:
        """删除模板。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        await self._commit()
        self.templates.pop(template_id, None)

    # ---------- 实体 ----------

    async def save_entity(self, entity: Entity) -> None:
        """写回 / 新建一个实体（整体替换对象）。"""
        await self.save_entities([entity])

    async def save_entities(self, entities: list[Entity]) -> None:
        """批量写回实体（单事务；同 ``save_locations`` 的理由）。

        D28 变更检测：**落库这一刻盖章**——本批实体拿到同一个新变更号与当前
        tick 窗口。所有实体写入都必须走这里（``save_entity`` 亦转发），所以
        "某条写入路径忘了盖章"这种静默缺陷在结构上不会发生。
        """
        assert self._conn is not None
        if not entities:
            return
        revision = self.revision + 1  # _commit 会把它推进到同一个值
        snapshots = []
        rows = []
        for entity in entities:
            snapshot = copy.deepcopy(entity)
            snapshot.revision = revision
            snapshot.changed_tick = self.tick
            snapshots.append(snapshot)
            rows.append(entity_db_row(snapshot))
        await self._conn.executemany(
            "INSERT OR REPLACE INTO entities("
            "id, components_json, revision, changed_tick"
            ") VALUES(?, ?, ?, ?)",
            rows,
        )
        await self._commit()
        for entity, snapshot in zip(entities, snapshots):
            # 保留现有调用方持有的对象身份，但只在事务成功后盖章并入表。
            entity.revision = snapshot.revision
            entity.changed_tick = snapshot.changed_tick
            self.entities[entity.id] = entity

    async def delete_entity(self, entity_id: str) -> None:
        """删除实体。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        await self._commit()
        self.entities.pop(entity_id, None)

    # ---------- 物品：已移除（v2 / D37） ----------
    #
    # 原 `save_item` / `_insert_item` / `delete_item` + `self.items` 内存表已删除：
    # 内核不再有物品定义（定义 → 组件声明，实例 → 实体 + 组件）。见 model.py 顶部说明。

    # ---------- 玩法数据 KV（namespace 隔离） ----------

    async def set_play_kv(self, namespace: str, key: str, value: Any) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO play_data(namespace, key, value_json) VALUES(?, ?, ?)",
            (namespace, key, json.dumps(value, ensure_ascii=False)),
        )
        await self._commit()
        self.play_data[(namespace, key)] = value

    # ---------- 世界日志（B3：上限 5000，写入时清理最旧） ----------

    async def append_world_log(
        self, ts: float, entity_id: str | None, kind: str, data: dict
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO world_log(ts, entity_id, kind, data_json) VALUES(?, ?, ?, ?)",
            (ts, entity_id, kind, json.dumps(data, ensure_ascii=False)),
        )
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM world_log")
        n = (await cur.fetchone())["n"]
        if n > WORLD_LOG_LIMIT:
            await self._conn.execute(
                "DELETE FROM world_log WHERE id IN ("
                "SELECT id FROM world_log ORDER BY id LIMIT ?)",
                (n - WORLD_LOG_LIMIT,),
            )
        await self._commit()

    async def list_world_log(self, limit: int = 100) -> list[dict]:
        """读取世界日志（最新在前）。"""
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, ts, entity_id, kind, data_json FROM world_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = []
        for row in await cur.fetchall():
            try:
                data = json.loads(row["data_json"])
            except (ValueError, TypeError):
                data = {}
            rows.append(
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "entity_id": row["entity_id"],
                    "kind": row["kind"],
                    "data": data,
                }
            )
        return rows

    # ---------- 身份（accounts / tokens / invite_codes） ----------

    async def save_account(self, account: Account) -> None:
        """写回 / 新建账户。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO accounts(id, username, password_hash, role, created_ts) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                account.id,
                account.username,
                account.password_hash,
                account.role,
                account.created_ts,
            ),
        )
        await self._commit()
        self.accounts[account.id] = account

    def get_account(self, account_id: str) -> Account | None:
        return self.accounts.get(account_id)

    def get_account_by_username(self, username: str) -> Account | None:
        for account in self.accounts.values():
            if account.username == username:
                return account
        return None

    async def save_token(self, info: TokenInfo, created_ts: float) -> None:
        """签发一份凭据（持久化 + 内存）。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO tokens("
            "token, entity_id, tier, kind, account_id, username, created_ts, revoked"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, 0)",
            (
                info.token,
                info.entity_id,
                info.tier,
                info.kind,
                info.account_id,
                info.username,
                created_ts,
            ),
        )
        await self._commit()
        self.tokens[info.token] = info

    def get_token(self, token: str) -> TokenInfo | None:
        """解析未吊销凭据。"""
        return self.tokens.get(token)

    async def set_token_revoked(self, token: str, revoked: bool = True) -> bool:
        """吊销 / 恢复一份凭据；不存在返回 False。"""
        assert self._conn is not None
        if token not in self.tokens:
            return False
        await self._conn.execute(
            "UPDATE tokens SET revoked = ? WHERE token = ?",
            (1 if revoked else 0, token),
        )
        await self._commit()
        if revoked:
            self.tokens.pop(token, None)
        return True

    async def revoke_tokens_of_account(self, account_id: str) -> None:
        """吊销某账户的全部凭据（登录/改密后旧凭据失效）。"""
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE tokens SET revoked = 1 WHERE account_id = ?", (account_id,)
        )
        await self._commit()
        self.tokens = {
            t: v for t, v in self.tokens.items() if v.account_id != account_id
        }

    async def delete_account(self, account_id: str) -> None:
        """删除账户行（永久注销；调用方负责吊销凭据与删除绑账户实体）。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await self._commit()
        self.accounts.pop(account_id, None)

    async def save_invite_code(self, code: str, created_ts: float) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO invite_codes(code, used, created_ts) VALUES(?, 0, ?)",
            (code, created_ts),
        )
        await self._commit()
        self.invite_codes[code] = {"used": False, "created_ts": created_ts}

    def get_invite_code(self, code: str) -> dict | None:
        return self.invite_codes.get(code)

    def list_invite_codes(self) -> list[dict]:
        return [
            {"code": code, "used": entry["used"], "created_ts": entry["created_ts"]}
            for code, entry in self.invite_codes.items()
        ]

    async def set_invite_code_used(self, code: str, used: bool = True) -> bool:
        """标记邀请码已使用（消费 / 吊销）；不存在返回 False。"""
        assert self._conn is not None
        if code not in self.invite_codes:
            return False
        await self._conn.execute(
            "UPDATE invite_codes SET used = ? WHERE code = ?", (1 if used else 0, code)
        )
        await self._commit()
        self.invite_codes[code]["used"] = used
        return True

    async def consume_invite_code(self, code: str) -> bool:
        """原子消费未使用的邀请码；调用方必须持有引擎锁。"""
        assert self._conn is not None
        if code not in self.invite_codes:
            return False
        cursor = await self._conn.execute(
            "UPDATE invite_codes SET used = 1 WHERE code = ? AND used = 0", (code,)
        )
        if cursor.rowcount != 1:
            return False
        await self._commit()
        self.invite_codes[code]["used"] = True
        return True

    # ---------- 世界元数据（world_meta 表） ----------

    def get_meta(self, key: str, default: str = "") -> str:
        """读 world_meta（内存态；_load_all 已载入）。"""
        return self.world_meta.get(key, default)

    async def set_meta(self, key: str, value: str) -> None:
        """写 world_meta（覆盖）。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_meta(key, value) VALUES(?, ?)",
            (key, value),
        )
        await self._commit()
        self.world_meta[key] = value

    # ---------- 世界与组织（D15；调用方在引擎锁内执行） ----------

    async def create_world(
        self,
        world_id: str,
        name: str,
        *,
        desc: str = "",
        play_ids: list[str] | None = None,
    ) -> World:
        """新建世界（id 冲突则报错）。"""
        assert self._conn is not None
        if world_id in self.worlds:
            raise ValueError(f"世界已存在：{world_id}")
        world = World(id=world_id, name=name, desc=desc, play_ids=list(play_ids or []))
        await self._conn.execute(
            "INSERT INTO worlds(id, name, desc, play_ids_json) VALUES(?, ?, ?, ?)",
            (world.id, world.name, world.desc, json.dumps(world.play_ids)),
        )
        await self._commit()
        self.worlds[world.id] = world
        return world

    async def update_world(
        self,
        world_id: str,
        *,
        name: str | None = None,
        desc: str | None = None,
        play_ids: list[str] | None = None,
    ) -> World:
        """更新世界（名称/描述/激活玩法包集合；None = 不变）。"""
        assert self._conn is not None
        world = self.worlds.get(world_id)
        if world is None:
            raise KeyError(f"世界不存在：{world_id}")
        if name is not None:
            world.name = name
        if desc is not None:
            world.desc = desc
        if play_ids is not None:
            world.play_ids = list(play_ids)
        await self._conn.execute(
            "UPDATE worlds SET name = ?, desc = ?, play_ids_json = ? WHERE id = ?",
            (world.name, world.desc, json.dumps(world.play_ids), world.id),
        )
        await self._commit()
        return world

    async def delete_world(self, world_id: str) -> None:
        """删除世界（含其组织树与地图归属；调用方负责"仍有地图"校验）。"""
        assert self._conn is not None
        if world_id not in self.worlds:
            raise KeyError(f"世界不存在：{world_id}")
        await self._conn.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
        await self._conn.execute(
            "DELETE FROM world_folders WHERE world_id = ?", (world_id,)
        )
        await self._conn.execute(
            "DELETE FROM world_maps WHERE world_id = ?", (world_id,)
        )
        await self._commit()
        self.worlds.pop(world_id, None)
        self.folders = {k: v for k, v in self.folders.items() if v.world_id != world_id}
        for map_id, wid in list(self.map_world.items()):
            if wid == world_id:
                self.map_world.pop(map_id, None)
                self.map_folder.pop(map_id, None)
                self.map_sort.pop(map_id, None)

    async def assign_map(
        self,
        map_id: str,
        world_id: str,
        *,
        folder_id: str | None = None,
        sort: int | None = None,
    ) -> None:
        """把地图归属到世界（及可选组织节点）；覆盖旧归属。

        ``sort=None``：同世界同节点内重挂保留原位，换节点则排到末尾。
        """
        assert self._conn is not None
        if map_id not in self.maps:
            raise KeyError(f"地图不存在：{map_id}")
        if world_id not in self.worlds:
            raise KeyError(f"世界不存在：{world_id}")
        if folder_id is not None:
            folder = self.folders.get(folder_id)
            if folder is None or folder.world_id != world_id:
                raise ValueError("组织节点不存在或不属于该世界")
        if sort is None:
            same = (
                self.map_world.get(map_id) == world_id
                and self.map_folder.get(map_id) == folder_id
            )
            sort = (
                self.map_sort.get(map_id, 0)
                if same
                else self._next_sort(world_id, folder_id)
            )
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_maps(map_id, world_id, folder_id, sort) "
            "VALUES(?, ?, ?, ?)",
            (map_id, world_id, folder_id, sort),
        )
        await self._commit()
        self.map_world[map_id] = world_id
        self.map_folder[map_id] = folder_id
        self.map_sort[map_id] = sort

    async def unassign_map(self, map_id: str) -> None:
        """解除地图的世界归属（地图本身保留，变为未归属）。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM world_maps WHERE map_id = ?", (map_id,))
        await self._commit()
        self.map_world.pop(map_id, None)
        self.map_folder.pop(map_id, None)
        self.map_sort.pop(map_id, None)

    async def move_map_folder(
        self, map_id: str, folder_id: str | None, *, sort: int | None = None
    ) -> None:
        """移动地图到世界内组织节点（folder_id=None = 世界根）。"""
        assert self._conn is not None
        if map_id not in self.map_world:
            raise KeyError(f"地图未归属世界：{map_id}")
        await self.assign_map(
            map_id, self.map_world[map_id], folder_id=folder_id, sort=sort
        )

    async def set_map_sort(self, map_id: str, sort: int) -> None:
        """设置地图在其组织节点内的序号。"""
        assert self._conn is not None
        if map_id not in self.map_world:
            raise KeyError(f"地图未归属世界：{map_id}")
        await self._conn.execute(
            "UPDATE world_maps SET sort = ? WHERE map_id = ?", (sort, map_id)
        )
        await self._commit()
        self.map_sort[map_id] = sort

    def _next_sort(self, world_id: str, folder_id: str | None) -> int:
        """组织节点内下一个可用序号（文件夹与地图共用一个排序空间）。"""
        used = [
            f.sort
            for f in self.folders.values()
            if f.world_id == world_id and f.parent_id == folder_id
        ] + [
            self.map_sort.get(map_id, 0)
            for map_id, wid in self.map_world.items()
            if wid == world_id and self.map_folder.get(map_id) == folder_id
        ]
        return max(used) + 1 if used else 0

    async def create_folder(
        self,
        world_id: str,
        name: str,
        *,
        parent_id: str | None = None,
        sort: int | None = None,
    ) -> WorldFolder:
        """新建组织文件夹（parent 必须同世界；None = 世界根；sort=None 排到末尾）。"""
        assert self._conn is not None
        if world_id not in self.worlds:
            raise KeyError(f"世界不存在：{world_id}")
        if parent_id is not None:
            parent = self.folders.get(parent_id)
            if parent is None or parent.world_id != world_id:
                raise ValueError("父文件夹不存在或不属于该世界")
        if sort is None:
            sort = self._next_sort(world_id, parent_id)
        folder = WorldFolder(
            id=uuid.uuid4().hex,
            world_id=world_id,
            name=name,
            parent_id=parent_id,
            sort=sort,
        )
        await self._conn.execute(
            "INSERT INTO world_folders(id, world_id, parent_id, name, sort) "
            "VALUES(?, ?, ?, ?, ?)",
            (folder.id, folder.world_id, folder.parent_id, folder.name, folder.sort),
        )
        await self._commit()
        self.folders[folder.id] = folder
        return folder

    async def rename_folder(self, folder_id: str, name: str) -> None:
        assert self._conn is not None
        folder = self.folders.get(folder_id)
        if folder is None:
            raise KeyError(f"文件夹不存在：{folder_id}")
        folder.name = name
        await self._conn.execute(
            "UPDATE world_folders SET name = ? WHERE id = ?", (name, folder_id)
        )
        await self._commit()

    async def set_folder_sort(self, folder_id: str, sort: int) -> None:
        """设置文件夹在其父节点内的序号。"""
        assert self._conn is not None
        if folder_id not in self.folders:
            raise KeyError(f"文件夹不存在：{folder_id}")
        self.folders[folder_id].sort = sort
        await self._conn.execute(
            "UPDATE world_folders SET sort = ? WHERE id = ?", (sort, folder_id)
        )
        await self._commit()

    async def move_folder(
        self, folder_id: str, parent_id: str | None, *, sort: int | None = None
    ) -> None:
        """移动文件夹到新父节点（同世界；None = 世界根；防环）。"""
        assert self._conn is not None
        folder = self.folders.get(folder_id)
        if folder is None:
            raise KeyError(f"文件夹不存在：{folder_id}")
        if parent_id == folder_id:
            raise ValueError("不能移动到自身之下")
        if parent_id is not None:
            parent = self.folders.get(parent_id)
            if parent is None or parent.world_id != folder.world_id:
                raise ValueError("父文件夹不存在或不属于该世界")
            # 防环：不能移到自己或自己后代之下
            node: WorldFolder | None = parent
            while node is not None:
                if node.id == folder_id:
                    raise ValueError("不能移动到自身或其后代之下")
                node = self.folders.get(node.parent_id) if node.parent_id else None
        if sort is None:
            same = folder.parent_id == parent_id
            sort = folder.sort if same else self._next_sort(folder.world_id, parent_id)
        folder.parent_id = parent_id
        folder.sort = sort
        await self._conn.execute(
            "UPDATE world_folders SET parent_id = ?, sort = ? WHERE id = ?",
            (parent_id, sort, folder_id),
        )
        await self._commit()

    async def delete_folder(self, folder_id: str) -> None:
        """删除组织文件夹（调用方负责非空校验；子文件夹与地图引用同时清除）。"""
        assert self._conn is not None
        if folder_id not in self.folders:
            raise KeyError(f"文件夹不存在：{folder_id}")
        await self._conn.execute("DELETE FROM world_folders WHERE id = ?", (folder_id,))
        await self._conn.execute(
            "UPDATE world_folders SET parent_id = NULL WHERE parent_id = ?",
            (folder_id,),
        )
        await self._conn.execute(
            "UPDATE world_maps SET folder_id = NULL WHERE folder_id = ?",
            (folder_id,),
        )
        await self._commit()
        self.folders.pop(folder_id, None)
        for f in self.folders.values():
            if f.parent_id == folder_id:
                f.parent_id = None
        for map_id, fid in self.map_folder.items():
            if fid == folder_id:
                self.map_folder[map_id] = None

    def list_maps_by_folder(self, world_id: str, folder_id: str | None) -> list[str]:
        """世界内某组织节点下的地图 id 列表（folder_id=None = 世界根）。

        按 sort、名称排序——与文件夹共用同一个序号空间，所以"同级排序"是全序。
        """
        ids = [
            map_id
            for map_id, wid in self.map_world.items()
            if wid == world_id and self.map_folder.get(map_id) == folder_id
        ]

        def key(map_id: str) -> tuple[int, str, str]:
            m = self.maps.get(map_id)
            return (self.map_sort.get(map_id, 0), m.name if m else "", map_id)

        return sorted(ids, key=key)

    def list_folders(self, world_id: str) -> list[WorldFolder]:
        """世界内全部组织文件夹（按 sort、名称排序）。"""
        return sorted(
            (f for f in self.folders.values() if f.world_id == world_id),
            key=lambda f: (f.sort, f.name, f.id),
        )
