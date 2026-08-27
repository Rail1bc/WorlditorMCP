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
import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..engine import WorldEngine, WorldError
from .api import WorlditorPlayAPI
from .spec import PlaySpec, load_play_spec, version_ok

logger = logging.getLogger("worlditor")

_PLAY_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
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
        worlditor_version: str = "0.3.0",
    ) -> None:
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

    @staticmethod
    def _plugin_root_dir() -> Path:
        """当前包目录（world/play/__init__.py → 上三级 = worlditor_mcp 包）。"""
        return Path(__file__).resolve().parents[2]

    def register_plugin_aliases(self) -> None:
        """把当前服务包注册为顶层名（幂等）。

        玩法包统一按文档路径导入：``from worlditor_mcp.api import ...``。
        独立服务环境包以正规名加载（顶层名已在 sys.modules），此处幂等跳过；
        保留供宿主以 ``data.plugins.*`` 形式加载的兼容场景。
        """
        top = self._plugin_root_dir().name  # worlditor_mcp
        if top in sys.modules:
            return
        root = self._plugin_root_dir()
        root_name = None
        for name, mod in list(sys.modules.items()):
            paths = getattr(mod, "__path__", None)
            if not paths:
                continue
            if not (name == top or name.endswith("." + top)):
                continue
            try:
                resolved = {Path(str(p)).resolve() for p in paths}
            except (OSError, TypeError):
                continue
            if root in resolved or root.parent in resolved:
                root_name = name
                break
        if root_name is None:
            logger.warning(
                "[worlditor] 未定位当前服务包模块，玩法包按顶层包名导入可能失败"
            )
            return
        for name, mod in list(sys.modules.items()):
            if name == root_name or name.startswith(root_name + "."):
                sys.modules[top + name[len(root_name) :]] = mod
        logger.info("[worlditor] 服务包顶层别名注册：%s → %s", root_name, top)

    async def load_all(self, context: Any | None = None) -> list[PlayInfo]:
        """按启用标记与依赖拓扑加载全部候选玩法包；返回成功加载的列表。"""
        self.register_plugin_aliases()
        await self._load_disabled_state()
        self._load_errors = {}
        specs: dict[str, tuple[PlaySpec, Path, bool]] = {}
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is not None:
                specs[spec.play_id] = (spec, path, builtin)
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
        await self.engine.flush_item_defs()
        return loaded

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
            setup(api, context)
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
            # 回滚半注册（kind/interaction/event/ui/字段/原语分派按 play_id 清理）
            self.engine.clear_play_registrations(spec.play_id)
            self.engine.detach_play_api(spec.play_id)
            return None
        except Exception:  # noqa: BLE001
            logger.exception("[worlditor] 玩法包加载失败：%s", path.name)
            self._load_errors[spec.play_id] = "加载异常（见日志）"
            # 回滚半注册（kind/interaction/event/ui/字段/原语分派按 play_id 清理）
            self.engine.clear_play_registrations(spec.play_id)
            self.engine.detach_play_api(spec.play_id)
            return None

    def _load_module(self, play_id: str, main_py: Path) -> Any:
        """importlib 加载玩法包 main.py（模块名 = play id）。"""
        spec = importlib.util.spec_from_file_location(play_id, main_py)
        if spec is None or spec.loader is None:
            raise RuntimeError("无法创建模块加载器")
        module = importlib.util.module_from_spec(spec)
        sys.modules[play_id] = module
        spec.loader.exec_module(module)
        return module

    # ---------- 管理（§4.3：list / enable / disable / uninstall） ----------

    def list_plays(self) -> list[dict]:
        """全部候选玩法包状态（loaded / disabled / load_failed + 错误详情）。"""
        out: list[dict] = []
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
                    }
                )
                continue
            if spec.play_id in self.plays:
                status = "loaded"
                error = ""
            elif spec.play_id in self._disabled:
                status = "disabled"
                error = ""
            else:
                status = "load_failed"
                error = self._load_errors.get(spec.play_id, "未加载")
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
                }
            )
        return sorted(out, key=lambda p: (p["builtin"], p["play_id"]))

    async def enable(self, play_id: str) -> None:
        """启用玩法包：自动先启用其 requires.plays 依赖（拓扑，G6）。"""
        async with self.engine._lock:  # noqa: SLF001
            await self._enable_inner(play_id, set())

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

    async def uninstall(self, play_id: str) -> None:
        """卸载社区玩法包（删除目录含其数据，不可逆；G7 路径安全）。"""
        if not _PLAY_ID_RE.match(play_id):
            raise WorldError("play_id 非法（仅允许字母/数字/下划线/连字符）")
        async with self.engine._lock:  # noqa: SLF001
            target = self._find_candidate(play_id)
            if target is None:
                raise WorldError(f"玩法包不存在：{play_id}")
            path, builtin = target
            if builtin:
                raise WorldError("内置玩法包仅可停用，不可卸载")
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
            info = self.plays.pop(play_id, None)
            if info is not None:
                await self._teardown_one(info)
            self._disabled.discard(play_id)
            await self._save_disabled_state()
            try:
                shutil.rmtree(resolved)
            except OSError as e:
                raise WorldError(f"删除玩法包目录失败：{e}") from e
            logger.info("[worlditor] 玩法包已卸载：%s", play_id)

    def _find_candidate(self, play_id: str) -> tuple[Path, bool] | None:
        for path, builtin in self.discover():
            spec = load_play_spec(path)
            if spec is not None and spec.play_id == play_id:
                return path, builtin
        return None

    def _find_candidate_ids(self) -> set[str]:
        ids: set[str] = set()
        for path, _ in self.discover():
            spec = load_play_spec(path)
            if spec is not None:
                ids.add(spec.play_id)
        return ids

    async def _teardown_one(self, info: PlayInfo) -> None:
        """卸载单个玩法包：teardown(api)（可选）+ 清注册 + 解绑。"""
        teardown = getattr(info.module, "teardown", None)
        if callable(teardown):
            try:
                teardown(info.api)
            except Exception:  # noqa: BLE001
                logger.exception("[worlditor] 玩法包 teardown 异常：%s", info.play_id)
        self.engine.clear_play_registrations(info.play_id)
        self.engine.detach_play_api(info.play_id)

    # ---------- 整体卸载 ----------

    async def unload_all(self) -> None:
        """卸载全部玩法包（teardown(api) 可选；随内核重载，C2）。"""
        for info in list(self.plays.values()):
            await self._teardown_one(info)
        self.plays.clear()
