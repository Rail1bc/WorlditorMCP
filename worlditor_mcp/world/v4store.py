"""v4 持久化层（aiosqlite，真异步；与 v3 WorldStore 同库共存）。

v4 无迁移（设计决策）：v3 表（maps/locations/templates/world_meta）结构沿用、
数据共享；v4 新增四表（entities/items/play_data/world_log）在
**同一个 world.db 文件**中建表，与 v3 引擎互不干扰（v3 引擎无视 v4 表）。

启动时全量载入内存（读路径快、免锁），写操作由调用方（V4WorldEngine）在
实例锁内执行，本类不自行加锁。

表结构（DESIGN_V4.md「表结构」）：
- entities(id PK, map_id, row, col, kind, name, desc, user_id,
  attrs_json, state_json, last_active_ts) + idx_entities_pos
- items(id PK, name, desc, icon, stackable, use_action, attrs_json)
- play_data(namespace, key, value_json, PK(namespace,key))
- world_log(id AUTOINCREMENT, ts, entity_id, kind, data_json) + idx_world_log_entity
  （容量上限 5000 条，写入时清理最旧，B3）

播种（幂等）：maps 空 → v3 种子世界（41 地块）；entities 空 → v4 种子实体
（商贩·阿福 / 告示牌 / 木门）；items 空 → v4 种子物品（喇叭，D1/D13：内核仅
注册喇叭定义，苹果等其余物品由玩法包注册，D8 持有下沉无 inventories 表）。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from .identity import Account, TokenInfo
from .store import _SEED_MAP, DEFAULT_MAP_ID, _build_seed_locations
from .v3model import (
    Location,
    Target,
    WorldMap,
    WorldTemplate,
    parse_location,
    parse_map,
)
from .v4model import (
    Entity,
    ItemDef,
    World,
    WorldFolder,
    entity_db_row,
    entity_from_row,
    item_db_row,
    item_from_row,
)

SCHEMA_VERSION = "4"
WORLD_LOG_LIMIT = 5000

# 内置广播道具（B2：say scope=world 消耗 1 个 + 每人 30s 冷却）
MEGAPHONE_ITEM_ID = "megaphone"

# ---------- v4 种子数据 ----------


def _seed_entities() -> list[Entity]:
    """v4 种子实体（B8：作为地图种子数据直接放置，静态）。

    - 广场「商贩·阿福」：kind=merchant，talk/trade（货单在 demo_play/data）
    - 步行街「告示牌」：kind=sign，read
    - 迷雾森林入口「木门」：kind=door，open，block_move（演示状态变更）
    """
    cells = [
        (
            DEFAULT_MAP_ID,
            0,
            0,
            "merchant",
            "商贩·阿福",
            "广场上的老商贩，货担里装着苹果和喇叭，笑眯眯地看着来往的行人。",
            {},
            {},
        ),
        (
            DEFAULT_MAP_ID,
            -2,
            0,
            "sign",
            "告示牌",
            "步行街边的木质告示牌，上面贴着几张纸。",
            {},
            {},
        ),
        (
            DEFAULT_MAP_ID,
            3,
            0,
            "door",
            "木门",
            "迷雾森林入口处一扇紧闭的木门，门缝里渗出丝丝凉意。",
            {},
            {"open": False},
        ),
    ]
    return [
        Entity(
            id=uuid.uuid4().hex,
            map_id=map_id,
            row=row,
            col=col,
            kind=kind,
            name=name,
            desc=desc,
            attrs=attrs,
            state=state,
        )
        for map_id, row, col, kind, name, desc, attrs, state in cells
    ]


def _seed_items() -> list[ItemDef]:
    """v4 种子物品：仅内核喇叭定义（D1：广播道具，持有归 social 包）。"""
    return [
        ItemDef(
            id=MEGAPHONE_ITEM_ID,
            name="喇叭",
            desc="全图广播道具：向整个世界喊话一次（每人每 30 秒可用一次）。",
            stackable=True,
            use_action=None,
        ),
    ]


# ---------- v4 表 SQL ----------

_V4_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    map_id TEXT NOT NULL,
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    user_id TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    state_json TEXT NOT NULL DEFAULT '{}',
    last_active_ts REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_entities_pos ON entities(map_id, row, col);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '',
    stackable INTEGER NOT NULL DEFAULT 1,
    use_action TEXT,
    attrs_json TEXT NOT NULL DEFAULT '{}'
);
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
-- v4.1 身份（B13 自助注册 / B4 token 三档）
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
-- v5 世界与组织（D15）：世界 = 玩法包激活集合；组织树纯管理；地图归属
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
    folder_id TEXT
);
"""

DEFAULT_WORLD_ID = "default"

_V3_TABLES_SQL = """
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
    data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class V4WorldStore:
    """v4 世界的 SQLite 持久化 + 内存态（启动时全量载入）。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
        # 内存态快照
        self.maps: dict[str, WorldMap] = {}
        self.loc_by_pos: dict[tuple[str, int, int], Location] = {}
        self.templates: dict[str, WorldTemplate] = {}
        self.entities: dict[str, Entity] = {}
        self.items: dict[str, ItemDef] = {}
        self.play_data: dict[tuple[str, str], Any] = {}
        self.accounts: dict[str, Account] = {}
        self.tokens: dict[str, TokenInfo] = {}
        self.invite_codes: dict[str, dict] = {}
        # v5 世界与组织（D15）
        self.worlds: dict[str, World] = {}
        self.folders: dict[str, WorldFolder] = {}
        self.map_world: dict[str, str] = {}  # map_id -> world_id
        self.map_folder: dict[str, str | None] = {}  # map_id -> folder_id | None
        self.world_meta: dict[str, str] = {}  # world_meta 表内存态

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        """打开连接、建表、幂等播种（v3 种子 + v4 种子）、全量载入内存。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(_V3_TABLES_SQL)
        await self._conn.executescript(_V4_TABLES_SQL)
        await self._seed_if_empty()
        await self._load_all()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _seed_if_empty(self) -> None:
        """maps/entities/items/worlds 各自空则播种（幂等，互不依赖）。"""
        assert self._conn is not None
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM maps")
        if (await cur.fetchone())["n"] == 0:
            await self._seed_world()
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM entities")
        if (await cur.fetchone())["n"] == 0:
            for entity in _seed_entities():
                await self._insert_entity(entity)
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM items")
        if (await cur.fetchone())["n"] == 0:
            for item in _seed_items():
                await self._insert_item(item)
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM worlds")
        if (await cur.fetchone())["n"] == 0:
            await self._conn.execute(
                "INSERT INTO worlds(id, name, desc, play_ids_json) VALUES(?, ?, ?, ?)",
                (DEFAULT_WORLD_ID, "默认世界", "", "[]"),
            )
        cur = await self._conn.execute("SELECT COUNT(*) AS n FROM world_maps")
        if (await cur.fetchone())["n"] == 0:
            await self._conn.execute(
                "INSERT INTO world_maps(map_id, world_id, folder_id) VALUES(?, ?, NULL)",
                (DEFAULT_MAP_ID, DEFAULT_WORLD_ID),
            )
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        await self._conn.commit()

    async def _seed_world(self) -> None:
        """全新库：播种 v3 种子世界（41 地块，与 v3 引擎共享）。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO maps(id, name, description_json, timezone, spawn_row, spawn_col) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                _SEED_MAP["id"],
                _SEED_MAP["name"],
                json.dumps(_SEED_MAP["description"], ensure_ascii=False)
                if isinstance(_SEED_MAP["description"], str)
                else None,
                _SEED_MAP["timezone"],
                _SEED_MAP["spawn_row"],
                _SEED_MAP["spawn_col"],
            ),
        )
        for loc in _build_seed_locations():
            await self._insert_location(loc)
        await self._conn.commit()

    # ---------- 全量载入 ----------

    async def _load_all(self) -> None:
        assert self._conn is not None
        self.maps = {}
        self.loc_by_pos = {}
        cur = await self._conn.execute("SELECT * FROM maps")
        for row in await cur.fetchall():
            m = parse_map(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": json.loads(row["description_json"])
                    if row["description_json"]
                    else None,
                    "timezone": row["timezone"],
                    "spawn_row": row["spawn_row"],
                    "spawn_col": row["spawn_col"],
                    "visible": row["visible"],
                }
            )
            self.maps[m.id] = m
        cur = await self._conn.execute("SELECT * FROM locations")
        for row in await cur.fetchall():
            loc = parse_location(
                {
                    "map_id": row["map_id"],
                    "row": row["row"],
                    "col": row["col"],
                    "name": row["name"],
                    "description": json.loads(row["description_json"])
                    if row["description_json"]
                    else None,
                    "connections": json.loads(row["conns_json"] or "{}"),
                }
            )
            self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc
        cur = await self._conn.execute("SELECT * FROM templates")
        for row in await cur.fetchall():
            self.templates[row["id"]] = WorldTemplate(
                id=row["id"],
                name=row["name"],
                data=json.loads(row["data_json"] or "{}"),
            )
        cur = await self._conn.execute("SELECT * FROM entities")
        for row in await cur.fetchall():
            entity = entity_from_row(row)
            if entity is not None:
                self.entities[entity.id] = entity
        cur = await self._conn.execute("SELECT * FROM items")
        for row in await cur.fetchall():
            item = item_from_row(row)
            if item is not None:
                self.items[item.id] = item
        cur = await self._conn.execute("SELECT * FROM play_data")
        for row in await cur.fetchall():
            try:
                value = json.loads(row["value_json"])
            except (ValueError, TypeError):
                value = None
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
        # v5 世界与组织（D15）
        cur = await self._conn.execute("SELECT * FROM worlds")
        for row in await cur.fetchall():
            try:
                play_ids = json.loads(row["play_ids_json"] or "[]")
            except (ValueError, TypeError):
                play_ids = []
            self.worlds[row["id"]] = World(
                id=row["id"],
                name=row["name"],
                desc=row["desc"] or "",
                play_ids=[str(p) for p in play_ids]
                if isinstance(play_ids, list)
                else [],
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

    # ---------- 目标解析（死引用判定，同 v3） ----------

    def resolve_target(self, t: Target, from_map_id: str) -> Target | None:
        """目标解析：map_id 空 = 当前地图；目标地图/地块不存在 → None（不可解析）。"""
        map_id = t.map_id or from_map_id
        if map_id not in self.maps:
            return None
        if (map_id, t.row, t.col) not in self.loc_by_pos:
            return None
        return Target(map_id=map_id, row=t.row, col=t.col, weight=t.weight)

    # ---------- 地图（v3 表写操作，与 v3 引擎共享数据） ----------

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
        await self._conn.commit()
        self.maps[m.id] = m

    async def save_location(self, loc: Location) -> None:
        """写回 / 新建一个地块（整体替换对象）。"""
        assert self._conn is not None
        await self._insert_location(loc)
        self.loc_by_pos[(loc.map_id, loc.row, loc.col)] = loc

    async def _insert_location(self, loc: Location) -> None:
        assert self._conn is not None
        from .v3model import location_to_dict

        data = location_to_dict(loc)
        await self._conn.execute(
            "INSERT OR REPLACE INTO locations(map_id, row, col, name, description_json, conns_json) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                loc.map_id,
                loc.row,
                loc.col,
                loc.name,
                json.dumps(data["description"]) if data["description"] else None,
                json.dumps(data["connections"]),
            ),
        )
        await self._conn.commit()

    async def delete_location(self, map_id: str, row: int, col: int) -> None:
        """删除地块（引用清理由引擎负责）。"""
        assert self._conn is not None
        await self._conn.execute(
            "DELETE FROM locations WHERE map_id = ? AND row = ? AND col = ?",
            (map_id, row, col),
        )
        await self._conn.commit()
        self.loc_by_pos.pop((map_id, row, col), None)

    async def delete_map(self, map_id: str) -> None:
        """删除地图（级联地块/实体/世界归属；调用方负责身份化实体在场校验）。"""
        assert self._conn is not None
        if map_id not in self.maps:
            raise KeyError(f"地图不存在：{map_id}")
        for entity in [e for e in self.entities.values() if e.map_id == map_id]:
            await self.delete_entity(entity.id)  # 级联背包
        await self._conn.execute("DELETE FROM locations WHERE map_id = ?", (map_id,))
        await self._conn.execute("DELETE FROM maps WHERE id = ?", (map_id,))
        await self._conn.execute("DELETE FROM world_maps WHERE map_id = ?", (map_id,))
        await self._conn.commit()
        self.maps.pop(map_id, None)
        self.loc_by_pos = {k: v for k, v in self.loc_by_pos.items() if k[0] != map_id}
        self.map_world.pop(map_id, None)
        self.map_folder.pop(map_id, None)

    async def save_template(self, template: WorldTemplate) -> None:
        """写回 / 新建一个模板。"""
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO templates(id, name, data_json) VALUES(?, ?, ?)",
            (template.id, template.name, json.dumps(template.data, ensure_ascii=False)),
        )
        await self._conn.commit()
        self.templates[template.id] = template

    async def delete_template(self, template_id: str) -> None:
        """删除模板。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        await self._conn.commit()
        self.templates.pop(template_id, None)

    # ---------- 实体 ----------

    async def save_entity(self, entity: Entity) -> None:
        """写回 / 新建一个实体（整体替换对象）。"""
        assert self._conn is not None
        await self._insert_entity(entity)
        self.entities[entity.id] = entity

    async def _insert_entity(self, entity: Entity) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO entities("
            "id, map_id, row, col, kind, name, desc, user_id, attrs_json, state_json, last_active_ts"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            entity_db_row(entity),
        )
        await self._conn.commit()

    async def delete_entity(self, entity_id: str) -> None:
        """删除实体。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        await self._conn.commit()
        self.entities.pop(entity_id, None)

    # ---------- 物品 ----------

    async def save_item(self, item: ItemDef) -> None:
        """写回 / 新建一个物品定义。"""
        assert self._conn is not None
        await self._insert_item(item)
        self.items[item.id] = item

    async def _insert_item(self, item: ItemDef) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO items("
            "id, name, desc, icon, stackable, use_action, attrs_json"
            ") VALUES(?, ?, ?, ?, ?, ?, ?)",
            item_db_row(item),
        )
        await self._conn.commit()

    async def delete_item(self, item_id: str) -> None:
        """删除物品定义。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await self._conn.commit()
        self.items.pop(item_id, None)

    # ---------- 玩法数据 KV（namespace 隔离） ----------

    async def set_play_kv(self, namespace: str, key: str, value: Any) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO play_data(namespace, key, value_json) VALUES(?, ?, ?)",
            (namespace, key, json.dumps(value, ensure_ascii=False)),
        )
        await self._conn.commit()
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
        await self._conn.commit()

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

    # ---------- 身份（v4.1：accounts / tokens / invite_codes） ----------

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
        await self._conn.commit()
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
        await self._conn.commit()
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
        await self._conn.commit()
        if revoked:
            self.tokens.pop(token, None)
        return True

    async def revoke_tokens_of_account(self, account_id: str) -> None:
        """吊销某账户的全部凭据（登录/改密后旧凭据失效）。"""
        assert self._conn is not None
        await self._conn.execute(
            "UPDATE tokens SET revoked = 1 WHERE account_id = ?", (account_id,)
        )
        await self._conn.commit()
        self.tokens = {
            t: v for t, v in self.tokens.items() if v.account_id != account_id
        }

    async def save_invite_code(self, code: str, created_ts: float) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO invite_codes(code, used, created_ts) VALUES(?, 0, ?)",
            (code, created_ts),
        )
        await self._conn.commit()
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
        await self._conn.commit()
        self.invite_codes[code]["used"] = used
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
        await self._conn.commit()
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
        await self._conn.commit()
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
        await self._conn.commit()
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
        await self._conn.commit()
        self.worlds.pop(world_id, None)
        self.folders = {k: v for k, v in self.folders.items() if v.world_id != world_id}
        for map_id, wid in list(self.map_world.items()):
            if wid == world_id:
                self.map_world.pop(map_id, None)
                self.map_folder.pop(map_id, None)

    async def assign_map(
        self, map_id: str, world_id: str, *, folder_id: str | None = None
    ) -> None:
        """把地图归属到世界（及可选组织节点）；覆盖旧归属。"""
        assert self._conn is not None
        if map_id not in self.maps:
            raise KeyError(f"地图不存在：{map_id}")
        if world_id not in self.worlds:
            raise KeyError(f"世界不存在：{world_id}")
        await self._conn.execute(
            "INSERT OR REPLACE INTO world_maps(map_id, world_id, folder_id) VALUES(?, ?, ?)",
            (map_id, world_id, folder_id),
        )
        await self._conn.commit()
        self.map_world[map_id] = world_id
        self.map_folder[map_id] = folder_id

    async def unassign_map(self, map_id: str) -> None:
        """解除地图的世界归属（地图本身保留，变为未归属）。"""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM world_maps WHERE map_id = ?", (map_id,))
        await self._conn.commit()
        self.map_world.pop(map_id, None)
        self.map_folder.pop(map_id, None)

    async def move_map_folder(self, map_id: str, folder_id: str | None) -> None:
        """移动地图到世界内组织节点（folder_id=None = 世界根）。"""
        assert self._conn is not None
        if map_id not in self.map_world:
            raise KeyError(f"地图未归属世界：{map_id}")
        await self._conn.execute(
            "UPDATE world_maps SET folder_id = ? WHERE map_id = ?",
            (folder_id, map_id),
        )
        await self._conn.commit()
        self.map_folder[map_id] = folder_id

    async def create_folder(
        self,
        world_id: str,
        name: str,
        *,
        parent_id: str | None = None,
        sort: int = 0,
    ) -> WorldFolder:
        """新建组织文件夹（parent 必须同世界；None = 世界根）。"""
        assert self._conn is not None
        if world_id not in self.worlds:
            raise KeyError(f"世界不存在：{world_id}")
        if parent_id is not None:
            parent = self.folders.get(parent_id)
            if parent is None or parent.world_id != world_id:
                raise ValueError("父文件夹不存在或不属于该世界")
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
        await self._conn.commit()
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
        await self._conn.commit()

    async def move_folder(self, folder_id: str, parent_id: str | None) -> None:
        """移动文件夹到新父节点（同世界；None = 世界根；防环）。"""
        assert self._conn is not None
        folder = self.folders.get(folder_id)
        if folder is None:
            raise KeyError(f"文件夹不存在：{folder_id}")
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
        folder.parent_id = parent_id
        await self._conn.execute(
            "UPDATE world_folders SET parent_id = ? WHERE id = ?",
            (parent_id, folder_id),
        )
        await self._conn.commit()

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
        await self._conn.commit()
        self.folders.pop(folder_id, None)
        for f in self.folders.values():
            if f.parent_id == folder_id:
                f.parent_id = None
        for map_id, fid in self.map_folder.items():
            if fid == folder_id:
                self.map_folder[map_id] = None

    def list_maps_by_folder(self, world_id: str, folder_id: str | None) -> list[str]:
        """世界内某组织节点下的地图 id 列表（folder_id=None = 世界根）。"""
        return [
            map_id
            for map_id, wid in self.map_world.items()
            if wid == world_id and self.map_folder.get(map_id) == folder_id
        ]

    def list_folders(self, world_id: str) -> list[WorldFolder]:
        """世界内全部组织文件夹（按 sort 排序）。"""
        return sorted(
            (f for f in self.folders.values() if f.world_id == world_id),
            key=lambda f: (f.sort, f.name),
        )
