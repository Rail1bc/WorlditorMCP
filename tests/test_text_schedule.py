"""文案格式统一（v0.5.2）：分时段文案**只有一种格式**，纯字符串明确拒绝。

背景：`parse_text_schedule` 过去同时接受「纯字符串（= 全天单条）」与
「结构化 `{"periods": [...]}` 」两种写法，还"非法条目静默丢弃"——
同一份数据两种写法必然引出"读进来是文本、存回去结构变了"的静默丢失
（G24/G28 家族），而静默丢字段正是 D23 要根除的东西。

本模块守住四条：
1. 只认结构化对象：字符串 / 非对象 / 空 periods / 坏时段 / 坏条目**全部报错**；
2. 报错是 `WorldError`（管理端 400 + 可读文案），不是 500；
3. `to_dict()` → `parse_text_schedule()` 是无损往返（格式自洽）；
4. **启动期**读到库里的不兼容老数据（如 v0.1.x 播种路径留下的纯字符串描述）：
   拒绝启动**并把话说到位**——`IncompatibleDataError` 指出表/行键/字段与
   "删哪个文件重建"。拒绝 ≠ 迁移：本版本不提供任何转换（D13）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from world_fixtures import schedule, seed_test_world

from worlditor_mcp import cli
from worlditor_mcp.admin import build_admin_app
from worlditor_mcp.world.engine import WorldEngine, WorldError
from worlditor_mcp.world.errors import IncompatibleDataError
from worlditor_mcp.world.identity import IdentityService
from worlditor_mcp.world.model import parse_text_schedule
from worlditor_mcp.world.store import WorldStore


def _run(coro):
    return asyncio.run(coro)


async def _engine(tmp_path: Path) -> WorldEngine:
    engine = WorldEngine(WorldStore(tmp_path / "world.db"))
    await engine.initialize()
    return engine


# ---------- 格式：只认结构化对象 ----------


def test_plain_string_is_rejected_with_hint():
    """纯字符串被拒绝，且错误里带上标准格式（用户照着就能改）。"""
    with pytest.raises(WorldError) as err:
        parse_text_schedule("小镇广场，人来人往。")
    message = str(err.value)
    assert "periods" in message and "text" in message
    assert "str" in message  # 说明收到了什么类型


@pytest.mark.parametrize(
    "bad",
    [
        123,
        ["periods"],
        {"periods": []},  # 空 = 想表达"没有文案"？那是 None 的语义，不给第二种写法
        {"periods": "不是数组"},
        {"periods": [{"start": "08:00", "end": "18:00"}]},  # 缺 items
        {
            "periods": [{"start": "8点", "end": "18:00", "items": [{"text": "x"}]}]
        },  # 时间非法
        {"periods": [{"start": "08:00", "end": "18:00", "items": []}]},  # 空 items
        {
            "periods": [{"start": "08:00", "end": "18:00", "items": [{"weight": 1}]}]
        },  # 缺 text
        {
            "periods": [{"start": "08:00", "end": "18:00", "items": [{"text": ""}]}]
        },  # 空 text
        {
            "periods": [
                {
                    "start": "08:00",
                    "end": "18:00",
                    "items": [{"text": "x", "weight": 0}],
                }
            ]
        },
        {
            "periods": [
                {
                    "start": "08:00",
                    "end": "18:00",
                    "items": [{"text": "x", "weight": "多"}],
                }
            ]
        },
        {"periods": ["不是对象"]},
    ],
)
def test_malformed_schedules_raise_instead_of_silent_drop(bad):
    """结构非法一律报错——不再"静默丢弃条目/整体退化成空"。"""
    with pytest.raises(WorldError):
        parse_text_schedule(bad)


def test_valid_schedule_round_trips_losslessly():
    """多时段 + 多条目 + 权重：to_dict → parse 无损（格式自洽）。"""
    original = {
        "periods": [
            {
                "start": "06:00",
                "end": "18:00",
                "items": [
                    {"text": "白天", "weight": 3.0},
                    {"text": "也白天", "weight": 0.5},
                ],
            },
            {
                "start": "18:00",
                "end": "06:00",
                "items": [{"text": "夜里", "weight": 1}],
            },
        ]
    }
    parsed = parse_text_schedule(original)
    assert parsed.to_dict() == original
    assert parse_text_schedule(parsed.to_dict()).to_dict() == original


def test_none_means_no_text():
    """None = 没有文案（唯一的"清除"写法），返回默认空调度。"""
    assert parse_text_schedule(None).periods[0].items[0].text == ""


# ---------- 端到端：引擎与管理端都按同一条规则办事 ----------


def test_engine_rejects_plain_text_description(tmp_path):
    """引擎层：`create_location(description="纯文本")` 报 WorldError（不是静默接受）。"""

    async def fn():
        engine = await _engine(tmp_path)
        try:
            await seed_test_world(engine)
            with pytest.raises(WorldError, match="periods"):
                await engine.create_location(
                    "default", 2, 2, "测试", description="纯文本"
                )
            created = await engine.create_location(
                "default", 2, 2, "测试", description=schedule("结构化")
            )
            assert (
                created.description.resolve(__import__("datetime").datetime.now())
                == "结构化"
            )
        finally:
            await engine.terminate()

    _run(fn())


def test_admin_rejects_plain_text_with_400(tmp_path):
    """管理端：纯文本描述 → 400 + 可读错误（不是 500，也不落盘）。"""

    async def fn():
        engine = await _engine(tmp_path)
        await seed_test_world(engine)
        identity = IdentityService(engine, auth_mode="open", admin_key="sekret")
        app = build_admin_app(identity, engine=engine)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://admin"
            ) as client:
                info = await identity.register_human(
                    "admin1", "pass123", admin_key="sekret"
                )
                headers = {"Authorization": f"Bearer {info.token}"}
                resp = await client.post(
                    "/admin/locations",
                    json={
                        "map_id": "default",
                        "row": 0,
                        "col": 0,
                        "name": "中央广场",
                        "description": "纯文本描述",
                    },
                    headers=headers,
                )
                assert resp.status_code == 400, resp.text
                assert "periods" in resp.json()["error"]
                detail = (
                    await client.get("/admin/maps/default", headers=headers)
                ).json()
                assert detail["locations"][0]["description"] is None  # 没有落盘

                # 结构化描述正常保存
                resp = await client.post(
                    "/admin/locations",
                    json={
                        "map_id": "default",
                        "row": 0,
                        "col": 0,
                        "name": "中央广场",
                        "description": schedule("人来人往"),
                    },
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                detail = (
                    await client.get("/admin/maps/default", headers=headers)
                ).json()
                saved = detail["locations"][0]["description"]
                assert saved["periods"][0]["items"][0]["text"] == "人来人往"
        finally:
            await engine.terminate()

    _run(fn())


def test_location_template_text_is_validated_at_save_time(tmp_path):
    """地块模板的文案在**保存点**校验（模板 data 原样入库，不能等到套用才炸）。"""

    async def fn():
        from worlditor_mcp.world.model import WorldTemplate

        engine = await _engine(tmp_path)
        await seed_test_world(engine)
        try:
            # 纯文本文案 → 保存即拒绝（不是先入库、套用时才报错）
            with pytest.raises(WorldError, match="periods"):
                await engine.save_template(
                    WorldTemplate(
                        id="bad",
                        name="长椅",
                        scope="location",
                        data={"name": "长椅", "description": "一张长椅。"},
                    )
                )
            # 空壳模板（name 留空）仍可保存：文案结构照样校验
            await engine.save_template(
                WorldTemplate(
                    id="shell",
                    name="空壳",
                    scope="location",
                    data={
                        "description": schedule("待填名字", start="08:00", end="18:00")
                    },
                )
            )
            shell = engine.store.templates["shell"]
            assert shell.data["name"] == ""
            assert shell.data["description"]["periods"][0]["start"] == "08:00"
            # 结构化文案正常保存
            await engine.save_template(
                WorldTemplate(
                    id="good",
                    name="长椅",
                    scope="location",
                    data={"name": "长椅", "description": schedule("一张长椅。")},
                )
            )
            good = engine.store.templates["good"]
            text = good.data["description"]["periods"][0]["items"][0]["text"]
            assert text == "一张长椅。"
        finally:
            await engine.terminate()

    _run(fn())


def test_demo_world_uses_structured_descriptions():
    """内置世界包的数据文件也只写结构化格式（别再出现纯文本描述）。"""
    world_json = (
        Path(__file__).resolve().parent.parent
        / "worlditor_mcp"
        / "builtin_plays"
        / "worlditor_play_demo_world"
        / "world.json"
    )
    data = json.loads(world_json.read_text(encoding="utf-8"))
    assert isinstance(data["map"]["description"], dict)
    for loc in data["locations"]:
        if loc.get("description") is not None:
            assert isinstance(loc["description"], dict), loc["name"]
        for slot in (loc.get("connections") or {}).values():
            for path in slot.get("paths") or []:
                if path.get("label") is not None:
                    assert isinstance(path["label"], dict), loc["name"]


# ---------- 启动期：库里的不兼容数据 → 拒绝，但把话说到位 ----------
#
# 场景来源（真事）：v0.1.x 有两条播种路径，`store.py` 那条写结构化、
# `v4store.py` 那条直接 `json.dumps(字符串)`，两者共用同一个 world.db。v0.5.2 收紧
# 解析器后，这种库**启动即崩**，而崩出来的是一屏 60 行 traceback —— 运维能拿到的
# 唯一信息是最后那句"（收到 str）"。这里的验收点就是：**仍然拒绝**（不迁移、
# 不静默容忍），但错误本身要指明「哪张表哪一行哪个字段」与「删哪个文件重建」。

# v0.1.0 `v4store._seed_world` 写进去的那一行（原样抄自 git show v0.1.0）
_LEGACY_SEED = (
    "INSERT OR REPLACE INTO maps(id, name, description_json, timezone,"
    " visible) VALUES(?, ?, ?, ?, 'public')",
    (
        "default",
        "主世界",
        json.dumps(
            "由广场、步行街、AstrBot大道、开源小区与迷雾森林组成的世界。",
            ensure_ascii=False,
        ),
        "Asia/Shanghai",
    ),
)


def _poison(tmp_path: Path, sql: str, params: tuple) -> Path:
    """建一个正常库，再注入一行"这个版本读不了"的内容（模拟旧数据）。"""
    db = tmp_path / "world.db"

    async def fn():
        store = WorldStore(db)
        await store.initialize()
        await store.close()

    _run(fn())
    con = sqlite3.connect(db)
    con.execute(sql, params)
    con.commit()
    con.close()
    return db


def _boot(db: Path) -> None:
    """再开一次库（等价于"下次启动"）；读不了就抛 IncompatibleDataError。"""

    async def fn():
        store = WorldStore(db)
        try:
            await store.initialize()
        finally:
            await store.close()

    _run(fn())


def test_legacy_plain_string_description_refuses_to_start(tmp_path):
    """旧库的纯字符串地图描述：启动拒绝，且指明表/行键/字段 + 处理方式。"""
    db = _poison(tmp_path, *_LEGACY_SEED)
    with pytest.raises(IncompatibleDataError) as err:
        _boot(db)
    msg = str(err.value)
    assert "maps.id='default'" in msg  # 哪张表哪一行
    assert "description" in msg  # 哪个字段
    assert "不迁移" in msg  # 结论没变：拒绝，不转换
    assert str(db) in msg  # 删哪个文件（绝对路径）
    assert ".old" in msg  # 想留档怎么办


def test_legacy_description_is_not_silently_tolerated(tmp_path):
    """拒绝 ≠ 静默容忍：抛错时**一个字段都没改**（不做任何偷偷的降级）。"""
    db = _poison(tmp_path, *_LEGACY_SEED)
    with pytest.raises(IncompatibleDataError):
        _boot(db)
    con = sqlite3.connect(db)
    raw = con.execute("SELECT description_json FROM maps").fetchone()[0]
    con.close()
    assert json.loads(raw) == json.loads(_LEGACY_SEED[1][2])  # 原样还在


def test_legacy_location_description_names_row(tmp_path):
    """地块描述是纯字符串：错误里带 (map_id, row, col) 与字段名。"""
    db = _poison(
        tmp_path,
        "INSERT INTO locations(map_id, row, col, name, description_json,"
        " conns_json) VALUES('default', 3, 4, '旧客栈', ?, '{}')",
        (json.dumps("炉火终日不熄。", ensure_ascii=False),),
    )
    with pytest.raises(IncompatibleDataError) as err:
        _boot(db)
    msg = str(err.value)
    assert "row=3" in msg and "col=4" in msg
    assert "description" in msg


def test_legacy_path_label_names_the_exact_slot(tmp_path):
    """连接路径 label 是纯字符串：错误指到 `connections.<方向>.paths[i].label`。

    方向必须用合法值（up/down/left/right）——非法方向键在载入时被**静默忽略**
    （`parse_location` 只解析 DIRECTIONS 里的槽位），所以用它当反例会让这条
    测试变成"什么都没发生"。
    """
    conns = json.dumps(
        {
            "up": {
                "direction": "up",
                "enabled": True,
                "paths": [
                    {
                        "reveal_target": True,
                        "label": "向北的小路",
                        "targets": [
                            {"map_id": "default", "row": -1, "col": 0, "weight": 1.0}
                        ],
                    }
                ],
            }
        },
        ensure_ascii=False,
    )
    db = _poison(
        tmp_path,
        "INSERT INTO locations(map_id, row, col, name, description_json,"
        " conns_json) VALUES('default', 0, 0, '小镇广场', NULL, ?)",
        (conns,),
    )
    with pytest.raises(IncompatibleDataError) as err:
        _boot(db)
    assert "connections.up.paths[0].label" in str(err.value)


def test_corrupt_json_column_is_reported_as_such(tmp_path):
    """列里根本不是合法 JSON（截断/手改坏了）→ 说"不是合法 JSON"，不是栈。"""
    db = _poison(
        tmp_path,
        "INSERT INTO maps(id, name, description_json, timezone, visible)"
        " VALUES('default', '主世界', ?, NULL, 'public')",
        ('{"periods": [{"start": "00:00"',),
    )
    with pytest.raises(IncompatibleDataError) as err:
        _boot(db)
    msg = str(err.value)
    assert "不是合法 JSON" in msg
    assert "maps.id='default'" in msg


def test_healthy_database_still_boots(tmp_path):
    """反向守卫：正常库（结构化文案）跨重启照常载入——别把检查做成误报。"""

    async def fn():
        engine = await _engine(tmp_path)
        await seed_test_world(engine)
        await engine.create_location(
            "default", 2, 2, "茶馆", description=schedule("茶香扑鼻")
        )
        await engine.terminate()

    _run(fn())
    _boot(tmp_path / "world.db")


def test_cli_reports_remedy_without_traceback(tmp_path, capsys):
    """CLI 端到端：启动中止 → 打指引、退出码 1、**不打栈**。"""
    db = _poison(tmp_path, *_LEGACY_SEED)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["serve", "--data-dir", str(tmp_path), "--admin-port", "0"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "worlditor 启动中止" in err
    assert "maps.id='default'" in err
    assert "不迁移" in err
    assert str(db) in err
    assert "Traceback" not in err
