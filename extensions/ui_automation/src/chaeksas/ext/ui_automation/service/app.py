"""UI 자동화 앱 — 화면 레지스트리의 서버 부분 (C9·C11).

이 확장의 **서버 쪽**이다 (`extension.json`의 `service`). 사람이 BUI-06에서 등록한 화면이
여기 쌓이고, 실행이 보낸 보고(C8)가 통계를 갱신해 승격을 결정한다.

- 공통 뼈대는 `service_kit`이 준다 (C11): 키 검증·권한, 멱등, 오류 형식, 사용 기록, 관리 API.
  여기서는 **작업 함수와 저장소만** 쓴다.
- **셀렉터가 나가는 작업은 `registry_write` 권한이 있어야 한다** (C9). 작업이 `required_scopes`로
  선언하고 뼈대가 건다 (C11) — 작업 함수가 키를 들여다보지 않는다. 공개 카탈로그에는 셀렉터가
  나가지 않는다.
- 저장은 SQLite 한 파일 (`store.py`). 레지스트리는 메모리에서 돌고 바뀌면 통째로 쓴다.

> 상태: `plan`·`heal`(C8)은 아직 없다 — 선언하지 않으니 부르면 404다. **없는 것을 되는 척
> 하지 않는다.** 계획 생성은 다음 조각이다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs
from fastapi import FastAPI

from chaeksas.contracts.service_app import (
    MODE_AUTONOMOUS,
    MODE_DETERMINISTIC,
    ExtensionRef,
    Operation,
    OpRequest,
    ServiceAppManifest,
)
from chaeksas.ext.ui_automation.contracts.plan import SessionReport
from chaeksas.ext.ui_automation.contracts.registry import PageRegistration
from chaeksas.ext.ui_automation.service.registry import HasLinks, Registry, RegistryError
from chaeksas.ext.ui_automation.service.store import Database, RegistryStore, SqliteKeyStore
from chaeksas.service_kit import OpError, create_app

log = logging.getLogger(__name__)

APP_ID = "ui-automation"
APP_NAME = "UI 자동화"
VERSION = "0.1.0"

#: 설정은 환경변수로만 (CLAUDE.md §5). 포트 기본값은 `docs/04-setup.md` §6의 표가 원본이다.
ENV_PREFIX = "CHK_SVC_UI_AUTOMATION__"
DEFAULT_PORT = 8000
DEFAULT_CONSOLE_PORT = 8001

#: 셀렉터가 나가는 작업 (C9) — 이 권한이 없으면 403.
REGISTRY_WRITE = "registry_write"

OPERATIONS = (
    Operation(
        name="registry_list_pages",
        description="화면 목록 (셀렉터 없음)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
    ),
    Operation(
        name="registry_get_page",
        description="화면 하나 전체 (로케이터 포함)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
        required_scopes=[REGISTRY_WRITE],
    ),
    Operation(
        name="registry_register",
        description="화면·요소 등록 (더하기만 한다)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
        required_scopes=[REGISTRY_WRITE],
    ),
    Operation(
        name="registry_delete",
        description="화면·요소 삭제 (되돌릴 수 없다)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
        required_scopes=[REGISTRY_WRITE],
    ),
    Operation(
        name="report",
        description="UI 세션 보고 — 통계·승격 (C8)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
    ),
)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def data_dir() -> Path:
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "svc-uia"


def manifest(console_url: str = "") -> ServiceAppManifest:
    return ServiceAppManifest(
        schema=1,
        app_id=APP_ID,
        name=APP_NAME,
        version=VERSION,
        category="system",
        console_url=console_url or _env("CONSOLE_URL") or f"http://localhost:{DEFAULT_CONSOLE_PORT}",
        operations=list(OPERATIONS),
        extension=ExtensionRef(id=APP_ID, version=VERSION),
    )


@dataclass
class Service:
    """레지스트리 한 벌 + 저장소. 작업 함수가 이것을 쓴다."""

    store: RegistryStore
    registry: Registry = field(default_factory=Registry)

    @classmethod
    def open(cls, db: Database) -> Service:
        store = RegistryStore(db=db)
        pages, stats, revision = store.load()
        return cls(store=store, registry=Registry(pages=pages, stats=stats, revision=revision))

    def flush(self) -> None:
        self.store.save(self.registry.pages, self.registry.stats, self.registry.revision)

    # ── 작업 함수 (C11 `Handler`) ──

    def list_pages(self, request: OpRequest, mode: str) -> Mapping[str, Any]:
        found = self.registry.pages_list(
            platform=request.input.get("platform"), query=request.input.get("query")
        )
        return {"pages": [one.to_json_dict() for one in found]}

    def get_page(self, request: OpRequest, mode: str) -> Mapping[str, Any]:
        """**셀렉터가 나간다** — `registry_write` 권한이 있어야 한다 (C9)."""
        page_id = str(request.input.get("page_id") or "")
        try:
            page = self.registry.page(page_id)
        except RegistryError as e:
            raise OpError("not_found", str(e), status=404) from e
        return {
            "page": page.to_json_dict(),
            "revision": page.revision,
            "stats": [
                {"semantic_key": key[1], "locator_key": key[2], **value.to_json_dict()}
                for key, value in sorted(self.registry.stats.items())
                if key[0] == page_id
            ],
            "warnings": self.registry.warnings(page_id),
        }

    def register(self, request: OpRequest, mode: str) -> Mapping[str, Any]:
        raw = request.input.get("page")
        if not isinstance(raw, dict):
            raise OpError("input_invalid", "page가 없다", status=422)
        try:
            page = PageRegistration.model_validate(raw)
        except ValueError as e:
            raise OpError("input_invalid", f"page가 계약과 맞지 않는다: {e}", status=422) from e
        try:
            found = self.registry.register(page)
        except RegistryError as e:
            # **사다리 없는 정보는 받지 않는다** (C9) — 보낸 쪽을 고쳐야 한다.
            raise OpError("page_invalid", str(e), status=422) from e
        self.flush()
        return found.to_json_dict()

    def delete(self, request: OpRequest, mode: str) -> Mapping[str, Any]:
        page_id = str(request.input.get("page_id") or "")
        semantic_key = request.input.get("semantic_key")
        try:
            found = self.registry.delete(
                page_id,
                str(semantic_key) if semantic_key else None,
                force=bool(request.input.get("force")),
            )
        except HasLinks as e:
            # 끊길 경로를 보여 주고 사람이 한 번 더 보게 한다 (U9).
            raise OpError(
                "has_links", str(e), status=409, detail={"links": [one.to_json_dict() for one in e.links]}
            ) from e
        except RegistryError as e:
            raise OpError("not_found", str(e), status=404) from e
        self.flush()
        return found.to_json_dict()

    def report(self, request: OpRequest, mode: str) -> Mapping[str, Any]:
        """C8 보고 — 통계를 갱신하고 승격을 결정한다. **`test` 보고는 통계에 넣지 않는다.**"""
        try:
            found = SessionReport.model_validate(request.input)
        except ValueError as e:
            raise OpError("input_invalid", f"보고가 계약과 맞지 않는다: {e}", status=422) from e
        promoted = self.registry.apply(found)
        self.flush()
        return {"accepted": True, "promoted": promoted}


def create(
    *,
    db_path: Path | None = None,
    admin_token: str | None = None,
    console_url: str = "",
) -> FastAPI:
    """앱 하나. `admin_token`이 없으면 관리 API는 503이다 (C11)."""
    database = Database(path=db_path or (data_dir() / "ui-automation.sqlite3"))
    service = Service.open(database)
    keys = SqliteKeyStore(db=database)

    app = create_app(
        manifest(console_url),
        {
            "registry_list_pages": service.list_pages,
            "registry_get_page": service.get_page,
            "registry_register": service.register,
            "registry_delete": service.delete,
            "report": service.report,
        },
        keys=keys,
        admin_token=admin_token or _env("ADMIN_TOKEN"),
    )
    app.state.service = service

    @app.get("/v1/catalog")
    def catalog() -> Any:
        """C13 §5 공통 카탈로그. **인증 없음, 셀렉터 없음** (C9)."""
        return service.registry.catalog()

    return app


def main() -> int:
    """`chk-svc-uia` 진입점."""
    import uvicorn  # noqa: PLC0415 — 띄울 때만 든다

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    port = int(_env("PORT") or DEFAULT_PORT)
    host = _env("HOST") or "0.0.0.0"  # noqa: S104 — 서버다 (컨테이너·역방향 프록시 뒤)
    uvicorn.run(create(), host=host, port=port, log_level="info")
    return 0


__all__ = [
    "APP_ID",
    "DEFAULT_CONSOLE_PORT",
    "DEFAULT_PORT",
    "OPERATIONS",
    "REGISTRY_WRITE",
    "Service",
    "create",
    "data_dir",
    "main",
    "manifest",
]
