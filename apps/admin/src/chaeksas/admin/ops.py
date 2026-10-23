"""명령줄(`chk-admin`)과 창(`chk-admin-ui`)이 **함께 쓰는** Admin 동작 (ADR-0089).

서명하는 입구는 둘이지만 확인 문구·봉투 내용·서명할 키 고르기는 여기 한 자리다 — 두 벌이면
「창에서 본 것과 서명한 것이 다르다」가 된다. **Qt를 모른다.**

개인키는 `sign()` 한 번 안에서만 열린다. 암호는 부르는 쪽이 받아 넘기고 여기서 쥐고 있지 않는다.
"""

from __future__ import annotations

import ipaddress
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from chaeksas.admin import keys as keystore
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.admin.connection import SHELL_LOCAL, SHELL_SSH, ServerShell
from chaeksas.contracts.signing import AdminKey, Envelope, key_id_for, sign


def now_iso() -> str:
    return datetime.now(UTC).isoformat()

# ─────────────────────────── 서명 ───────────────────────────


def sign_with(key: keystore.StoredKey, payload: dict[str, Any], *, passphrase: str | None) -> Envelope:
    """키를 **열고 서명하고 놓는다** — 열린 키는 이 함수 밖으로 나가지 않는다."""
    private = keystore.load(key, passphrase=passphrase)
    return sign(payload, private, signed_at=now_iso())


# ─────────────────────────── 키 ───────────────────────────


@dataclass(frozen=True)
class KeyRow:
    """ADM-01 표의 한 줄. `state`는 「등록됨」·「등록 안 됨」·「철회됨」·「알 수 없음」."""

    key: keystore.StoredKey
    state: str

    @property
    def registered(self) -> bool:
        return self.state == "등록됨"


@dataclass(frozen=True)
class KeyStates:
    """이 PC의 키들과 Center가 아는 것. `center_keys`가 `None`이면 **닿지 못했다**."""

    rows: list[KeyRow]
    center_keys: list[AdminKey] | None
    problem: str = ""

    @property
    def active_in_center(self) -> list[AdminKey]:
        return [one for one in self.center_keys or [] if not one.revoked]

    @property
    def needs_bootstrap(self) -> bool:
        """Center에 닿았고 Admin 키가 **하나도 없다** — 첫 키를 넣을 때다."""
        return self.center_keys is not None and not self.center_keys


def key_states(center: Center) -> KeyStates:
    """**모르는 것을 안다고 하지 않는다** — Center에 닿지 못하면 상태는 「알 수 없음」이다."""
    found = keystore.listing()
    try:
        known: list[AdminKey] | None = center.admin_keys()
        problem = ""
    except CenterProblem as e:
        known, problem = None, str(e)
    by_id = {one.key_id: one for one in known or []}
    rows = []
    for one in found:
        if known is None:
            state = "알 수 없음"
        else:
            at = by_id.get(one.key_id)
            state = "등록 안 됨" if at is None else ("철회됨" if at.revoked else "등록됨")
        rows.append(KeyRow(key=one, state=state))
    order = {"등록됨": 0, "알 수 없음": 1, "등록 안 됨": 2, "철회됨": 3}
    rows.sort(key=lambda row: (order.get(row.state, 9), row.key.created_at))
    return KeyStates(rows=rows, center_keys=known, problem=problem)


def choose_key(center: Center, explicit: str | None = None) -> tuple[keystore.StoredKey, bool]:
    """서명할 키. 둘째 값은 「Center가 아는 것이라 골랐다」(사람에게 한 줄로 말할 거리).

    적었으면 그것. 하나면 그것. 여럿이면 **Center에 등록되어 있고 철회되지 않은 것이 정확히
    하나일 때만** 그것 — 짐작이 아니라 Center가 받아 줄 키다. 그 밖은 `keystore.find`가
    `--key`로 고르라고 말한다 (아무거나 쓰지 않는다).
    """
    if explicit:
        return keystore.find(explicit), False
    found = keystore.listing()
    if len(found) > 1:
        try:
            registered = {one.key_id for one in center.admin_keys() if not one.revoked}
        except CenterProblem:
            registered = set()
        usable = [one for one in found if one.key_id in registered]
        if len(usable) == 1:
            return usable[0], True
    return keystore.find(None), False


def admin_key_payload(key: keystore.StoredKey, *, label: str | None = None) -> dict[str, Any]:
    """새 공개키를 **기존 키의 서명으로** 더하는 봉투 내용 (C2 `admin_key`)."""
    return {
        "kind": "admin_key",
        "key_id": key_id_for(key.public_bytes()),
        "public_key": key.public_path.read_text(encoding="utf-8").strip(),
        "label": label or key.label,
    }


def admin_key_revoke_payload(key_id: str, reason: str) -> dict[str, Any]:
    return {"kind": "admin_key_revoke", "key_id": key_id, "reason": reason, "revoked_at": now_iso()}


REVOKE_KEY_WARNING = "{key_id}를 철회하면 이 키로 서명한 승인·배포가 모두 무효가 됩니다. 계속할까요?"


def delete_refusal(states: KeyStates, key_id: str) -> str | None:
    """지우면 **Admin이 잠기는** 키면 그 까닭. 지워도 되면 `None` (ADM-01 「지우기」)."""
    active = states.active_in_center
    if len(active) == 1 and active[0].key_id == key_id:
        return "Center가 아는 유일한 Admin 키입니다 — 지우면 새 키를 넣을 서명자가 없어 잠깁니다"
    return None


def delete_warning(states: KeyStates, key_id: str) -> str | None:
    """한 번 더 물을 거리. Center에 살아 있는 키이거나, 모르면 묻는다."""
    if states.center_keys is None:
        return "Center에 닿지 못해 이 키가 등록됐는지 알 수 없습니다. 등록된 키라면 다시는 그 키로 서명할 수 없습니다."
    if any(one.key_id == key_id for one in states.active_in_center):
        return "Center에 등록된 키입니다. 이 PC에서 지우면 다시는 이 키로 서명할 수 없습니다(Center의 등록은 남습니다)."
    return None


# ─────────────────────────── 첫 키 (부트스트랩) ───────────────────────────

#: Center 이미지(`deploy/Dockerfile.center`)의 실행 명령과 같은 앞부분.
CENTER_IN_CONTAINER = ["uv", "run", "--frozen", "--package", "chaeksas-center", "chk-center"]
#: compose가 서비스 이름으로 붙이는 꼬리표 (`deploy/compose.yaml`의 `center`).
CENTER_LABEL = "label=com.docker.compose.service=center"


def bootstrap_command(key: keystore.StoredKey) -> str:
    """다른 서버의 Center라면 **그 서버 셸에서** 칠 명령 (사람이 복사한다)."""
    return f'chk-center admin-keys bootstrap {key.public_path.name} "{key.label or key.key_id}"'


def is_loopback(url: str) -> bool:
    host = (urlsplit(url).hostname or "").strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class FoundCenter:
    """서버 셸에서 찾은 Center. `problem`이 있으면 찾지 못했다 (사람에게 그대로 말한다)."""

    shell: ServerShell
    container: str = ""
    command: str = ""
    problem: str = ""

    @property
    def ok(self) -> bool:
        return not self.problem

    def describe(self) -> str:
        what = f"컨테이너 {self.container[:12]}" if self.container else f"명령 「{self.command}」"
        return f"{self.shell.where()}의 {what}"


def _in_shell(shell: ServerShell, argv: list[str], *, remote: str | None = None) -> list[str]:
    """그 셸에서 돌릴 명령줄. SSH는 **암호를 묻지 않는다**(`BatchMode`) — 키·에이전트로 들어간다.

    SSH 쪽은 원격 셸이 한 줄을 읽으므로 인자를 따옴표로 묶어 한 덩이로 넘긴다(`remote`가 있으면
    그것이 이미 지은 한 줄이다 — 「Center 명령」에 `cd … &&`가 들어갈 수 있다).
    """
    if shell.kind == SHELL_SSH:
        return [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", str(shell.ssh_port),
            shell.ssh_target, "--", remote if remote is not None else shlex.join(argv),
        ]
    return argv


def _last_line(done: Any) -> str:
    lines = [one for one in (done.stdout or "").splitlines() + (done.stderr or "").splitlines() if one.strip()]
    return lines[-1] if lines else f"종료 코드 {done.returncode}"


def find_center(shell: ServerShell, url: str, *, run: Any = subprocess.run) -> FoundCenter:
    """그 셸에서 Center를 찾는다 — 「Center 명령」을 적었으면 그것, 아니면 compose 컨테이너 **하나**.

    「이 PC」는 주소가 루프백일 때만이다 — 주소가 다른 곳이면 이 PC의 Center는 그 Center가 아니다.
    컨테이너가 둘 이상이면 고르지 않는다 (엉뚱한 Center에 Admin 키가 들어간다).
    """
    if shell.kind == SHELL_LOCAL:
        if not is_loopback(url):
            return FoundCenter(shell, problem=f"Center 주소({url})가 이 PC가 아닙니다 — 서버 셸을 SSH로 고르세요")
    elif shell.kind == SHELL_SSH:
        if not shell.ssh_target:
            return FoundCenter(shell, problem="SSH 대상(사용자@호스트)이 비어 있습니다")
    else:
        return FoundCenter(shell, problem="서버 셸을 설정하지 않았습니다")
    if shell.center_command:
        return FoundCenter(shell, command=shell.center_command)
    if shell.kind == SHELL_LOCAL and shutil.which("docker") is None:
        return FoundCenter(
            shell, problem="이 PC에 docker가 없습니다 — docker 없이 띄웠다면 「Center 명령」을 적으세요"
        )
    try:
        done = run(
            _in_shell(shell, ["docker", "ps", "--filter", CENTER_LABEL, "--format", "{{.ID}}"]),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return FoundCenter(shell, problem=f"셸을 열지 못했습니다: {e}")
    if done.returncode != 0:
        if shell.kind == SHELL_SSH and done.returncode == 255:
            return FoundCenter(
                shell, problem=f"SSH로 들어가지 못했습니다 (암호 대신 SSH 키가 있어야 합니다): {_last_line(done)}"
            )
        return FoundCenter(shell, problem=f"docker를 부르지 못했습니다: {_last_line(done)}")
    ids = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
    if not ids:
        return FoundCenter(
            shell,
            problem="Center 컨테이너가 없습니다 — Center가 떠 있는지, docker 없이 띄웠다면 「Center 명령」을 적으세요",
        )
    if len(ids) > 1:
        return FoundCenter(
            shell, problem=f"Center 컨테이너가 {len(ids)}개라 고르지 않습니다 — 「Center 명령」으로 정하세요"
        )
    return FoundCenter(shell, container=ids[0])


@dataclass
class BootstrapResult:
    ok: bool
    message: str
    output: list[str] = field(default_factory=list)


def bootstrap(found: FoundCenter, key: keystore.StoredKey, *, run: Any = subprocess.run) -> BootstrapResult:
    """서버 셸에서 `chk-center admin-keys bootstrap`을 돌린다 (C2 — 서버 셸에서만, ADR-0089 §6).

    공개키는 stdin으로 건넨다 — 서버에 파일을 들이지 않는다. **들어갔는지는 부르는 쪽이 Center API로
    확인한다** (셸과 주소가 다른 서버를 가리킬 수 있다).
    """
    label = key.label or key.key_id
    tail = ["admin-keys", "bootstrap", "/dev/stdin", label]
    if found.container:
        argv = _in_shell(found.shell, ["docker", "exec", "-i", found.container, *CENTER_IN_CONTAINER, *tail])
    elif found.shell.kind == SHELL_SSH:
        argv = _in_shell(found.shell, [], remote=f"{found.command} {shlex.join(tail)}")
    else:
        # 이 PC에서는 셸을 거치지 않는다 (`shell=True` 금지, CLAUDE.md §5) — 프로그램과 인자로 나눈다.
        argv = [*shlex.split(found.command, posix=sys.platform != "win32"), *tail]
    try:
        done = run(
            argv,
            input=key.public_path.read_text(encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return BootstrapResult(False, f"서버 셸에서 실행하지 못했습니다: {e}")
    lines = [one for one in (done.stdout or "").splitlines() + (done.stderr or "").splitlines() if one.strip()]
    if done.returncode == 0:
        return BootstrapResult(True, f"첫 Admin 키를 넣었습니다 — {key.key_id} ({found.describe()})", lines)
    return BootstrapResult(False, f"첫 키를 넣지 못했습니다: {_last_line(done)}", lines)


# ─────────────────────────── 외부 확장 (C13) ───────────────────────────


@dataclass(frozen=True)
class ExtensionReview:
    """서명 **전에** 보일 것. `problems`가 있으면 서명하지 않는다 (E1·E3을 먼저 돌린다)."""

    definition: dict[str, Any]
    id: str = ""
    version: str = ""
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        from chaeksas.contracts.extension import definition_hash  # noqa: PLC0415

        return {
            "kind": "extension",
            "id": self.id,
            "version": self.version,
            "definition_hash": definition_hash(self.definition),
        }


def read_definition(path: str | Path) -> dict[str, Any]:
    import json  # noqa: PLC0415

    try:
        found = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise keystore.KeyError_(f"정의 파일을 읽지 못했습니다: {e}") from e
    if not isinstance(found, dict):
        raise keystore.KeyError_("정의 파일이 JSON 객체가 아닙니다")
    return found


def review_extension(definition: dict[str, Any]) -> ExtensionReview:
    """정의를 검사하고 **사람이 볼 줄**을 짓는다 — 정의가 Bot의 키를 어느 주소로 보낼지 정하므로
    허용 호스트와 결정 수행 허용을 눈으로 확인하게 한다 (ADM-04)."""
    from chaeksas.contracts.extension import (  # noqa: PLC0415
        ExtensionManifest,
        definition_hash,
        validate,
    )

    try:
        manifest = ExtensionManifest.model_validate(definition)
    except ValueError as e:
        return ExtensionReview(definition, problems=[f"정의가 C13과 맞지 않습니다: {str(e).splitlines()[0]}"])
    problems = [f"[{one.rule}/{one.code}] {one.message}" for one in validate(manifest, from_center=True)]
    lines = [
        f"{manifest.id}@{manifest.version} · {manifest.name} · 등급 {manifest.tier}",
        f"  해시: {definition_hash(definition)}",
    ]
    adapter = manifest.service.adapter if manifest.service else None
    if adapter is not None:
        lines.append(f"  허용 호스트: {', '.join(adapter.allowed_hosts) or '(없음)'}")
        lines.append(f"  사설망 허용: {'예' if adapter.allow_private_network else '아니오'}")
        for op in adapter.operations:
            lines.append(f"  작업 {op.name}: {', '.join(op.modes)}{' · 멱등' if op.idempotent else ''}")
    return ExtensionReview(definition, manifest.id, manifest.version, lines, problems)


def extension_revoke_payload(extension_id: str, version: str, reason: str) -> dict[str, Any]:
    return {
        "kind": "extension_revoke",
        "id": extension_id,
        "version": version,
        "reason": reason,
        "revoked_at": now_iso(),
    }


REVOKE_EXTENSION_WARNING = "{id}@{version}의 승인을 철회하면 이 정의를 쓰는 Bot이 실행 불가가 됩니다. 계속할까요?"


__all__ = [
    "REVOKE_EXTENSION_WARNING",
    "REVOKE_KEY_WARNING",
    "BootstrapResult",
    "ExtensionReview",
    "KeyRow",
    "KeyStates",
    "admin_key_payload",
    "admin_key_revoke_payload",
    "FoundCenter",
    "bootstrap",
    "bootstrap_command",
    "find_center",
    "choose_key",
    "delete_refusal",
    "delete_warning",
    "extension_revoke_payload",
    "is_loopback",
    "key_states",
    "now_iso",
    "read_definition",
    "review_extension",
    "sign_with",
]
