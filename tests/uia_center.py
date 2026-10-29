"""UI 자동화 앱을 **일꾼**으로 붙인 진짜 소켓 Center — 시험이 쓰는 자리 하나 (C15, ADR-0102).

**이것은 제품 코드가 아니다.** UI 자동화 앱은 더 이상 HTTP로 불리지 않는다 — 부르는 쪽(Worker·도구·
편집기)은 Center에 외부 작업을 올리고, 앱은 일꾼으로 그것을 가져가 끝낸다. 그래서 「앱을 부른다」를
보려는 시험은 셋을 함께 띄운다: Center(진짜 소켓 — 롱폴링), UI 자동화 앱(일꾼 스레드), 부르는 쪽의
**호출 토큰**.

| 자리 | 무엇 |
| --- | --- |
| `running()` | Center + UI 자동화 앱(일꾼으로 들인 것) |
| `UiaCenter.studio_token()` | Studio 키 → 호출 토큰. `test_…` 실행만 올린다, 등록 권한 없음 |
| `UiaCenter.pc_token()` | 등록된 Bot UI 키 → 호출 토큰. 「셀렉터 등록」(`reg_…`)·Bot `BOT` 배포(`run_…`) |
| `UiaCenter.catalog()` | Center에 올라간 공개 카탈로그(C7 기여 자원 `ui_page`) — 일꾼이 지금 올리게 하고 읽는다 |
| `execute()` | 앱의 작업 수행기(`app.state.ops`)를 Center 없이 바로 부른다 — 작업 함수만 볼 때 |
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from center_admin import approve as approve_package
from center_admin import deploy
from consumers import ADMIN, enroll, serve, start

from chaeksas.center.app import create_app as create_center
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.external_task import LockedTask
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.ext.ui_automation.service.app import APP_ID, create
from chaeksas.service_kit import Outcome, ServiceLlm

#: 등록된 PC에 배포해 두는 Bot — 매니페스트가 토픽 `ui-automation`을 요구한다 (C15 「그 Bot이 요구하나」).
BOT = "uia.trial"
VERSION = "1.0.0"
AT = "2026-10-29T09:00:00+09:00"
_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="Proc_x" isExecutable="true"><bpmn:startEvent id="S" /></bpmn:process>
</bpmn:definitions>
"""


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _package_zip() -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": VERSION,
        "name": BOT,
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_x",
        "requires": {"service_apps": [{"app_id": APP_ID, "operations": ["plan", "heal", "report"]}]},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", _BPMN)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


@dataclass
class UiaCenter:
    url: str
    store: Store
    #: UI 자동화 앱 (FastAPI) — `app.state.service`가 레지스트리, `app.state.ops`가 작업 수행기다.
    app: Any
    #: 앱을 돌리는 일꾼 (`service_kit.Consumer`) — 카탈로그를 지금 올리려면 `consumer.publish()`.
    consumer: Any = None
    _pcs: int = field(default=0, repr=False)

    def http(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=60)

    def _key(self, http: httpx.Client, *, name: str, kind: str) -> str:
        made = http.post("/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN)
        assert made.status_code == 201, made.text
        return str(made.json()["key"])

    def _call_token(self, http: httpx.Client, key: str) -> str:
        made = http.post("/api/v1/call-tokens", headers=_bearer(key))
        assert made.status_code in (200, 201), made.text
        return str(made.json()["token"])

    def studio_token(self) -> str:
        """Studio 키로 청한 호출 토큰 — `test_…` 실행만, 등록 권한(`registry_write`)은 없다."""
        with self.http() as http:
            return self._call_token(http, self._key(http, name="설계자", kind="studio"))

    def pc_token(self, *, selector_registration: bool = True, deployed: bool = True) -> str:
        """등록된 Bot UI 하나의 호출 토큰. 「셀렉터 등록」을 켜면 `reg_…`를, Bot을 배포하면 `run_…`을 올린다."""
        self._pcs += 1
        with self.http() as http:
            key = self._key(http, name=f"현장 {self._pcs}", kind="bot_ui")
            made = http.post(
                "/api/v1/bot-ui/register",
                json={
                    "schema": 1,
                    "machine_id": format(self._pcs, "x") * 64,
                    "name": f"현장 {self._pcs}",
                    "os": "windows-11-23H2",
                    "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
                },
                headers=_bearer(key),
            )
            assert made.status_code < 400, made.text
            bot_ui_id = str(made.json()["bot_ui_id"])
            if selector_registration:
                on = http.put(
                    f"/api/v1/bot-uis/{bot_ui_id}/utility", json={"selector_registration": True}, headers=ADMIN
                )
                assert on.status_code == 200, on.text
            if deployed:
                if self.store.row("SELECT 1 FROM packages WHERE id = ?", (BOT,)) is None:
                    up = http.post(
                        "/api/v1/packages",
                        files={"file": ("p.zip", _package_zip(), "application/zip")},
                        headers=ADMIN,
                    )
                    assert up.status_code in (200, 201), up.text
                    approve_package(http, BOT, VERSION)
                deploy(http, target={"type": "bot_ui", "id": bot_ui_id}, bpm_process_id=BOT, version=VERSION)
            return self._call_token(http, key)

    def catalog(self, token: str) -> dict[str, Any]:
        """일꾼이 카탈로그를 **지금** 올리게 하고(평소엔 주기마다) Center의 기여 자원 목록을 읽는다."""
        self.consumer.publish()
        with self.http() as http:
            found = http.get(
                "/api/v1/resources", params={"type": "contributed", "resource_type": "ui_page"}, headers=_bearer(token)
            )
            assert found.status_code == 200, found.text
            return dict(found.json())


@contextmanager
def running(tmp_path: Path, *, llm: ServiceLlm | None = None, db_path: Path | None = None) -> Iterator[UiaCenter]:
    """Center를 띄우고 UI 자동화 앱을 일꾼으로 들여 돌린다. 끝나면 둘 다 멈춘다."""
    store = Store(tmp_path / "center.sqlite3")
    center = create_center(CenterSettings(admin_token="t-admin", package_dir=tmp_path / "pkg"), store=store)
    url, server, thread = serve(center)
    app = create(db_path=db_path or tmp_path / "uia.sqlite3", admin_token="t-admin", llm=llm or ServiceLlm())
    ops = app.state.ops
    with httpx.Client(base_url=url, timeout=30) as http:
        tokens = enroll(http, topics=[APP_ID], manifests=[ops.manifest.to_json_dict()], folder=tmp_path / "uia-c")
    consumer, stop = start([ops], center_url=url, tokens=tokens)
    try:
        yield UiaCenter(url=url, store=store, app=app, consumer=consumer)
    finally:
        stop.set()
        server.should_exit = True
        thread.join(timeout=10)
        store.close()


def locked(
    operation: str,
    body: dict[str, Any],
    *,
    mode: str = "deterministic",
    run_id: str = "run_20261029_090000_aaaaaa",
    node_id: str = "Task_Ui",
    call_seq: int = 1,
    attempt: int = 1,
    origin: str = "run",
    caller: dict[str, Any] | None = None,
    business_key: str | None = None,
) -> LockedTask:
    """일꾼이 Center에서 받는 일감 한 장 (C15 `LockedTask`)."""
    now = datetime.now(UTC)
    return LockedTask.model_validate(
        {
            "task_id": f"et_{operation}_{run_id}_{call_seq}_{attempt}",
            "topic": APP_ID,
            "operation": operation,
            "mode": mode,
            "origin": origin,
            "idempotency": {
                "run_id": run_id,
                "node_id": node_id,
                "node_instance": 1,
                "attempt": attempt,
                "call_seq": call_seq,
            },
            "caller": caller or {"type": "worker", "host": "pc_01"},
            "business_key": business_key or f"{run_id}:{node_id}:1:{attempt}",
            "input": body,
            "lock_until": (now + timedelta(minutes=5)).isoformat(),
            "deadline": (now + timedelta(minutes=10)).isoformat(),
        }
    )


def execute(app: Any, operation: str, body: dict[str, Any], **over: Any) -> Outcome:
    """앱의 작업 수행기에 일감 한 장을 준다 — Center·일꾼 없이 작업 함수만 볼 때."""
    found: Outcome = app.state.ops.execute(locked(operation, body, **over))
    return found


__all__ = ["BOT", "VERSION", "UiaCenter", "execute", "locked", "running"]
