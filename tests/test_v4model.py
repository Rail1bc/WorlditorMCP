"""v4 数据模型解析容错测试（v4model.py）。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from worlditor_mcp.world.v4model import (  # noqa: E402
    Entity,
    InteractionResult,
    ItemDef,
    entity_db_row,
    entity_from_row,
    item_db_row,
    item_from_row,
)


def test_entity_from_dict_ok():
    e = Entity.from_dict(
        {
            "id": "abc",
            "map_id": "default",
            "row": 1,
            "col": 2,
            "kind": "merchant",
            "name": "阿福",
            "desc": "老商贩",
            "attrs": {"gold": 5},
            "state": {"open": True},
            "user_id": "u1",
            "last_active_ts": 123.4,
        }
    )
    assert e is not None
    assert e.pos_key() == ("default", 1, 2)
    assert e.attrs == {"gold": 5}
    assert e.is_identity() is False


def test_entity_from_dict_tolerant():
    """缺字段/坏类型/坏坐标 → None；attrs 非 dict → 空 dict。"""
    assert Entity.from_dict(None) is None
    assert Entity.from_dict({}) is None
    assert Entity.from_dict({"id": "a"}) is None  # 缺 name/map_id/kind
    assert (
        Entity.from_dict({"id": "a", "map_id": "m", "kind": "k", "name": "n"}) is None
    )  # 缺 row/col
    assert (
        Entity.from_dict(
            {"id": "a", "map_id": "m", "kind": "k", "name": "n", "row": "1", "col": 0}
        )
        is None
    )  # row 非 int
    e = Entity.from_dict(
        {
            "id": "a",
            "map_id": "m",
            "kind": "k",
            "name": "n",
            "row": 1,
            "col": 0,
            "attrs": "bad",
            "state": None,
        }
    )
    assert e is not None and e.attrs == {} and e.state == {}


def test_entity_db_roundtrip():
    e = Entity(
        id="x", map_id="m", row=1, col=2, kind="player", name="小明", attrs={"a": 1}
    )
    row = entity_db_row(e)
    assert row[8] == '{"a": 1}'


def test_entity_from_row_fake():
    class FakeRow:
        def __getitem__(self, key):
            return {
                "id": "x",
                "map_id": "m",
                "row": 1,
                "col": 2,
                "kind": "player",
                "name": "小明",
                "desc": "",
                "user_id": None,
                "attrs_json": "not-json",
                "state_json": "",
                "last_active_ts": 0.0,
            }[key]

    e = entity_from_row(FakeRow())
    assert e is not None and e.attrs == {} and e.state == {}


def test_item_def_roundtrip():
    item = ItemDef(
        id="sword", name="木剑", desc="练习用。", stackable=False, use_action="equip"
    )
    row = item_db_row(item)
    assert row[4] == 0
    parsed = item_from_row(
        type(
            "R",
            (),
            {
                "__getitem__": lambda self, k: {
                    "id": "sword",
                    "name": "木剑",
                    "desc": "练习用。",
                    "icon": "",
                    "stackable": 0,
                    "use_action": "equip",
                    "attrs_json": "{}",
                }[k]
            },
        )()
    )
    assert parsed is not None and parsed.stackable is False
    assert ItemDef.from_dict({"id": "a"}) is None  # 缺 name
    assert (
        ItemDef.from_dict({"id": "a", "name": "n", "stackable": "yes"}).stackable
        is True
    )


def test_result_parse():
    """InteractionResult（D12：仅 text + ui，无 effects）。"""
    result = InteractionResult.from_dict({"text": "hi", "ui": None})
    assert result is not None and result.text == "hi"
    assert result.to_dict() == {"text": "hi", "ui": None}
    assert InteractionResult.from_dict(None) is None
    assert InteractionResult.from_dict({"text": 123}).text == ""
