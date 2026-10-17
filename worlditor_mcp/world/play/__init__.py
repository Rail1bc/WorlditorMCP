"""玩法包发现加载器（DESIGN.md「玩法包体系」）。

扫描 builtin_plays/（服务内置，随版本分发）与 `<数据目录>/plays/` 下
worlditor_play_* 目录；校验 play.yaml 与 requires（worlditor 版本 + plays 依赖）；
importlib 加载 main.py 并调用 setup(api, context)。

- 每个玩法包一个独立 WorlditorPlayAPI（kv namespace 隔离）；单个玩法包
  加载失败记日志跳过，不阻断内核与其他玩法包（异常隔离）。
- 状态持久化（G5/B4）：禁用集合落 world_meta，重启按标记加载（默认启用）。
- 管理（§4.3）：list / enable / disable / uninstall；依赖解析（G6）——
  拓扑加载、enable 自动带依赖、disable 被依赖者报错拒绝。
- 卸载安全（G7）：uninstall 仅限数据目录 plays/ 下直接子目录、
  play_id 白名单校验；内置包仅可停用。
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import logging
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import __version__ as _WORLDITOR_VERSION
from ..engine import WorldEngine, WorldError
from .api import WorlditorPlayAPI
from .spec import PLAY_PREFIX, PlaySpec, load_play_spec, version_ok

logger = logging.getLogger("worlditor")

_PLAY_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 社区玩法包安装（zip 上传，管理端）限制
_MAX_PLAY_ZIP_BYTES = 5 * 1024 * 1024
_MAX_PLAY_ZIP_UNPACKED = 20 * 1024 * 1024


def _zip_parts(name: str) -> list[str]:
    """zip 条目名 → 规范路径片段（去空段与 `.`；含 `..` 直接拒绝）。"""
    parts = [
        p for p in name.replace("\\", "/").lstrip("/").split("/") if p not in ("", ".")
    ]
    if any(p == ".." for p in parts):
        raise WorldError("包内路径非法（含 ..）")
    return parts


_META_DISABLED_KEY = "plays_disabled_json"


@dataclass
class PlayInfo:
    """一个已加载的玩法包。"""

    spec: PlaySpec
    api: WorlditorPlayAPI
    module: Any
    path: Path
    builtin: bool = False

    @property
    def play_id(self) -> str:
        return self.spec.play_id


class PlayLoader:
    """玩法包发现与加载（随内核整体重载；单包 enable/disable 即时生效）。"""

    def __init__(
        self,
        engine: WorldEngine,
        *,
        plays_dir: Path,
        builtin_dir: Path | None = None,
        worlditor_version: str = _WORLDITOR_VERSION,
    ) -> None:
        """构造加载器。

        Args:
            worlditor_version: 校验 ``requires.worlditor`` 时用的内核版本；默认
                = 本包版本（旧默认写死 ``"0.3.0"``，嵌入场景不传参时会把
                ``>=0.7.0`` 的包误判成不兼容）。
        """
        self.engine = engine
        self.plays_dir = Path(plays_dir)
        self.builtin_dir = Path(builtin_dir) if builtin_dir else None
        self.worlditor_version = worlditor_version
        self.plays: dict[str, PlayInfo] = {}
        self._disabled: set[str] = set()  # 持久化的禁用集合
        self._load_errors: dict[str, str] = {}  # play_id -> 加载失败原因

    # ---------- 发现 ----------

    def discover(self) -> list[tuple[Path, bool]]:
        """候选玩法包目录：(path, builtin)。builtin = 服务内置（只读）。"""
        dirs: list[tuple[Path, bool]] = []
        if self.builtin_dir is not None and self.builtin_dir.is_dir():
            for p in sorted(self.builtin_dir.iterdir()):
                if p.is_dir() and p.name.startswith("worlditor_play_"):
                    dirs.append((p, True))
        if self.plays_dir.is_dir():
            for p in sorted(self.plays_dir.iterdir()):
                if p.is_dir() and p.name.startswith("worlditor_play_"):
                    dirs.append((p, False))
        return dirs

    # ---------- 状态持久化（G5：禁用集合落库，默认启用） ----------

    async def _load_disabled_state(self) -> None:
        raw = self.engine.store.get_meta(_META_DISABLED_KEY, "")
        try:
            value = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            value = []
        self._disabled = {str(p) for p in value} if isinstance(value, list) else set()

    async def _save_disabled_state(self) -> None:
        await self.engine.store.set_meta(
            _META_DISABLED_KEY, json.dumps(sorted(self._disabled))
        )

    # ---------- 加载 ----------

    async def load_all(self, context: Any | None = None) -> list[PlayInfo]:
        """按启用标记与依赖拓扑加载全部候选玩法包；返回成功加载的列表。"""
        await self._load_disabled_state()
        self._load_errors = {}
        specs: dict[str, tuple[PlaySpec, Path, bool]] = {}
        conflicts: dict[str, list[Path]] = {}
        # 同名目录冲突（手工复制、旧版安装遗留）：**先扫到的胜出**——discover()
        # 先内置后社区，所以等价于"内置优先"。落败目录只登记原因，不再"两个都不
        # 加载"：那会让内置内容包在重启后整体消失，而社区目录又删不掉（旧行为）。
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is None:
                continue
            if spec.play_id in specs:
                conflicts.setdefault(spec.play_id, [specs[spec.play_id][1]]).append(
                    path
                )
                continue
            specs[spec.play_id] = (spec, path, builtin)
        for play_id, paths in conflicts.items():
            winner, losers = paths[0], paths[1:]
            self._load_errors[play_id] = (
                f"同名目录被忽略（已加载 {winner}）："
                + "、".join(str(p) for p in losers)
            )
            logger.error("[worlditor] play_id %s 有重复目录，忽略：%s", play_id, losers)
        loaded: list[PlayInfo] = []
        for play_id in self._topo_order(specs):
            spec, path, builtin = specs[play_id]
            if play_id in self._disabled:
                continue
            # 依赖必须已加载（拓扑内；缺失/禁用的依赖 → 该包加载失败不阻塞）
            missing = [
                d for d in spec.requires_plays if d not in self.plays and d != play_id
            ]
            if missing:
                self._load_errors[play_id] = f"依赖未启用：{'、'.join(missing)}"
                logger.warning(
                    "[worlditor] 跳过玩法包 %s：依赖未启用 %s", play_id, missing
                )
                continue
            info = await self.load_one(path, context, builtin=builtin)
            if info is not None:
                loaded.append(info)
        # v2 / D37：原 `flush_item_defs()`（把物品定义落库）已随物品移除
        await self._notify_plays_changed("load_all")
        return loaded

    async def _notify_plays_changed(self, reason: str) -> None:
        """玩法包集合变化 → 广播 ``plays_changed`` 信号事件。

        用途：前端（SSE 订阅者）据此刷新视图 tab 与管理页清单——否则装/卸包后
        浏览器必须手动整页刷新才知道有新视图。刻意**不写 world_log**：这是 UI
        信号，不是世界历史。订阅者为零时开销可忽略（纯内存分发）。

        Args:
            reason: 触发原因（load_all / enable / disable / install / uninstall）。
        """
        try:
            await self.engine.emit(
                "plays_changed",
                {"reason": reason, "plays": sorted(self.plays)},
            )
        except Exception:  # noqa: BLE001
            logger.debug("[worlditor] plays_changed 广播失败", exc_info=True)

    def _topo_order(self, specs: dict[str, tuple[PlaySpec, Path, bool]]) -> list[str]:
        """依赖拓扑排序（Kahn）：先加载被依赖者；环/缺失依赖者留到最后。"""
        order: list[str] = []
        pending = set(specs)
        while pending:
            ready = [
                i
                for i in pending
                if all(d not in pending for d in specs[i][0].requires_plays)
            ]
            if not ready:
                order.extend(sorted(pending))  # 环或缺失依赖：按序尝试（会失败）
                break
            for play_id in sorted(ready):
                order.append(play_id)
                pending.discard(play_id)
        return order

    async def load_one(
        self, path: Path, context: Any | None, *, builtin: bool = False
    ) -> PlayInfo | None:
        """加载单个玩法包目录；失败记日志跳过（不抛）。"""
        spec = load_play_spec(path)
        if spec is None:
            self._load_errors[path.name] = "play.yaml 缺失或非法"
            logger.warning("[worlditor] 跳过玩法包 %s：play.yaml 缺失或非法", path.name)
            return None
        if not version_ok(self.worlditor_version, spec.requires_worlditor):
            self._load_errors[spec.play_id] = (
                f"需要 worlditor {spec.requires_worlditor}，当前 {self.worlditor_version}"
            )
            logger.warning(
                "[worlditor] 跳过玩法包 %s：需要 worlditor %s，当前 %s",
                spec.name,
                spec.requires_worlditor,
                self.worlditor_version,
            )
            return None
        # 同 play_id 已加载（install_zip / 直调 load_one 这条不经过 load_all 去重的
        # 路径）：**拒绝覆盖**——覆盖会换掉 `plays[play_id]` 与它绑定的 api，旧包的
        # 注册残留却还在，重启后 load_all 又按"同名目录冲突"处理，结果两个都不在。
        # 这里只记原因、且**不清注册**（清理会误伤已在用的那个包）。
        existing = self.plays.get(spec.play_id)
        if existing is not None:
            self._load_errors[spec.play_id] = (
                f"play_id 已被占用（{existing.path}），本目录未加载"
            )
            logger.error(
                "[worlditor] 拒绝重复加载 %s：已加载自 %s，本次路径 %s",
                spec.play_id,
                existing.path,
                path,
            )
            return None
        main_py = path / "main.py"
        if not main_py.is_file():
            self._load_errors[spec.play_id] = "缺少 main.py"
            logger.warning("[worlditor] 跳过玩法包 %s：缺少 main.py", spec.name)
            return None
        try:
            module = self._load_module(spec.play_id, main_py)
            api = WorlditorPlayAPI(self.engine, spec.play_id)
            self.engine.attach_play_api(spec.play_id, api)
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise RuntimeError("main.py 缺少 setup(api, context)")
            # setup 可为同步或 async（v0.2.0：世界包这类导入型包需要 await 写世界）
            result = setup(api, context)
            if inspect.isawaitable(result):
                await result
            info = PlayInfo(
                spec=spec, api=api, module=module, path=path, builtin=builtin
            )
            self.plays[spec.play_id] = info
            logger.info(
                "[worlditor] 玩法包已加载：%s (%s)", spec.display_name, spec.version
            )
            return info
        except WorldError as e:
            # 玩法包自身的 WorldError（如原语互斥）：原因透出到管理页可见
            logger.exception("[worlditor] 玩法包加载失败：%s", path.name)
            self._load_errors[spec.play_id] = str(e)
            self._rollback_failed_load(spec.play_id)
            return None
        except SystemExit as e:
            # `SystemExit` 不是 `Exception`：不隔离的话 `sys.exit()` 会一路冒到
            # `load_all` → `WorlditorService.start`，**一个包就能让服务起不来**
            # （实测）。这里按"该包加载失败"处理，其余包照常。
            logger.exception("[worlditor] 玩法包企图退出进程（已隔离）：%s", path.name)
            self._load_errors[spec.play_id] = (
                f"包内调用了 sys.exit({e.code!r})——已隔离为加载失败，服务继续"
            )
            self._rollback_failed_load(spec.play_id)
            return None
        except Exception:  # noqa: BLE001
            logger.exception("[worlditor] 玩法包加载失败：%s", path.name)
            self._load_errors[spec.play_id] = "加载异常（见日志）"
            self._rollback_failed_load(spec.play_id)
            return None

    def _rollback_failed_load(self, play_id: str) -> None:
        """加载失败后的回滚：清注册 + 解绑 api + 清模块缓存。

        **首次加载失败要连组件声明一起清**（``purge=True``）——这个包从来没成功
        过，它的声明留在内存里会让 ``list_kinds()`` / ``capabilities()`` 继续报
        "有主但未激活"这种不存在的状态（曾由注释承诺回滚、实际没回滚）。
        曾加载过（disable → enable 又失败）则保留声明：``_tag_specs`` 的留存正是
        "停用不清规格"的既定语义，清了会把"停用"误报成"未声明"。
        """
        purge = play_id not in self._disabled
        self.engine.clear_play_registrations(play_id, purge=purge)
        self.engine.detach_play_api(play_id)
        self._forget_modules(play_id)

    @staticmethod
    def _forget_modules(play_id: str) -> None:
        """清掉该包的模块缓存（``play_id`` 及其全部子模块）。

        模块是按**名字**缓存的：不清的话重装同名包会拿到上一次的模块对象
        （目录都换了、代码还是旧的），包内的辅助模块也会一直挂着——`docs/archive/CORE_AUDIT.md`
        §4 记的"sys.modules 卸载残留"就是这条。
        """
        stale = [
            name
            for name in sys.modules
            if name == play_id or name.startswith(f"{play_id}.")
        ]
        for name in stale:
            sys.modules.pop(name, None)

    def _load_module(self, play_id: str, main_py: Path) -> Any:
        """按**包语义**加载玩法包入口 ``main.py``（多文件包，G50 已落地）。

        `main.py` 作为包 ``<play_id>`` 的入口注册，包的 ``__path__`` 指向包目录
        ——于是包内可以写 ``from . import helper``，解析成 ``<play_id>.helper``。

        为什么不是"把包目录塞进 `sys.path` 再 `import helper`"：`sys.modules` 按
        **裸模块名**缓存、`sys.path` 是全局扁平列表，两个包各有一个 `helper.py`
        时，先导入的那个会永久占住名字，后一个**静默拿到别人的模块**（实测）；
        包目录排在 `sys.path` 前面还会遮蔽标准库同名的模块（放个 `json.py` 就中招）。
        包语义把唯一的 play_id 放进模块全名，天然隔离，也不碰 `sys.path`。
        """
        spec = importlib.util.spec_from_file_location(
            play_id,
            main_py,
            submodule_search_locations=[str(main_py.parent)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("无法创建模块加载器")
        module = importlib.util.module_from_spec(spec)
        sys.modules[play_id] = module
        spec.loader.exec_module(module)
        return module

    # ---------- 管理（§4.3：list / enable / disable / uninstall） ----------

    def list_plays(self) -> list[dict]:
        """全部候选玩法包状态（loaded / disabled / load_failed + 错误详情）。

        同名目录只出一行（胜出者），提示放 ``note``——否则管理页会出现两行
        同一个 play_id，且落败那行还会被算成"已加载"。
        """
        out: list[dict] = []
        seen: set[str] = set()
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is None:
                out.append(
                    {
                        "play_id": path.name,
                        "name": path.name,
                        "version": "",
                        "author": "",
                        "desc": "",
                        "requires": [],
                        "builtin": builtin,
                        "status": "invalid",
                        "error": self._load_errors.get(
                            path.name, "play.yaml 缺失或非法"
                        ),
                        "note": "",
                    }
                )
                continue
            if spec.play_id in seen:
                continue  # 同名目录：胜出那一行已带 note
            seen.add(spec.play_id)
            note = ""
            if spec.play_id in self.plays:
                status = "loaded"
                error = ""
            elif spec.play_id in self._disabled:
                status = "disabled"
                error = ""
            else:
                status = "load_failed"
                error = self._load_errors.get(spec.play_id, "未加载")
            if status != "load_failed":
                # 只有"同名目录被忽略"这类非失败信息会落到这里（失败原因走 error）
                note = self._load_errors.get(spec.play_id, "")
            out.append(
                {
                    "play_id": spec.play_id,
                    "name": spec.display_name,
                    "version": spec.version,
                    "author": spec.author,
                    "desc": spec.desc,
                    "requires": list(spec.requires_plays),
                    "builtin": builtin,
                    "status": status,
                    "error": error,
                    "note": note,
                }
            )
        return sorted(out, key=lambda p: (p["builtin"], p["play_id"]))

    async def enable(self, play_id: str) -> None:
        """启用玩法包：自动先启用其 requires.plays 依赖（拓扑，G6）。"""
        async with self.engine._lock:  # noqa: SLF001
            await self._enable_inner(play_id, set())
        await self._notify_plays_changed("enable")

    async def _enable_inner(self, play_id: str, stack: set[str]) -> None:
        if play_id in self.plays:
            return  # 已加载
        if play_id in stack:
            raise WorldError(f"玩法包依赖成环：{' -> '.join(stack | {play_id})}")
        target = self._find_candidate(play_id)
        if target is None:
            raise WorldError(f"玩法包不存在：{play_id}")
        path, builtin = target
        spec = load_play_spec(path)
        if spec is None:
            raise WorldError(f"玩法包无效（play.yaml 缺失或非法）：{play_id}")
        candidate_ids = self._find_candidate_ids()
        for dep in spec.requires_plays:
            if dep == play_id:
                continue
            if dep not in candidate_ids and dep not in self.plays:
                raise WorldError(f"依赖玩法包不存在：{dep}（{play_id} 需要）")
            await self._enable_inner(dep, stack | {play_id})
        info = await self.load_one(path, None, builtin=builtin)
        if info is None:
            raise WorldError(
                f"玩法包加载失败：{play_id}（{self._load_errors.get(play_id, '未知错误')}）"
            )
        self._disabled.discard(play_id)
        await self._save_disabled_state()

    async def disable(self, play_id: str) -> None:
        """停用玩法包：仍有已加载包依赖它 → 报错拒绝（G6，同 D2 风格）。"""
        async with self.engine._lock:  # noqa: SLF001
            dependents = [
                info.play_id
                for info in self.plays.values()
                if play_id in info.spec.requires_plays
            ]
            if dependents:
                raise WorldError(
                    f"仍有玩法包依赖它：{'、'.join(sorted(dependents))}，请先停用依赖者"
                )
            info = self.plays.pop(play_id, None)
            if info is not None:
                await self._teardown_one(info)
            self._disabled.add(play_id)
            await self._save_disabled_state()
        await self._notify_plays_changed("disable")

    async def uninstall(self, play_id: str) -> None:
        """卸载社区玩法包（删包目录；G7 路径安全）。

        **先删目录、再清状态**：反过来（旧行为）一旦 ``rmtree`` 失败，包已经被
        teardown、disabled 标记也落了库，管理端却报错——下次启动它又回来了。

        **数据不在删除范围内**：``play_data`` KV 与实体上的组件一律保留，
        "卸载即删数据"是过去的错误说法（清理语义见 GAPS G49）。
        """
        if not _PLAY_ID_RE.match(play_id):
            raise WorldError("play_id 非法（仅允许字母/数字/下划线/连字符）")
        async with self.engine._lock:  # noqa: SLF001
            # 同名目录可能有多个：**删社区那份**，内置那份留着。`_find_candidate`
            # 先扫到内置 → 旧行为会报"内置不可卸载"，社区残留目录永远删不掉
            candidates = self._find_candidates(play_id)
            community = [c for c in candidates if not c[1]]
            if not community:
                if candidates:
                    raise WorldError("内置玩法包仅可停用，不可卸载")
                raise WorldError(f"玩法包不存在：{play_id}")
            path, _builtin = community[0]
            # 路径安全：仅限 plays_dir 下直接子目录、目录名 == play_id
            try:
                resolved = path.resolve()
            except OSError as e:
                raise WorldError("玩法包路径异常") from e
            plays_root = self.plays_dir.resolve()
            if resolved.parent != plays_root or resolved.name != play_id:
                raise WorldError("玩法包路径不合法，拒绝卸载")
            dependents = [
                info.play_id
                for info in self.plays.values()
                if play_id in info.spec.requires_plays
            ]
            if dependents:
                raise WorldError(
                    f"仍有玩法包依赖它：{'、'.join(sorted(dependents))}，请先停用依赖者"
                )
            try:
                shutil.rmtree(resolved)
            except OSError as e:
                raise WorldError(f"删除玩法包目录失败：{e}") from e
            info = self.plays.get(play_id)
            # 只有"已加载的这个实例就来自刚删掉的目录"才卸载它——同名残留 + 内置
            # 同时存在时，已加载的是内置那份，删掉社区残留不该把内置也摘下来
            if info is not None and info.path.resolve() == resolved:
                self.plays.pop(play_id, None)
                await self._teardown_one(info, purge=True)
            # 还有别的社区目录同名 → 保留禁用标记（未删干净就别清状态）
            if not [c for c in self._find_candidates(play_id) if not c[1]]:
                self._disabled.discard(play_id)
            await self._save_disabled_state()
            logger.info("[worlditor] 玩法包已卸载：%s", play_id)
        await self._notify_plays_changed("uninstall")

    async def install_zip(self, data: bytes, *, filename: str = "") -> str:
        """安装社区玩法包（zip 字节流；安全校验 → 解压到 plays_dir → 加载）。

        包结构要求：zip 内**恰好一个顶层目录** ``<play_id>/``，其中含
        ``play.yaml`` 与 ``main.py``；顶层目录名必须 **== play.yaml 的 name**、
        且以 ``worlditor_play_`` 开头（安装与卸载都按目录名定位，不一致会导致
        "装得上却卸不掉"）。

        Args:
            data: zip 文件字节。
            filename: 原始文件名（仅用于错误提示）。

        Returns:
            安装并加载成功的 play_id。

        Raises:
            WorldError: 体积超限 / zip 非法 / 结构不符 / play_id 非法或缺前缀 /
                目录名与 play.yaml name 不一致 / 目录已存在 / play_id 被占用 /
                加载失败（失败时自动回滚已解压目录）。
        """
        if len(data) > _MAX_PLAY_ZIP_BYTES:
            raise WorldError(
                f"玩法包体积过大（上限 {_MAX_PLAY_ZIP_BYTES // (1024 * 1024)} MB）"
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise WorldError(f"不是有效的 zip 包：{filename or '上传内容'}") from e
        members = [i for i in archive.infolist() if not i.is_dir()]
        if not members:
            raise WorldError("zip 包为空")
        unpacked = sum(i.file_size for i in archive.infolist())
        if unpacked > _MAX_PLAY_ZIP_UNPACKED:
            raise WorldError("解压后体积过大，拒绝安装")
        # 顶层目录必须唯一（避免散文件与多包混装）
        tops = set()
        for item in archive.infolist():
            parts = _zip_parts(item.filename)
            if not parts:
                continue
            if not item.is_dir() and len(parts) == 1:
                raise WorldError("包结构错误：请把玩法包放在单个顶层目录里再打包")
            tops.add(parts[0])
        if len(tops) != 1:
            raise WorldError(
                "包结构错误：需要且仅需要一个顶层目录（如 worlditor_play_xxx/）"
            )
        play_id = next(iter(tops))
        if not _PLAY_ID_RE.match(play_id):
            raise WorldError(
                f"play_id 非法：{play_id}（仅允许字母/数字/下划线/连字符）"
            )
        # 前缀是**加载的硬条件**（discover 只认 worlditor_play_*）——少了它包能解压
        # 成功却永远不出现在清单里，重启后静默消失，目录还删不掉
        if not play_id.startswith(PLAY_PREFIX):
            raise WorldError(f"play_id 必须以 {PLAY_PREFIX} 开头：{play_id}")
        target = self.plays_dir / play_id
        if target.exists():
            raise WorldError(f"玩法包目录已存在：{play_id}（如需更新请先卸载）")
        # 同 play_id 已在别处（内置目录 / 名字不同的目录）：装下去会顶掉那个包，
        # 而卸载按 play_id 找的是先扫到的那个 → 新装的目录再也删不掉
        existing = self._find_candidate(play_id)
        if existing is not None:
            where = "内置包" if existing[1] else "另一个目录里的同名包"
            raise WorldError(f"play_id 已被{where}占用：{play_id}（{existing[0]}）")
        self.plays_dir.mkdir(parents=True, exist_ok=True)
        root = self.plays_dir.resolve()
        try:
            for item in archive.infolist():
                parts = _zip_parts(item.filename)
                if not parts:
                    continue
                dest = self.plays_dir.joinpath(*parts)
                if not dest.resolve().is_relative_to(root):
                    raise WorldError("包内路径越界，拒绝安装")
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        if not (target / "play.yaml").is_file() or not (target / "main.py").is_file():
            shutil.rmtree(target, ignore_errors=True)
            raise WorldError("包内缺少 play.yaml 或 main.py")
        # 目录名必须 == play.yaml 的 name：安装/卸载都按**目录名**定位（uninstall 要求
        # 目录名 == play_id），不一致时包能装上、却两个名字都卸不掉（实测）
        spec = load_play_spec(target)
        if spec is None:
            shutil.rmtree(target, ignore_errors=True)
            raise WorldError(
                "包内 play.yaml 非法（name 必须为 worlditor_play_* 且 version 非空）"
            )
        if spec.play_id != play_id:
            shutil.rmtree(target, ignore_errors=True)
            raise WorldError(
                f"包结构错误：顶层目录名 {play_id} 与 play.yaml 的 name "
                f"{spec.play_id} 不一致（两者必须相同）"
            )
        info = await self.load_one(target, None)
        if info is None:
            reason = self._load_errors.pop(play_id, "加载失败")
            shutil.rmtree(target, ignore_errors=True)
            raise WorldError(f"玩法包加载失败：{reason}")
        self._disabled.discard(play_id)
        await self._save_disabled_state()
        logger.info("[worlditor] 玩法包已安装：%s", play_id)
        await self._notify_plays_changed("install")
        return play_id

    def _find_candidate(self, play_id: str) -> tuple[Path, bool] | None:
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is not None and spec.play_id == play_id:
                return path, builtin
        return None

    def _find_candidates(self, play_id: str) -> list[tuple[Path, bool]]:
        """全部同 id 候选目录（同名目录可能有多个：内置包 + 社区残留）。"""
        out: list[tuple[Path, bool]] = []
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is not None and spec.play_id == play_id:
                out.append((path, builtin))
        return out

    def _find_candidate_ids(self) -> set[str]:
        ids: set[str] = set()
        for path, _ in self.discover():
            spec = load_play_spec(path)
            if spec is not None:
                ids.add(spec.play_id)
        return ids

    async def _teardown_one(self, info: PlayInfo, *, purge: bool = False) -> None:
        """卸载单个玩法包：teardown(api)（可选）+ 清注册 + 解绑。

        Args:
            info: 待卸载的包。
            purge: 真卸载（删包目录）传 True——连**标签归属记忆**（D26：query 的激活
                判定用）一并删除；停用/整体卸载传 False，保留归属记忆。

        v2 / D37：原先这里还要"先落库删除本包注册的物品定义"（避免"幽灵物品"残留，
        并区分"用户数据"不删）——物品不在内核后，那段逻辑连同 ``keep_user_items``
        参数一起删除；"用户数据 vs 包声明"现在由存储位置天然区分（本地实体模板落
        `templates` 表、包注册模板在引擎内存表）。
        """
        teardown = getattr(info.module, "teardown", None)
        if callable(teardown):
            try:
                result = teardown(info.api)
                # setup 支持 async（v0.2.0），teardown 同理——不 await 的话
                # "在 teardown 里取消自管 task"（G5 约定）静默不生效
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception("[worlditor] 玩法包 teardown 异常：%s", info.play_id)
        # v2 / D37：原"落库删除本包注册的物品定义"已移除（内核不再有物品定义）
        self.engine.clear_play_registrations(info.play_id, purge=purge)
        self.engine.detach_play_api(info.play_id)
        # 模块缓存清理必须在 teardown **之后**（teardown 还要用包里的代码）
        self._forget_modules(info.play_id)

    # ---------- 整体卸载 ----------

    async def unload_all(self) -> None:
        """卸载全部玩法包（teardown(api) 可选；随内核重载，C2）。"""
        for info in list(self.plays.values()):
            await self._teardown_one(info)
        self.plays.clear()
