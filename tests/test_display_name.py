"""显示名（``core:info.name``）的写入校验——K-11 / D56。

为什么单开一个文件：名字是**世界里唯一的身份显示**（``/scene`` 的 peers、管理端列表、
内核日志全用它），而它在 v0.9 / K-7 之后**玩法包可以直接写**。校验分散在五个写入出入口，
哪天有人加第六条写入路径而忘了校验，这里应该先红。

守三件事：
1. 规则本身（长度 / 控制字符 / 双向文本 / 零宽，中文与 emoji 必须仍然合法）；
2. **每一条写入路径**都拦得住（`set_data` / `set_component` / `add_component` /
   `update_entity` / `place_entity`，含玩法包那条门）；
3. 「作者数据」（组件 label 派生的名字）不当作玩家输入，不该因此让建实体失败。
"""

from __future__ import annotations

import asyncio

import pytest
from world_fixtures import seed_test_world  # noqa: E402

from worlditor_mcp.world.engine import WorldEngine, WorldError  # noqa: E402
from worlditor_mcp.world.model import (  # noqa: E402
    CORE_INFO,
    DISPLAY_NAME_MAX,
    check_display_name,
)
from worlditor_mcp.world.play.api import WorlditorPlayAPI  # noqa: E402
from worlditor_mcp.world.store import WorldStore  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# 会让名字"看起来和实际不一样"的字符——每一类各取一个代表
_BIDI = "\u202e"  # RIGHT-TO-LEFT OVERRIDE：名字整体反序
_ZERO_WIDTH = "\u200b"  # ZERO WIDTH SPACE：两个名字看起来一模一样
_BIDI_ISOLATE = "\u2066"  # LEFT-TO-RIGHT ISOLATE
_BAD_NAMES = [
    "",  # 空
    "   ",  # 全空白
    "张三\n李四",  # 控制字符：会劈开单行渲染
    "张\t三",  # 制表符（注意不能用 `"张三\t"`——首尾空白会被 strip 掉，那是归一不是漏洞）
    f"张{_BIDI}三",  # 双向文本
    f"张{_BIDI_ISOLATE}三",  # 双向隔离
    f"张{_ZERO_WIDTH}三",  # 零宽
    "长" * (DISPLAY_NAME_MAX + 1),  # 超长
    None,  # 非字符串
    123,
]


@pytest.mark.parametrize("bad", _BAD_NAMES)
def test_check_display_name_rejects(bad):
    with pytest.raises(WorldError):
        check_display_name(bad)


@pytest.mark.parametrize(
    "ok,expected",
    [
        ("张三", "张三"),  # 中文（`isalnum()` 对中文为 True，不许误伤）
        ("  张三  ", "张三"),  # 首尾空白归一
        ("Alice-01", "Alice-01"),
        ("🙋", "🙋"),
        ("👨‍👩‍👧", "👨‍👩‍👧"),  # ZWJ 序列：Cf 里唯一放行的
        ("长" * DISPLAY_NAME_MAX, "长" * DISPLAY_NAME_MAX),  # 边界值放行
    ],
)
def test_check_display_name_accepts(ok, expected):
    assert check_display_name(ok) == expected


def test_every_write_path_rejects_bad_name(tmp_path):
    """**每一条**写入 `core:info.name` 的路径都要拦得住（这是 K-11 的核心断言）。"""

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            entity = await engine.place_entity("thing", "default", 0, 0, name="箱子")
            api = WorlditorPlayAPI(engine, "worlditor_play_probe")
            bad = f"张{_BIDI}三"

            # ① 内核对字段写（管理端 / 内核内部）
            with pytest.raises(WorldError, match="控制字符"):
                await engine.set_data(entity.id, "name", bad, component=CORE_INFO)
            # ② 玩法包读写（K-7 开的那扇门——先确认它是开的，再确认它有门槛）
            with pytest.raises(WorldError, match="控制字符"):
                await api.set_data(entity.id, "name", bad, component=CORE_INFO)
            # ③ 整块写组件（绕过字段写的那条路）
            with pytest.raises(WorldError, match="控制字符"):
                await engine.set_component(entity.id, CORE_INFO, {"name": bad})
            # ④ 建组件（同一套校验的另一半）
            other = await engine.place_entity("thing", "default", 1, 0)
            await engine.remove_component(other.id, CORE_INFO)
            with pytest.raises(WorldError, match="控制字符"):
                await engine.add_component(other.id, CORE_INFO, {"name": bad})
            # ⑤ 管理端更新（两个入口：name= 与 components=）
            with pytest.raises(WorldError, match="控制字符"):
                await engine.update_entity(entity.id, name=bad)
            with pytest.raises(WorldError, match="控制字符"):
                await engine.update_entity(
                    entity.id, components={CORE_INFO: {"name": bad}}
                )
            # ⑥ 创建（place_entity 的显式 name）；不给位置 = 合法的"不在世界上"
            with pytest.raises(WorldError, match="控制字符"):
                await engine.place_entity("thing", name=bad)

            # 合法的仍然能写：门没被焊死
            await api.set_data(entity.id, "name", "李四", component=CORE_INFO)
            assert engine.store.entities[entity.id].name == "李四"
            assert (
                engine.store.entities[entity.id].component(CORE_INFO)["name"] == "李四"
            )

            # desc 不受影响：描述本来就是多行长文本
            await api.set_data(entity.id, "desc", "第一行\n第二行", component=CORE_INFO)
            assert (
                "第二行"
                in engine.store.entities[entity.id].component(CORE_INFO)["desc"]
            )

            # 边界：恰好 24 个字符可以，25 个不行
            await api.set_data(
                entity.id, "name", "长" * DISPLAY_NAME_MAX, component=CORE_INFO
            )
            with pytest.raises(WorldError, match="最多"):
                await api.set_data(
                    entity.id,
                    "name",
                    "长" * (DISPLAY_NAME_MAX + 1),
                    component=CORE_INFO,
                )
        finally:
            await engine.terminate()

    _run(fn())


def test_derived_name_from_label_is_not_player_input(tmp_path):
    """组件 `label` 派生的名字是**作者数据**，不该因为长度就建不出实体。

    这条守的是"别把校验塞到 `_compose_entity` 的公共路径上"——否则一个起了长
    label 的包会突然 `place_entity(kind=…)` 全失败，而报错指向的地方跟它无关。
    """

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            api = WorlditorPlayAPI(engine, "worlditor_play_probe")
            long_label = "很长很长的组件标签" * 4  # 远超 24 个字符
            api.declare_component("demo_long", label=long_label)

            made = await api.place_entity("demo_long")  # 不给 name → 取 label
            assert made is not None
            assert engine.store.entities[made.id].name == long_label
        finally:
            await engine.terminate()

    _run(fn())


def test_name_fallback_is_unchanged(tmp_path):
    """**"没有名字"和"名字非法"是两回事**：前者仍兜底 `id` 前 8 位，不是抛错。"""

    async def fn():
        engine = WorldEngine(WorldStore(tmp_path / "world.db"))
        await engine.initialize()
        try:
            await seed_test_world(engine)
            bare, _ = engine._compose_entity(
                kind=None,
                tags=None,
                components=None,
                name=None,
                desc="",
                position={"map_id": "default", "row": 0, "col": 0},
            )
            assert CORE_INFO not in bare.components
            assert bare.name == bare.id[:8]
        finally:
            await engine.terminate()

    _run(fn())
