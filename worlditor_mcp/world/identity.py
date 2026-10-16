"""身份注册与凭据（B13 自助注册 / B4 token 三档）。

统一注册机制服务两类接入者：人类（WebUI）与 agent（MCP/远程），
**不依赖管理员人工签发**：

- ``auth_mode`` 三种世界注册模式：open（开放）/ invite（邀请码）/ closed（封闭）。
- token 三档：``read``（围观，开放模式可公开获取免注册）/ ``play``（移动/交互/
  说话）/ ``admin``（编辑/管理）。
- 人类 = 账户（用户名+密码）→ 凭据；agent = 注册接口 → 凭据 + **一条主体记录**。
- **注册不创建实体**（D45）：内核不诞生角色、不指定落点。"我以哪具化身行动"
  由玩法包经 ``api.act_as`` / ``api.claim_avatar`` 决定（D46）——所以新凭据的
  ``entity_id`` 为空是**合法常态**，不是"注册没成功"。
- ``admin_key`` 配置：注册时提供它的账户自动成为管理员（管理员只做配置、
  邀请码与吊销）。

密码哈希用 PBKDF2-HMAC-SHA256（标准库，无外部依赖）；token 为 secrets 随机
hex。身份服务是纯逻辑层（不依赖 AstrBot），可独立单测。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("worlditor")

AUTH_MODES = ("open", "invite", "closed")
_PBKDF2_ITERATIONS = 200_000

# **不可密码登录**的主体（agent 自助注册建的账户）用空哈希占位。
# 空串过不了 `_verify_password`（它按 `$` 分段，分不出来直接 False），
# 而 `_check_password` 要求至少 6 位——所以这种主体**永远**登不进来，
# 也**改不出**密码（`change_password` 要先验原密码）。它只是 roster 的键。
_NO_PASSWORD = ""


class IdentityError(Exception):
    """身份业务错误（用户名已存在、密码错误、模式限制等），消息可直接展示。"""


@dataclass
class Account:
    """人类账户（唯一标识 = uuid4 hex）。"""

    id: str
    username: str
    password_hash: str
    role: str  # "user" | "admin"
    created_ts: float


@dataclass
class TokenInfo:
    """一份凭据：token → **这次连接以哪个实体行动**（可为空）+ 主体（账户）。

    ``entity_id`` 为空是**合法常态**（D45）：新注册的凭据还没有化身，或玩家的
    化身还没被玩法包选为"当前行动的那具"。内核只记这个指针，不解释它。
    """

    token: str
    entity_id: str
    tier: str
    kind: str  # "player" | "readonly"（v0.2.0 起不再有 agent 类型）
    account_id: str | None = None
    username: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "entity_id": self.entity_id,
            "tier": self.tier,
            "kind": self.kind,
            "username": self.username,
        }


def _hash_password(password: str) -> str:
    """PBKDF2 哈希：'pbkdf2$iter$salt_hex$hash_hex'。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iter_s),
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _new_token() -> str:
    return secrets.token_hex(24)


class IdentityService:
    """身份服务：注册 / 登录 / 凭据管理与校验（操作走引擎锁，防并发竞态）。"""

    def __init__(
        self,
        engine: Any,
        *,
        auth_mode: str = "open",
        admin_key: str = "",
        allow_agent_register: bool = True,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._engine = engine  # WorldEngine（创建 player/agent 实体）
        if auth_mode not in AUTH_MODES:
            raise ValueError(f"auth_mode 必须是 {'/'.join(AUTH_MODES)} 之一")
        self.auth_mode = auth_mode
        self.admin_key = admin_key or ""
        self.allow_agent_register = allow_agent_register
        self._clock = clock or time.time

    # ---------- 注册 / 登录 ----------

    async def register_human(
        self,
        username: str,
        password: str,
        *,
        invite_code: str | None = None,
        admin_key: str | None = None,
    ) -> TokenInfo:
        """人类自助注册：创建账户 + 发放 play 档凭据（**不创建实体**，D45）。

        注册只产出**凭据**——内核不诞生角色、不指定落点；"以哪具化身行动"由玩法包
        经 ``api.act_as`` 决定（D46）。所以返回的 ``token["entity_id"]`` 是空串，
        这是**正常结果**，不是失败。

        Raises:
            IdentityError: 模式限制 / 用户名非法或已存在 / 密码过弱 / 邀请码无效。
        """
        username = self._check_username(username)
        self._check_password(password)
        is_admin = bool(admin_key and self.admin_key and admin_key == self.admin_key)
        async with self._engine._lock:
            if not is_admin:
                # 校验必须与消费处于同一引擎锁内，避免并发复用一次性邀请码。
                self._check_invite(self.auth_mode, invite_code)
            if self._engine.store.get_account_by_username(username) is not None:
                raise IdentityError("用户名已存在")
            role = "admin" if is_admin else "user"
            account = Account(
                id=uuid.uuid4().hex,
                username=username,
                password_hash=_hash_password(password),
                role=role,
                created_ts=self._now(),
            )
            token = TokenInfo(
                token=_new_token(),
                entity_id="",
                tier="admin" if role == "admin" else "play",
                kind="player",
                account_id=account.id,
                username=username,
            )
            await self._engine.store.save_auth_bundle(
                account, token, self._now(), invite_code
            )
            return token

    async def register_agent(
        self, name: str, *, invite_code: str | None = None
    ) -> TokenInfo:
        """无密码自助注册（agent / 脚本友好；B13）。

        与人类注册的唯一差别是**不设密码**：主体记录照建（``password_hash`` 为空
        ——永远登不进来，也改不出密码），这样 agent 才有**稳定的主体键**——
        否则"重连 = 换一个主体"，roster（它有几具化身）会跟着丢（D46 / 方案 D-c）。

        Raises:
            IdentityError: 模式限制 / 自助注册关闭 / 邀请码无效 / 名称非法或已被占用。
        """
        name = self._check_username(name)
        if not self.allow_agent_register:
            raise IdentityError("agent 自助注册已关闭，请联系管理员")
        async with self._engine._lock:
            self._check_invite(self.auth_mode, invite_code)
            if self._engine.store.get_account_by_username(name) is not None:
                raise IdentityError("名称已被占用")
            account = Account(
                id=uuid.uuid4().hex,
                username=name,
                password_hash=_NO_PASSWORD,
                role="user",
                created_ts=self._now(),
            )
            token = TokenInfo(
                token=_new_token(),
                entity_id="",
                tier="play",
                kind="player",
                account_id=account.id,
                username=name,
            )
            await self._engine.store.save_auth_bundle(
                account, token, self._now(), invite_code
            )
            return token

    async def login(self, username: str, password: str) -> TokenInfo:
        """人类登录：校验密码，刷新凭据（旧 token 吊销）。

        D45：登录**不创建也不复活实体**——凭据的 ``entity_id`` 从空开始，
        "接着玩哪具化身"由玩法包自己记（它可以在自举工具里用 ``api.act_as``
        重新选定，见 docs/PLAY_DEV.md 玩家包契约）。管理员因此**始终能登录管理端**
        去启用世界包或建图（v0.2.0：内核不内置世界内容，不能让部署死锁在门口）。
        """
        async with self._engine._lock:
            account = self._engine.store.get_account_by_username(username.strip())
            if account is None or not _verify_password(password, account.password_hash):
                raise IdentityError("用户名或密码错误")
            await self._engine.store.revoke_tokens_of_account(account.id)
            token = await self._issue_token(
                entity_id="",
                tier="admin" if account.role == "admin" else "play",
                kind="player",
                account_id=account.id,
                username=account.username,
            )
            # D47：主体登录信号（玩法包据此"让化身入场"/恢复上次选中的化身）。
            # 在锁内发，handler 可重入调原语。
            await self._engine.emit_principal_event(
                "on_principal_login",
                account_id=account.id,
                username=account.username,
            )
            return token

    async def create_read_token(self) -> TokenInfo:
        """read 档围观凭据（开放模式可公开获取，免注册；B13）。"""
        if self.auth_mode != "open":
            raise IdentityError("当前模式不提供公开围观凭据")
        return await self._issue_token(entity_id="", tier="read", kind="readonly")

    # ---------- 凭据管理 ----------

    async def change_password(
        self, token: str, old_password: str, new_password: str
    ) -> None:
        """玩家自助改密（登录后旧凭据全部吊销，需重新登录）。"""
        info = self.resolve(token)
        if (
            info is None
            or info.tier not in ("play", "admin")
            or info.account_id is None
        ):
            raise IdentityError("无效的凭据")
        async with self._engine._lock:
            account = self._engine.store.get_account(info.account_id)
            if account is None or not _verify_password(
                old_password, account.password_hash
            ):
                raise IdentityError("原密码错误")
            self._check_password(new_password)
            account.password_hash = _hash_password(new_password)
            await self._engine.store.save_account(account)
            await self._engine.store.revoke_tokens_of_account(account.id)

    async def logout(self, token: str) -> bool:
        """注销当前凭据。"""
        return await self.revoke_token(token)

    async def revoke_token(self, token: str) -> bool:
        """吊销一份凭据（管理员吊销 agent 凭据 / 玩家注销）。

        D47：吊销一份**有主体**的凭据 → 发 ``on_principal_logout``（玩法包可据此
        让化身离场）。改密/登录时的**批量**吊销走 ``revoke_tokens_of_account``，
        那是"刷新凭据"不是"登出"，不发事件——否则多端登录会把化身反复踢下线。
        """
        async with self._engine._lock:
            info = self._engine.store.get_token(token)
            if info is None:
                return False
            revoked = await self._engine.store.set_token_revoked(token, True)
            if revoked and info.account_id:
                await self._engine.emit_principal_event(
                    "on_principal_logout",
                    account_id=info.account_id,
                    username=info.username or "",
                )
            return revoked

    # ---------- 账户检索（v0.1.12：管理端复杂管理） ----------

    def search_accounts(
        self,
        *,
        q: str = "",
        role: str = "",
        page: int = 1,
        page_size: int = 50,
        sort: str = "created_desc",
    ) -> dict:
        """账户检索（管理端）：q 用户名子串匹配 / role 精确 / 分页 / 排序。

        每行附带：创建时间、**该主体的全部化身**（名称/位置/最近活跃）、未吊销
        凭据数。排序选项：created_desc（默认）/ created_asc / username。

        D46：一个主体可以有 0 / 1 / N 具化身，所以这里是 ``entities`` 列表而不是
        单个 ``entity``——"哪个是主要的那具"由玩法包决定，内核没有这个排序概念。
        """
        accounts = list(self._engine.store.accounts.values())
        needle = (q or "").strip().lower()
        if needle:
            accounts = [a for a in accounts if needle in a.username.lower()]
        if role:
            accounts = [a for a in accounts if a.role == role]
        if sort == "username":
            accounts.sort(key=lambda a: a.username.lower())
        elif sort == "created_asc":
            accounts.sort(key=lambda a: a.created_ts)
        else:
            accounts.sort(key=lambda a: a.created_ts, reverse=True)
        total = len(accounts)
        per = min(max(1, int(page_size or 50)), 200)
        current = max(1, int(page or 1))
        start = (current - 1) * per
        rows = []
        for a in accounts[start : start + per]:
            entities = self._engine.entities_of_account(a.id)
            token_count = sum(
                1 for t in self._engine.store.tokens.values() if t.account_id == a.id
            )
            rows.append(
                {
                    "id": a.id,
                    "username": a.username,
                    "role": a.role,
                    "created_ts": a.created_ts,
                    "entities": [e.to_dict() for e in entities],
                    "token_count": token_count,
                }
            )
        return {
            "accounts": rows,
            "total": total,
            "page": current,
            "page_size": per,
        }

    def list_account_tokens(self, account_id: str) -> list[dict]:
        """账户未吊销凭据明细（管理端；token 完整返回供吊销/复制）。"""
        return [
            {
                "token": t.token,
                "tier": t.tier,
                "kind": t.kind,
                "entity_id": t.entity_id,
                "username": t.username,
            }
            for t in self._engine.store.tokens.values()
            if t.account_id == account_id
        ]

    # ---------- 账户生命周期（永久注销 / 角色管理） ----------

    async def delete_own_account(self, token: str) -> None:
        """本人永久注销：删账户 + 吊销全部凭据 + 删除玩家实体（不可恢复）。

        token 即凭据（与改密/登出同权限模型）；确认由调用方 UI 承担。
        """
        info = self.resolve(token)
        if info is None or not info.account_id:
            raise IdentityError("无效的凭据")
        await self.delete_account(info.account_id)

    async def delete_account(self, account_id: str) -> None:
        """永久注销账户（管理员 / 本人通道共用）。

        级联：账户行 + 全部凭据（吊销）+ **该主体的全部化身**（受控删除，D14 /
        D42 / D46）+ ``on_principal_deleted`` 事件（玩法包据此清自己的 roster）。
        实体删除会触发 on_entity_removed / on_world_edited。

        两层保险的理由：内核删的是"绑了这个账户的实体"，玩法包记的是"这个主体
        有哪些化身"——**只有两边都清**才不会留下孤儿（内核清单是权威数据，
        事件是给包的信号）。

        Raises:
            IdentityError: 账户不存在。
        """
        async with self._engine._lock:
            account = self._engine.store.get_account(account_id)
            if account is None:
                raise IdentityError("账户不存在")
            await self._engine.store.revoke_tokens_of_account(account_id)
            for entity in self._engine.entities_of_account(account_id):
                await self._engine.delete_account_entity(entity.id)
            await self._engine.store.delete_account(account_id)
            await self._engine.emit_principal_event(
                "on_principal_deleted",
                account_id=account_id,
                username=account.username,
            )

    async def set_account_role(self, account_id: str, role: str) -> dict:
        """变更账户角色（user/admin）：吊销全部凭据，重新登录按新角色。

        Raises:
            IdentityError: 账户不存在 / 角色非法。
        """
        if role not in ("user", "admin"):
            raise IdentityError("角色必须是 user 或 admin")
        async with self._engine._lock:
            account = self._engine.store.get_account(account_id)
            if account is None:
                raise IdentityError("账户不存在")
            account.role = role
            await self._engine.store.save_account(account)
            await self._engine.store.revoke_tokens_of_account(account_id)
        return {"username": account.username, "role": role}

    # ---------- 邀请码（invite 模式，管理员） ----------

    async def create_invite_codes(self, count: int = 1) -> list[str]:
        """批量生成邀请码（管理员）。"""
        codes: list[str] = []
        async with self._engine._lock:
            for _ in range(max(1, count)):
                code = secrets.token_hex(6)
                await self._engine.store.save_invite_code(code, self._now())
                codes.append(code)
        return codes

    def list_invite_codes(self) -> list[dict]:
        return self._engine.store.list_invite_codes()

    async def revoke_invite_code(self, code: str) -> bool:
        """吊销一个未使用的邀请码。"""
        async with self._engine._lock:
            return await self._engine.store.set_invite_code_used(code)

    # ---------- 凭据校验 ----------

    def resolve(self, token: str) -> TokenInfo | None:
        """解析 token → 身份；无效/已吊销/空返回 None。"""
        if not token:
            return None
        return self._engine.store.get_token(token)

    # ---------- 内部 ----------

    def _now(self) -> float:
        return self._clock()

    def _check_username(self, username: str) -> str:
        username = (username or "").strip()
        if not (2 <= len(username) <= 24):
            raise IdentityError("用户名长度须为 2-24 个字符")
        if not all(ch.isalnum() or ch in "_-" for ch in username):
            raise IdentityError("用户名只能包含字母、数字、下划线、连字符")
        return username

    def _check_password(self, password: str) -> None:
        if not password or len(password) < 6:
            raise IdentityError("密码至少 6 位")

    def _check_invite(self, mode: str, invite_code: str | None) -> None:
        if mode == "closed":
            raise IdentityError("当前世界为封闭模式，仅管理员可签发凭据")
        if mode == "invite":
            code = (invite_code or "").strip()
            entry = self._engine.store.get_invite_code(code)
            if entry is None or entry["used"]:
                raise IdentityError("邀请码无效或已使用")

    async def _issue_token(
        self,
        *,
        entity_id: str,
        tier: str,
        kind: str,
        account_id: str | None = None,
        username: str | None = None,
    ) -> TokenInfo:
        token = _new_token()
        info = TokenInfo(
            token=token,
            entity_id=entity_id,
            tier=tier,
            kind=kind,
            account_id=account_id,
            username=username,
        )
        await self._engine.store.save_token(info, self._now())
        return info
