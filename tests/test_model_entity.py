"""数据模型解析容错测试（model.py）。"""

from __future__ import annotations

from worlditor_mcp.world import (  # noqa: E402
    Entity,
    InteractionResult,
    entity_db_row,
    entity_from_row,
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
            "components": {"local:stat": {"gold": 5}, "core:perception": {}},
            "user_id": "u1",
            "last_active_ts": 123.4,
        }
    )
    assert e is not None
    assert e.pos_key() == ("default", 1, 2)
    # v2 / D32（§12.4）：顶层 name/desc/user_id/map_id/row/col 都是**输入便利**，
    # 会被折进 core:info / core:account / core:position —— 内部只有组件一种形态
    assert e.components == {
        "local:stat": {"gold": 5},
        "core:perception": {},
        "core:position": {"map_id": "default", "row": 1, "col": 2},
        "core:info": {"name": "阿福", "desc": "老商贩"},
        "core:account": {"user_id": "u1"},
    }
    assert e.name == "阿福" and e.desc == "老商贩" and e.user_id == "u1"
    assert e.map_id == "default" and (e.row, e.col) == (1, 2)
    assert e.has_position() is True
    assert e.component("local:stat") == {"gold": 5}
    assert e.component("local:missing") == {}  # 缺失组件 → 空 dict
    assert e.is_account_bound() is True  # D42：判据是 core:account，不是身份
    # 名字的兜底语义：没有 core:info → id 前 8 位
    bare = Entity.from_dict(
        {"id": "0123456789abcdef", "kind": "k", "row": 0, "col": 0, "map_id": "m"}
    )
    assert bare is not None and bare.name == "01234567" and bare.desc == ""
    assert bare.user_id is None
    # D36：位置是**可选**的——三个键都不给 = 实体不在世界上（合法）
    homeless = Entity.from_dict({"id": "h", "kind": "k"})
    assert homeless is not None
    assert homeless.pos_key() is None and homeless.has_position() is False
    assert homeless.map_id is None and homeless.row is None and homeless.col is None


def test_entity_from_dict_tolerant():
    """缺字段/坏类型/坏坐标 → None；components 非 dict → 空 dict、坏条目丢弃。"""
    assert Entity.from_dict(None) is None
    assert Entity.from_dict({}) is None
    assert Entity.from_dict({"id": "a"}) is None  # 缺 kind
    assert Entity.from_dict({"id": "a", "kind": "k"}) is not None  # D36：位置可缺
    assert (
        Entity.from_dict({"id": "a", "map_id": "m", "kind": "k", "row": 0, "col": 0})
        is not None
    )  # v2：name 不再是必填（缺失 → core:info 缺失 → 兜底 id 前 8 位）
    assert (
        Entity.from_dict({"id": "a", "map_id": "m", "kind": "k", "row": 0}) is None
    )  # D36：位置**只给一半**（有 map_id+row 没 col）→ 坏数据
    assert (
        Entity.from_dict({"id": "a", "map_id": "m", "kind": "k", "row": "1", "col": 0})
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
            "components": "bad",
        }
    )
    assert e is not None
    # 坏 components（"bad"）→ 空；顶层 name 折进 core:info，位置折进 core:position
    assert e.components == {
        "core:position": {"map_id": "m", "row": 1, "col": 0},
        "core:info": {"name": "n"},
    }
    # 坏信封（缺冒号）/ 非对象值被丢弃，合法条目保留（parse_components 容错）
    e2 = Entity.from_dict(
        {
            "id": "a",
            "map_id": "m",
            "kind": "k",
            "name": "n",
            "row": 1,
            "col": 0,
            "components": {
                "no-colon": {"x": 1},
                "local:bad": "not-a-dict",
                "local:ok": {"y": 2},
            },
        }
    )
    assert e2 is not None and e2.components == {
        "local:ok": {"y": 2},
        "core:position": {"map_id": "m", "row": 1, "col": 0},
        "core:info": {"name": "n"},  # 顶层 name 折进来（输入便利）
    }


def test_entity_db_roundtrip():
    e = Entity(
        id="x",
        kind="player",
        components={
            "core:position": {"map_id": "m", "row": 1, "col": 2},
            "core:info": {"name": "小明"},
        },
        tags=["spawner"],
    )
    row = entity_db_row(e)
    # v10：实体行 **7 列**——位置/名字/描述/账户绑定全在 components 里（第 3 列）
    assert row == (
        "x",
        "player",
        '{"core:position": {"map_id": "m", "row": 1, "col": 2}, "core:info": {"name": "小明"}}',
        0.0,
        '["spawner"]',
        0,
        0,
    )
    parsed = entity_from_row(
        type(
            "R",
            (),
            {
                "__getitem__": lambda self, k: {
                    "id": "x",
                    "kind": "player",
                    "components_json": row[2],
                    "last_active_ts": 0.0,
                    "tags_json": row[4],
                }[k]
            },
        )()
    )
    assert parsed is not None and parsed.components == e.components
    assert parsed.name == "小明"
    assert parsed.pos_key() == ("m", 1, 2)


def test_entity_from_row_fake():
    class FakeRow:
        def __getitem__(self, key):
            return {
                "id": "x",
                "kind": "player",
                "components_json": "not-json",
                "last_active_ts": 0.0,
                "tags_json": '["a", "", 3, "a", "b"]',
            }[key]

    e = entity_from_row(FakeRow())
    assert e is not None and e.components == {}
    # D18：标签容错解析——非字符串/空串丢弃、去重保序（顺序参与字段覆盖优先级）
    assert e.tags == ["a", "b"]
    # 坏 JSON → 没有位置组件 → 不在世界上（而不是落到 (0,0)）
    assert e.pos_key() is None


def test_result_parse():
    """InteractionResult（D12：仅 text + ui，无 effects）。"""
    result = InteractionResult.from_dict({"text": "hi", "ui": None})
    assert result is not None and result.text == "hi"
    assert result.to_dict() == {"text": "hi", "ui": None}
    assert InteractionResult.from_dict(None) is None
    assert InteractionResult.from_dict({"text": 123}).text == ""
