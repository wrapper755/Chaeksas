"""`chk-admin` — 서명 키와 패키지 승인 (C2·C5, ADM-01·02).

**첫 릴리스는 명령줄만**이다 (`docs/06-screens/admin.md`). 서명은 토큰이 새도 배포를 못 하게
하는 마지막 관문이라 서버가 아니라 **관리자 PC에서** 한다.

- **되돌릴 수 없는 일은 묻는다** — 철회는 「계속할까요?」에 `y`를 받아야 한다 (U9).
- 승인할 때 **해시를 보여 준다.** 승인한 그 바이트가 아니면 승인이 아니다.
- 한글을 찍으므로 stdout을 UTF-8로 고정한다 (Windows 기본 코드페이지에서 죽는다).
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import UTC, datetime
from typing import Any

from chaeksas.admin import keys as keystore
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.contracts.signing import Envelope, key_id_for, sign

#: 승인을 기다리는 상태 (C5).
CANDIDATE = "candidate"

#: 되돌릴 수 없는 일에 받는 답 (U9 — 기본은 「아니오」다).
YES = ("y", "yes", "ㅇ")


def _utf8() -> None:
    """Windows의 cp949에서 한글을 찍다 죽지 않게 (CLAUDE.md §5)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ask(question: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in YES
    except EOFError:  # pragma: no cover — 파이프로 돌릴 때
        return False


def _sign(args: argparse.Namespace, payload: dict[str, Any]) -> Envelope:
    found = keystore.find(getattr(args, "key", None))
    private = keystore.load(found, passphrase=getattr(args, "passphrase", None))
    return sign(payload, private, signed_at=now_iso())


# ─────────────────────────── 키 (ADM-01) ───────────────────────────


def keys_new(args: argparse.Namespace, center: Center) -> int:
    made = keystore.create(label=args.label, passphrase=getattr(args, "passphrase", None))
    print(f"키를 만들었습니다 — {made.key_id}")
    print(f"  개인키: {made.path} (암호문)")
    print(f"  공개키: {made.public_path}")
    print("\n첫 키라면 서버에서: chk-center admin-keys bootstrap " + str(made.public_path))
    print("아니면: chk-admin keys register " + made.key_id + " --signed-by <기존 키>")
    return 0


def keys_list(args: argparse.Namespace, center: Center) -> int:
    found = keystore.listing()
    if not found:
        print("이 PC에 서명 키가 없습니다 — `chk-admin keys new`로 만드세요.")
        return 0
    registered = {}
    try:
        registered = {one.key_id: one for one in center.admin_keys()}
    except CenterProblem as e:
        # **모르는 것을 안다고 하지 않는다** — Center에 닿지 못하면 등록 여부를 비워 둔다.
        print(f"(Center에 닿지 못해 등록 여부를 알 수 없습니다 — {e})\n")
    for one in found:
        at = registered.get(one.key_id)
        state = "등록 안 됨" if at is None else ("철회됨" if at.revoked else "등록됨")
        print(f"{one.key_id}  {state}  {one.label or ''}  {one.created_at[:10]}")
    return 0


def keys_register(args: argparse.Namespace, center: Center) -> int:
    """새 공개키를 **기존 키의 서명으로** 등록한다 (C2 V8 — 자기 자신은 못 올린다)."""
    wanted = keystore.find(args.key_id)
    public = wanted.public_bytes()
    payload: dict[str, Any] = {
        "kind": "admin_key",
        "key_id": key_id_for(public),
        "public_key": wanted.public_path.read_text(encoding="utf-8").strip(),
        "label": args.label or wanted.label,
    }
    signer = keystore.find(args.signed_by)
    if signer.key_id == wanted.key_id:
        print("자기 자신으로는 등록할 수 없습니다 (C2 V8) — 다른 Admin 키로 서명하세요.")
        return 2
    print(f"{wanted.key_id}를 {signer.key_id}의 서명으로 추가합니다.")
    envelope = sign(payload, keystore.load(signer, passphrase=getattr(args, "passphrase", None)),
                    signed_at=now_iso())
    found = center.add_admin_key(envelope)
    print(f"등록했습니다 — {found.key_id}")
    return 0


def keys_revoke(args: argparse.Namespace, center: Center) -> int:
    if not _ask(
        f"{args.key_id}를 철회하면 이 키로 서명한 승인·배포가 모두 무효가 됩니다. 계속할까요?",
        assume_yes=args.yes,
    ):
        print("취소했습니다.")
        return 1
    payload = {
        "kind": "admin_key_revoke",
        "key_id": args.key_id,
        "reason": args.reason,
        "revoked_at": now_iso(),
    }
    found = center.revoke_admin_key(_sign(args, payload))
    print(f"철회했습니다 — {found.key_id} ({found.revoked_at})")
    return 0


# ─────────────────────────── 패키지 (ADM-02) ───────────────────────────


def pending(args: argparse.Namespace, center: Center) -> int:
    found = [one for one in center.packages() if one.get("status") == CANDIDATE]
    if not found:
        print("승인을 기다리는 패키지가 없습니다.")
        return 0
    for one in found:
        print(
            f"{one.get('id')}@{one.get('version')}  {one.get('kind')}  "
            f"{one.get('uploaded_by') or ''}  {one.get('content_hash', '')[:23]}…"
        )
    return 0


def approve(args: argparse.Namespace, center: Center) -> int:
    """승인 서명 → Center. **해시를 보여 주고 묻는다** — 그 바이트가 아니면 승인이 아니다."""
    info = center.package(args.id, args.version)
    print(f"{args.id}@{args.version} · {info.get('kind')} · {info.get('status')}")
    print(f"  해시: {info.get('content_hash')}")
    print(f"  올린 이: {info.get('uploaded_by') or '모름'}")
    if not _ask("승인할까요?", assume_yes=args.yes):
        print("취소했습니다.")
        return 1
    payload = {
        "kind": "package",
        "id": args.id,
        "version": args.version,
        "content_hash": info.get("content_hash"),
    }
    found = center.approve(args.id, args.version, _sign(args, payload))
    print(f"승인했습니다 — {found.get('id')}@{found.get('version')} ({found.get('status')})")
    return 0


def revoke_package(args: argparse.Namespace, center: Center) -> int:
    if not _ask(
        f"{args.id}@{args.version}의 승인을 철회하면 그 패키지의 배포가 모두 무효가 됩니다. 계속할까요?",
        assume_yes=args.yes,
    ):
        print("취소했습니다.")
        return 1
    payload = {
        "kind": "package_revoke",
        "id": args.id,
        "version": args.version,
        "reason": args.reason,
        "revoked_at": now_iso(),
    }
    found = center.revoke_package(args.id, args.version, _sign(args, payload))
    print(f"철회했습니다 — {found.get('id')}@{found.get('version')} ({found.get('status')})")
    return 0


# ─────────────────────────── 배포 (ADM-03) ───────────────────────────


def deploy(args: argparse.Namespace, center: Center) -> int:
    """배포 서명 → Center (C2 `deployment`). **대상과 유효 기간을 보여 주고 묻는다.**"""
    info = center.package(args.id, args.version)
    if info.get("status") != "approved":
        print(f"승인되지 않은 패키지입니다 (지금 {info.get('status')}) — 먼저 `chk-admin approve`")
        return 2
    print(f"{args.id}@{args.version} → Bot UI {args.bot_ui}")
    print(f"  해시: {info.get('content_hash')}")
    print(f"  유효: {args.start or '즉시'} ~ {args.until or '무기한'}")
    if not _ask("배포할까요?", assume_yes=args.yes):
        print("취소했습니다.")
        return 1

    payload: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": args.deployment_id or f"dep_{secrets.token_hex(4)}",
        "target": {"type": "bot_ui", "id": args.bot_ui},
        "bpm_process_id": args.id,
        "version": args.version,
        "content_hash": info.get("content_hash"),
        "not_before": args.start,
        "expires_at": args.until,
    }
    found = center.deploy(_sign(args, payload))
    print(f"배포했습니다 — {found.get('deployment_id')} → {found.get('target', {}).get('id')}")
    return 0


def deployments(args: argparse.Namespace, center: Center) -> int:
    found = center.deployments(bot_ui=args.bot_ui, active=not args.all)
    if not found:
        print("배포가 없습니다.")
        return 0
    for one in found:
        state = "철회됨" if one.get("revoked_at") else "활성"
        target = one.get("target", {})
        window = f"{one.get('not_before') or '즉시'} ~ {one.get('expires_at') or '무기한'}"
        print(
            f"{one.get('deployment_id')}  {state}  {target.get('type')}:{target.get('id')}  "
            f"{one.get('bpm_process_id')}@{one.get('version')}  {window}"
        )
    return 0


def revoke_deploy(args: argparse.Namespace, center: Center) -> int:
    if not _ask(f"배포 {args.deployment_id}를 철회할까요? (되살릴 수 없습니다)", assume_yes=args.yes):
        print("취소했습니다.")
        return 1
    payload = {
        "kind": "revoke",
        "deployment_id": args.deployment_id,
        "reason": args.reason,
        "revoked_at": now_iso(),
    }
    found = center.revoke_deployment(_sign(args, payload))
    print(f"철회했습니다 — {found.get('deployment_id')}")
    return 0


# ─────────────────────────── 작업 (C5 `/jobs`) ───────────────────────────


def _inputs(args: argparse.Namespace) -> dict[str, Any]:
    """`--input k=v`와 `--inputs <JSON>`을 합친다. 값은 JSON으로 읽고, 안 되면 문자열이다."""
    import json  # noqa: PLC0415 — 입력을 받을 때만 든다

    made: dict[str, Any] = {}
    if args.inputs:
        try:
            parsed = json.loads(args.inputs)
        except ValueError as e:
            raise CenterProblem(f"--inputs가 JSON이 아닙니다: {e}") from e
        if not isinstance(parsed, dict):
            raise CenterProblem("--inputs는 JSON 객체여야 합니다")
        made.update(parsed)
    for one in args.input or []:
        name, sep, value = one.partition("=")
        if not sep:
            raise CenterProblem(f"--input은 `이름=값` 모양입니다 (받은 것 {one!r})")
        try:
            made[name] = json.loads(value)
        except ValueError:
            made[name] = value  # 따옴표 없는 글자는 그대로 문자열
    return made


def job_new(args: argparse.Namespace, center: Center) -> int:
    """작업 지시 (ADM, 콘솔 CON-05와 같은 일). **서명이 없다** — 이미 배포된 것을 돌릴 뿐이다."""
    inputs = _inputs(args)
    print(f"{args.id}{'@' + args.version if args.version else ''} → Bot UI {args.bot_ui}")
    print(f"  입력: {len(inputs)}개" + (f" ({', '.join(sorted(inputs))})" if inputs else ""))
    print(f"  만료: {args.until or '없음'}")
    if not _ask("작업을 보낼까요?", assume_yes=args.yes):
        print("취소했습니다.")
        return 1

    body: dict[str, Any] = {
        "bpm_process_id": args.id,
        "target": {"type": "bot_ui", "id": args.bot_ui},
        "inputs": inputs,
        "version": args.version,
        "expires_at": args.until,
        "note": args.note,
        "idempotency_key": args.idempotency_key,
    }
    found = center.create_job({k: v for k, v in body.items() if v is not None})
    print(
        f"작업을 만들었습니다 — {found.get('job_id')} "
        f"({found.get('bpm_process_id')}@{found.get('version')}, {found.get('state')})"
    )
    return 0


def job_list(args: argparse.Namespace, center: Center) -> int:
    found = center.jobs(state=args.state, bot_ui=args.bot_ui, bpm_process_id=args.bpm_process)
    if not found:
        print("작업이 없습니다.")
        return 0
    for one in found:
        reason = one.get("state_reason") or one.get("cancel_result") or ""
        target = one.get("target", {})
        print(
            f"{one.get('job_id')}  {one.get('state')}{'(' + reason + ')' if reason else ''}  "
            f"{target.get('id')}  {one.get('bpm_process_id')}@{one.get('version')}  "
            f"{one.get('requested_by')}  {one.get('requested_at', '')[:19]}"
        )
    return 0


def job_show(args: argparse.Namespace, center: Center) -> int:
    one = center.job(args.job_id)
    print(f"{one.get('job_id')}  {one.get('state')}  {one.get('state_reason') or ''}")
    print(f"  Bot: {one.get('bpm_process_id')}@{one.get('version')} → {one.get('target', {}).get('id')}")
    print(f"  지시: {one.get('requested_by')} {one.get('requested_at')}")
    print(f"  입력: {sorted(one.get('inputs') or {})}")
    if one.get("run_id"):
        print(f"  실행: {one.get('run_id')} ({one.get('run_status') or '진행 중'})")
    if one.get("cancel_requested"):
        print(f"  취소: 요청됨 ({one.get('cancel_result') or '답 기다리는 중'})")
    return 0


def job_cancel(args: argparse.Namespace, center: Center) -> int:
    """취소. **현장이 이미 시작했으면 멈추지 않는다** (C5) — 그때는 거절이 돌아온다."""
    if not _ask(f"작업 {args.job_id}를 취소할까요?", assume_yes=args.yes):
        print("취소하지 않았습니다.")
        return 1
    found = center.cancel_job(args.job_id)
    if found.get("state") == "cancelled":
        print(f"취소했습니다 — {found.get('job_id')}")
    else:
        # 202 — 현장에 물어본 상태다. 그사이 시작했으면 `accepted`로 남는다 (C5).
        print(
            f"취소를 요청했습니다 — {found.get('job_id')} (지금 {found.get('state')}). "
            "다음 하트비트에 현장이 답합니다"
        )
    return 0


# ─────────────────────────── 명령줄 ───────────────────────────


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="chk-admin", description="Chaeksas Admin — 서명 (C2)")
    made.add_argument("--key", help="쓸 서명 키 id (키가 여럿일 때)")
    made.add_argument("-y", "--yes", action="store_true", help="확인 묻지 않기")
    subs = made.add_subparsers(dest="command", required=True)

    keys = subs.add_parser("keys", help="서명 키 (ADM-01)").add_subparsers(dest="sub", required=True)
    new = keys.add_parser("new", help="새 서명 키")
    new.add_argument("--label")
    new.set_defaults(run=keys_new)
    shown = keys.add_parser("list", help="이 PC의 키")
    shown.set_defaults(run=keys_list)
    register = keys.add_parser("register", help="공개키를 Center에 등록 (기존 키가 서명)")
    register.add_argument("key_id")
    register.add_argument("--signed-by", dest="signed_by", help="서명할 기존 키 id")
    register.add_argument("--label")
    register.set_defaults(run=keys_register)
    revoke = keys.add_parser("revoke", help="키 철회")
    revoke.add_argument("key_id")
    revoke.add_argument("--reason", default="관리자 철회")
    revoke.set_defaults(run=keys_revoke)

    waiting = subs.add_parser("pending", help="승인 대기 패키지 (ADM-02)")
    waiting.set_defaults(run=pending)

    ok = subs.add_parser("approve", help="패키지 승인 서명")
    ok.add_argument("id")
    ok.add_argument("version")
    ok.set_defaults(run=approve)

    sent = subs.add_parser("deploy", help="배포 서명 (ADM-03)")
    sent.add_argument("id")
    sent.add_argument("version")
    sent.add_argument("--bot-ui", dest="bot_ui", required=True, help="대상 Bot UI id")
    sent.add_argument("--from", dest="start", help="이때부터 (ISO 8601)")
    sent.add_argument("--until", dest="until", help="이때까지 (ISO 8601)")
    sent.add_argument("--deployment-id", dest="deployment_id", help="다시 올릴 때 (멱등)")
    sent.set_defaults(run=deploy)

    shown_deploys = subs.add_parser("deployments", help="배포 목록")
    shown_deploys.add_argument("--bot-ui", dest="bot_ui")
    shown_deploys.add_argument("--all", action="store_true", help="철회된 것까지")
    shown_deploys.set_defaults(run=deployments)

    undo = subs.add_parser("revoke-deploy", help="배포 철회 서명")
    undo.add_argument("deployment_id")
    undo.add_argument("--reason", default="관리자 철회")
    undo.set_defaults(run=revoke_deploy)

    job = subs.add_parser("job", help="작업 지시 (C5 — 서명 없음)").add_subparsers(
        dest="sub", required=True
    )
    made_job = job.add_parser("new", help="작업 만들기 (콘솔 CON-05와 같은 일)")
    made_job.add_argument("id", help="BPM 프로세스 id")
    made_job.add_argument("--bot-ui", dest="bot_ui", required=True, help="대상 Bot UI id")
    made_job.add_argument("--version", help="비우면 그 Bot UI에 배포된 버전")
    made_job.add_argument("--input", action="append", metavar="이름=값", help="입력 (여러 번)")
    made_job.add_argument("--inputs", help="입력 전체를 JSON 객체로")
    made_job.add_argument("--until", help="이때까지 시작하지 못하면 만료 (ISO 8601)")
    made_job.add_argument("--note", help="메모 (500자 이내)")
    made_job.add_argument("--idempotency-key", dest="idempotency_key", help="다시 보낼 때 (멱등)")
    made_job.set_defaults(run=job_new)

    listed_jobs = job.add_parser("list", help="작업 목록")
    listed_jobs.add_argument("--state", help="pending·dispatched·queued·accepted·…")
    listed_jobs.add_argument("--bot-ui", dest="bot_ui")
    listed_jobs.add_argument("--bpm-process", dest="bpm_process")
    listed_jobs.set_defaults(run=job_list)

    shown_job = job.add_parser("show", help="작업 하나 (실행 상태 포함)")
    shown_job.add_argument("job_id")
    shown_job.set_defaults(run=job_show)

    stopped = job.add_parser("cancel", help="작업 취소")
    stopped.add_argument("job_id")
    stopped.set_defaults(run=job_cancel)

    drop = subs.add_parser("revoke-package", help="패키지 승인 철회 서명")
    drop.add_argument("id")
    drop.add_argument("version")
    drop.add_argument("--reason", default="관리자 철회")
    drop.set_defaults(run=revoke_package)
    return made


def main(argv: list[str] | None = None, *, center: Center | None = None) -> int:
    _utf8()
    args = parser().parse_args(argv)
    found = center or Center.from_env()
    try:
        return int(args.run(args, found))
    except (keystore.KeyError_, CenterProblem) as e:
        # **왜 안 되는지 한 줄로** 말한다 — 추적을 쏟지 않는다.
        print(f"오류: {e}", file=sys.stderr)
        return 2


__all__ = [
    "CANDIDATE",
    "YES",
    "approve",
    "deploy",
    "deployments",
    "job_cancel",
    "job_list",
    "job_new",
    "job_show",
    "main",
    "parser",
    "pending",
]
