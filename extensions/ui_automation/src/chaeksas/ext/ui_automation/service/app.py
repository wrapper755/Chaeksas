"""UI 자동화 앱 — 화면 레지스트리의 서버 부분 (C9·C11).

이 확장의 **서버 쪽**이다 (`extension.json`의 `service`). 사람이 BUI-06에서 등록한 화면이
여기 쌓이고, 실행이 보낸 보고(C8)가 통계를 갱신해 승격을 결정한다.

- 공통 뼈대는 `service_kit`이 준다 (C11): 키 검증·권한, 멱등, 오류 형식, 사용 기록, 관리 API.
  여기서는 **작업 함수와 저장소만** 쓴다.
- **셀렉터가 나가는 작업은 `registry_write` 권한이 있어야 한다** (C9). 작업이 `required_scopes`로
  선언하고 뼈대가 건다 (C11) — 작업 함수가 키를 들여다보지 않는다. 공개 카탈로그에는 셀렉터가
  나가지 않는다.
- 저장은 SQLite 한 파일 (`store.py`). 레지스트리는 메모리에서 돌고 바뀌면 통째로 쓴다.

- 치유(`heal`, C8)는 모델에게 묻고 답을 **거른다** (`healing.py`). 모델은 C11 §모델 연결로 받는다.

- 목표로 계획(`plan`의 `goal`, 자율 수행만)은 모델이 스텝을 세우고 `planning.py`가 거른다 (ADR-0035).
  모델은 **값의 이름만** 본다.
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
    ResourceCatalog,
    ServiceAppManifest,
)
from chaeksas.ext.ui_automation.contracts.plan import (
    ElementInfo,
    ExecutionPlan,
    HealRequest,
    PlanStep,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registry import PageRegistration
from chaeksas.ext.ui_automation.service import healing, planning
from chaeksas.ext.ui_automation.service.registry import HasLinks, Registry, RegistryError
from chaeksas.ext.ui_automation.service.store import Database, RegistryStore, SqliteKeyStore
from chaeksas.service_kit import OpError, OpResult, ServiceLlm, create_app, usage_of

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

#: 공개 카탈로그 경로 (C13 §5). **manifest가 알리는 것과 실제 경로가 한 상수에서 온다** —
#: 두 곳에 적으면 어긋나고, 어긋나면 Center가 404를 받는다.
CATALOG_PATH = "/v1/catalog"

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
        name="plan",
        description="실행 계획 — 결정 수행은 등록된 사다리, 자율 수행은 목표로 모델이 스텝을 세운다 (C8)",
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
    ),
    Operation(
        name="heal",
        description="사다리가 모두 실패한 요소의 대체 로케이터를 모델에게 묻는다 (C8)",
        # 치유는 폴백이 아니라 확장의 정해진 기능이다 — 결정 수행에서도 된다 (C8 수행 모드 표).
        # 운영에서 막으려면 운영 키의 허용 작업에서 heal을 뺀다.
        modes=[MODE_DETERMINISTIC, MODE_AUTONOMOUS],
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
        # **우리 카탈로그를 알린다** (C11 `resources`, C7) — 내장 확장의 정의는 Center에
        # 없으니 서버 부분이 자기 자원을 알려야 CON-07 「UI 화면」 탭에 뜬다. 아래
        # `/v1/catalog`가 그 응답이다 (C13 §5, 셀렉터 없음).
        resources=[ResourceCatalog(type="ui_page", catalog_url=CATALOG_PATH, label="UI 화면")],
    )


@dataclass
class Service:
    """레지스트리 한 벌 + 저장소. 작업 함수가 이것을 쓴다."""

    store: RegistryStore
    registry: Registry = field(default_factory=Registry)
    #: 치유가 묻는 모델 (C11 §모델 연결). 없으면 치유는 503 `llm_unavailable`이다.
    llm: ServiceLlm = field(default_factory=ServiceLlm)

    @classmethod
    def open(cls, db: Database, llm: ServiceLlm | None = None) -> Service:
        store = RegistryStore(db=db)
        pages, stats, revision = store.load()
        return cls(
            store=store,
            registry=Registry(pages=pages, stats=stats, revision=revision),
            llm=llm if llm is not None else ServiceLlm(),
        )

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

    def plan(self, request: OpRequest, mode: str) -> OpResult:
        """C8 `plan` — 결정 수행은 **등록된 사다리를 모아 주고**, 자율 수행은 목표로 스텝을 세운다.

        **스텝을 비워 보내면 그 화면의 사다리 전부**를 준다 — Worker는 세션을 열 때 계획을
        받고 스텝은 그 뒤에 하나씩 오기 때문이다 (C10).

        목표(`goal`)는 **자율 수행에서만** 받는다 — 결정 수행은 LLM을 몰래 부르지 않는다. 모델이
        세운 스텝은 `planning.py`가 거르고, 어긋나면 422 `goal_plan_invalid`다 (ADR-0035).
        """
        goal = str(request.input.get("goal") or "").strip()
        if goal and mode == MODE_DETERMINISTIC:
            raise OpError("mode_unsupported", "결정 수행은 목표로 계획하지 않는다 — 스텝을 주세요", status=422)
        page_id = str(request.input.get("page_id") or "")
        try:
            page = self.registry.page(page_id)
        except RegistryError as e:
            raise OpError("not_found", str(e), status=404) from e

        usage = None
        if goal:
            values = [str(one) for one in (request.input.get("values") or [])]
            results = [str(one) for one in (request.input.get("results") or [])]
            reply = self.llm.ask(planning.messages_for(goal, page, values, results))
            usage = usage_of([reply])
            try:
                steps = planning.steps_from(reply.text, page, values, results)
            except planning.GoalPlanInvalid as e:
                raise OpError(
                    "goal_plan_invalid",
                    f"모델이 세운 계획을 쓸 수 없다: {e}",
                    status=422,
                    detail={"reasons": e.reasons},
                ) from e
        else:
            try:
                steps = [PlanStep.model_validate(one) for one in (request.input.get("steps") or [])]
            except ValueError as e:
                raise OpError("input_invalid", f"스텝이 계약과 맞지 않는다: {e}", status=422) from e
        made = ExecutionPlan(
            schema=1,
            plan_id=f"plan_{page.page_id}_{page.revision}",
            page_id=page.page_id,
            platform=page.platform,
            start_url=request.input.get("start_url") or page.url_pattern,
            # 데스크톱이면 Worker가 이것으로 창을 찾아 붙거나 띄운다 (C8, ADR-0033).
            app=page.app,
            window=page.window,
            revision=page.revision,
            steps=steps,
            # **스텝에 나오는 모든 요소의 사다리 전부** (C8) — 폴백은 Worker가 로컬에서 탄다.
            # 스텝을 비워 보냈으면 그 화면의 사다리 전부를 준다 (세션을 열 때 받는 계획이다).
            locators={key: list(ladder) for key, ladder in page.locators.items()}
            if not steps
            else {step.semantic_key: list(page.locators.get(step.semantic_key, [])) for step in steps},
            elements={
                key: ElementInfo(description=hint.description or hint.name, role=hint.role)
                for key, hint in page.elements.items()
            },
        )
        missing = made.missing_keys()
        if missing:
            # 등록되지 않은 요소를 가리켰다 — C10과 같은 코드로 올린다.
            raise OpError(
                "unknown_semantic_key",
                f"사다리가 없는 요소가 있다: {', '.join(missing)}",
                status=422,
                detail={"items": missing},
            )
        return OpResult(made.to_json_dict(), usage=usage)

    def heal(self, request: OpRequest, mode: str) -> OpResult:
        """C8 `heal` — 모델에게 **한 번** 묻고 답을 **걸러서** 준다 (`service/healing.py`).

        쓸 수 없는 제안은 `locator: null`과 이유다 (200 — 정상적인 분기). 모델이 없거나 닿지
        않으면 C11 오류(503)이고 Worker는 전환한다.
        """
        try:
            asked = HealRequest.model_validate(request.input)
        except ValueError as e:
            raise OpError("input_invalid", f"치유 요청이 계약과 맞지 않는다: {e}", status=422) from e
        try:
            healing.check_size(asked)
        except healing.SnapshotTooLarge as e:
            raise OpError("snapshot_too_large", str(e), status=413) from e
        try:
            page = self.registry.page(asked.page_id)
        except RegistryError as e:
            raise OpError("page_not_found", str(e), status=404) from e
        if asked.semantic_key not in page.locators and asked.semantic_key not in page.elements:
            raise OpError(
                "unknown_semantic_key",
                f"등록되지 않은 요소다: {asked.semantic_key}",
                status=422,
                detail={"items": [asked.semantic_key]},
            )
        reply = self.llm.ask(healing.messages_for(asked, page))
        answer = healing.answer_from(reply.text, asked, page)
        return OpResult(answer.to_json_dict(), usage=usage_of([reply]))

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
    llm: ServiceLlm | None = None,
) -> FastAPI:
    """앱 하나. `admin_token`이 없으면 관리 API는 503이다 (C11).

    모델(`CHK_SVC_UI_AUTOMATION__LLM__*`, C11 §모델 연결)은 치유(`heal`)가 쓴다. 없으면 치유만
    503 `llm_unavailable`이고 나머지 작업은 돈다.
    """
    database = Database(path=db_path or (data_dir() / "ui-automation.sqlite3"))
    model = llm if llm is not None else ServiceLlm.from_env(ENV_PREFIX)
    service = Service.open(database, model)
    keys = SqliteKeyStore(db=database)

    app = create_app(
        manifest(console_url),
        {
            "registry_list_pages": service.list_pages,
            "registry_get_page": service.get_page,
            "registry_register": service.register,
            "registry_delete": service.delete,
            "plan": service.plan,
            "heal": service.heal,
            "report": service.report,
        },
        keys=keys,
        admin_token=admin_token or _env("ADMIN_TOKEN"),
        llm=model,
    )
    app.state.service = service

    @app.get(CATALOG_PATH)
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
