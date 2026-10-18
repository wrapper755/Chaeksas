"""STU-13의 「이 스텝까지 시험」·「계획 세워 보기」 — **Studio 시험 실행과 같은 길**로 Worker를 부른다.

Bot UI로 넘기지 않는다 (ADR-0074) — Studio 시험 실행이 이미 Bot UI가 띄운 Worker에 직접 붙는다.
이 모듈은 Qt를 모른다. 편집기(`editor.py`)가 단추를 잇고 결과 줄을 상자에 쓴다.

지키는 것 넷.

- **보고하지 않는다** (C10 `report: false`) — 설계자가 돌려 본 것이 승격 통계를 건드리지 않게.
- **끝나면 세션을 닫는다** — Worker의 UI 세션은 하나라(ADR-0014) 쥐고 있으면 Bot이 기다린다.
- **읽은 값은 결과 줄에만** 간다 (원칙 6). 어디에도 남기지 않는다.
- **계획 세워 보기는 스텝을 돌리지 않는다** — 세운 스텝을 받고 바로 닫는다. 표에 넣는 것은 사람이다.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts import SERVICE_KEY_REF_SETTING
from chaeksas.ext.ui_automation.client.task import (
    TEMPLATE,
    WORKER_PORT_SETTING,
    WORKER_TOKEN_DIR_SETTING,
    WorkerClient,
    _desktop_app,
    _from_plan,
    _rendered,
    _step,
)
from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_STUDIO,
    MUTATING_ACTIONS,
    Caller,
    SessionRequest,
)

PLAN_SOURCE = {"server": "서버", "cache": "로컬 캐시 (오프라인)"}


class NotReady(RuntimeError):
    """누르기 전에 갖춰야 할 것이 없다 — 화면이 그 말을 그대로 보인다."""


def template_names(texts: Sequence[str]) -> list[str]:
    """값·목표 안의 `{이름}`들 (C14 — `{{`·`}}`는 중괄호 글자다). 처음 나온 차례대로."""
    names: list[str] = []
    for text in texts:
        for match in TEMPLATE.finditer(text):
            name = match.group(1)
            if name is None:
                continue
            # `{건.품목}`은 `건`을 묻는다 — 사람은 반복 항목 하나를 통째로 모른다. 이름 그대로 묻는다.
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return names


def _nested(answers: Mapping[str, str]) -> dict[str, Any]:
    """`{"건.품목": "볼트"}` → `{"건": {"품목": "볼트"}}` — 수행기의 `render`가 점으로 따라간다."""
    out: dict[str, Any] = {}
    for name, value in answers.items():
        head, *rest = name.split(".")
        if not rest:
            out[name] = value
            continue
        place = out.setdefault(head, {})
        if not isinstance(place, dict):
            continue
        for part in rest[:-1]:
            place = place.setdefault(part, {})
        place[rest[-1]] = value
    return out


@dataclass
class EditorTrial:
    """편집기 하나의 Worker 창구. `ctx`는 Studio가 준 편집기 문맥이다 (ADR-0074)."""

    ctx: Any
    #: 시험이 끼운다 — 없으면 문맥의 예약 키로 짓는다.
    worker: WorkerClient | None = None
    #: 결과 한 줄을 받는 쪽 (편집기의 「시험 결과」 상자).
    say: Callable[[str], None] = field(default=lambda _line: None)

    # ── 갖춰야 할 것 ──

    def _worker(self) -> WorkerClient:
        if self.worker is not None:
            return self.worker
        port = self.ctx.setting(WORKER_PORT_SETTING)
        if not port:
            raise NotReady("Worker 자리를 모릅니다 — 이 PC의 Bot UI가 Worker를 띄워야 합니다.")
        folder = self.ctx.setting(WORKER_TOKEN_DIR_SETTING)
        return WorkerClient(token_dir=Path(str(folder)) if folder else Path.cwd(), port=int(port))

    def key(self, key_ref: str) -> str:
        """태스크의 키 참조, 비면 BPM 프로세스 설정(`service.key_ref`) — **엔진과 같은 순서**다."""
        ref = key_ref.strip() or str(self.ctx.setting(SERVICE_KEY_REF_SETTING) or "")
        if not ref:
            raise NotReady(
                "UI 자동화 앱 키 참조가 없습니다 — 태스크의 「키 참조」나 BPM 프로세스 정보(STU-06)에 적으세요."
            )
        found = self.ctx.secret(ref)
        if not found:
            raise NotReady(f"키 참조 {ref}의 값이 없습니다 — 설정 › 서비스 앱 키에 개발용 키를 넣으세요.")
        return str(found)

    def _request(self, spec: Mapping[str, Any], *, mode: str, key: str, **more: Any) -> SessionRequest:
        return SessionRequest(
            schema=1,
            caller=Caller(type=CALLER_STUDIO),
            mode=mode,
            business_key=f"stu_{secrets.token_hex(4)}",
            page_id=str(spec.get("page_id") or ""),
            start_url=spec.get("start_url") or None,
            app=_desktop_app(dict(spec)),
            headed=True,
            heal=bool(spec.get("heal", True)),
            report=False,
            service_key=key,
            **more,
        )

    # ── 이 스텝까지 시험 ──

    def run(self, spec: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], answers: Mapping[str, str]) -> str:
        """스텝을 하나씩 보낸다. 결과 한 마디(「성공」·「실패」·「사람에게 전환」)를 돌려준다.

        값은 **화면에 손대기 전에** 모두 채운다 — 모르는 이름이 있으면 아무것도 열지 않는다.
        """
        worker = self._worker()
        key = self.key(str(spec.get("key_ref") or ""))
        values = _nested(answers)
        filled = [_rendered(dict(one), values) for one in steps]
        info = worker.open(self._request(spec, mode="deterministic", key=key))
        source = PLAN_SOURCE.get(info.plan_source, info.plan_source)
        self.say(f"[계획 출처: {source}] {spec.get('page_id')} · {len(filled)}스텝 · 보고하지 않습니다")
        done = 0
        verdict = "실패"
        try:
            for index, raw in enumerate(filled, start=1):
                result = worker.step(info.session_id, info.session_secret, _step(raw))
                mark = "O" if result.ok else ("△" if result.escalated else "X")
                line = f"{index}. {raw.get('key')} · {raw.get('action')} → {mark}"
                if result.fallback_depth:
                    line += f" (사다리 {result.fallback_depth + 1}번째 칸)"
                if result.healed:
                    line += " · 자가 치유"
                self.say(line)
                if result.text and str(raw.get("action")) not in MUTATING_ACTIONS:
                    # **읽은 값은 여기에만** 보인다 (원칙 6 — 보고하지 않는다).
                    for one in str(result.text).splitlines():
                        self.say(f"    {one}")
                if result.escalated:
                    self.say(f"    사람에게 전환: {result.error or '사다리가 모두 실패했습니다'}")
                    verdict = "사람에게 전환"
                    break
                if not result.ok:
                    self.say(f"    실패: {result.error_code or ''} {result.error or ''}".rstrip())
                    break
                done += 1
            else:
                verdict = "성공"
        finally:
            _close(worker, info.session_id, info.session_secret)
        self.say(f"결과: {verdict} — {done}/{len(filled)} 스텝 · 세션을 닫았습니다")
        return verdict

    # ── 계획 세워 보기 ──

    def plan(self, spec: Mapping[str, Any], goal: str, results: Sequence[str]) -> list[dict[str, Any]]:
        """자율 수행으로 열어 앱이 세운 스텝(C10 `planned_steps`)을 받고 **돌리지 않고** 닫는다.

        모델에게는 값의 **이름만** 간다 (ADR-0035) — 그래서 값을 묻지 않는다.
        """
        worker = self._worker()
        key = self.key(str(spec.get("key_ref") or ""))
        info = worker.open(
            self._request(
                spec,
                mode="autonomous",
                key=key,
                goal=goal,
                values=template_names([goal]),
                results=[str(one) for one in results],
            )
        )
        try:
            planned = [_from_plan(one) for one in info.planned_steps]
        finally:
            _close(worker, info.session_id, info.session_secret)
        self.say(f"[계획] {spec.get('page_id')} · {len(planned)}스텝 — 돌리지 않았습니다")
        for index, one in enumerate(planned, start=1):
            parts = [f"{index}. {one.get('key')} · {one.get('action')}"]
            if one.get("value") is not None:
                parts.append(f"값 {one['value']}")
            if one.get("result"):
                parts.append(f"→ {one['result']}")
            self.say(" ".join(parts))
        if planned:
            self.say("「스텝으로 굳히기」를 누르면 이 스텝이 표에 들어가고 목표로 계획이 꺼집니다.")
        return planned


def _close(worker: WorkerClient, session_id: str, secret: str) -> None:
    try:
        worker.close(session_id, secret)
    except Exception:  # noqa: BLE001 — 이미 닫혔을 수 있다 (유휴 시간이 닫아 준다)
        return


__all__ = ["PLAN_SOURCE", "EditorTrial", "NotReady", "template_names"]
