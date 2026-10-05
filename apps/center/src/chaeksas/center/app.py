"""Center API 한 벌 (`create_app`).

경로는 C4·C5·C7이 정한 그대로다. 권한은 C5 「권한표」를 `auth`가 한 곳에서 본다.

    app = create_app(Settings.from_env())
    uvicorn.run(app, ...)          # 또는 `chk-center`

**콘솔은 여기 없다** (ADR-0017 — `web/apps/center-console`). Center는 API만 가진다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from chaeksas.center import keys
from chaeksas.center.api import bot_ui, deployments, jobs, packages, runs, signing
from chaeksas.center.auth import Caller, caller, require_admin, require_read
from chaeksas.center.errors import ApiError, handle
from chaeksas.center.responses import Utf8JSONResponse
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.center_api import LIST_LIMIT_DEFAULT
from chaeksas.contracts.center_keys import CenterKeyCreated, CenterKeyCreateRequest
from chaeksas.contracts.center_keys import validate_create as validate_key_create

API = "/api/v1"


def create_app(settings: Settings, *, store: Store | None = None) -> FastAPI:
    """Center 앱 하나. `store`를 주면 그것을 쓴다 (시험은 메모리 DB를 준다)."""
    # 모든 JSON 응답에 charset=utf-8 (PowerShell 5.1이 한글을 깨뜨리지 않게, 이슈 #3)
    app = FastAPI(title="Chaeksas Center", version="0.1.0", default_response_class=Utf8JSONResponse)
    app.state.settings = settings
    app.state.store = store or Store(settings.db_path)

    def authenticate(request: Request) -> Caller:
        return caller(
            request,
            app.state.store,
            admin_token=settings.admin_token,
            read_token=settings.read_token,
        )

    app.state.authenticate = authenticate
    app.add_exception_handler(ApiError, handle)
    app.include_router(bot_ui.router)
    app.include_router(runs.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """인증 없음 — 비밀이 없다. 컨테이너 상태 확인이 쓴다."""
        return {"status": "ok", "server_time": now_iso()}

    # ─────────────────── Center API 키 (C7, CON-11) ───────────────────

    @app.post(f"{API}/center-keys", status_code=201)
    async def create_center_key(request: Request) -> Any:
        require_admin(authenticate(request))
        body = await _json(request)
        try:
            wanted = CenterKeyCreateRequest.model_validate(body)
        except ValueError as e:
            raise ApiError(422, "input_invalid", "요청이 계약과 맞지 않는다") from e
        problems = validate_key_create(wanted)
        if problems:
            raise ApiError(422, "input_invalid", str(problems[0]), {"violations": [str(v) for v in problems]})

        record, raw = keys.issue(
            app.state.store, name=wanted.name, key_type=wanted.type, expires_at=wanted.expires_at
        )
        created = CenterKeyCreated(**record.info(now=now_iso()).model_dump(), key=raw)
        # **원문은 이 응답에만 실린다** (C7·CON-11 — 다시 볼 수 없다).
        return created

    @app.get(f"{API}/center-keys")
    def list_center_keys(request: Request, type: str | None = None, state: str | None = None) -> Any:
        require_read(authenticate(request))
        now = now_iso()
        return [k.info(now=now) for k in keys.listing(app.state.store, key_type=type, state=state)]

    @app.delete(f"{API}/center-keys/{{key_id}}")
    def revoke_center_key(request: Request, key_id: str) -> Any:
        """폐기. **지우지 않는다** — 폐기 시각을 남겨 「누가 언제 썼나」를 볼 수 있게 한다."""
        require_admin(authenticate(request))
        record = keys.get(app.state.store, key_id)
        if record is None:
            raise ApiError(404, "not_found", f"키 {key_id}가 없다")
        keys.revoke(app.state.store, key_id)
        found = keys.get(app.state.store, key_id)
        assert found is not None
        return found.info(now=now_iso())

    @app.post(f"{API}/center-keys/{{key_id}}/unbind")
    def unbind_center_key(request: Request, key_id: str) -> Any:
        """PC 묶음 풀기 (CON-11). PC를 다시 설치해 `machine_id`가 바뀐 경우."""
        require_admin(authenticate(request))
        record = keys.get(app.state.store, key_id)
        if record is None:
            raise ApiError(404, "not_found", f"키 {key_id}가 없다")
        if not keys.unbind(app.state.store, key_id):
            raise ApiError(409, "not_bound", "묶여 있지 않다")
        return keys.get(app.state.store, key_id).info(now=now_iso())  # type: ignore[union-attr]

    # ─────────────────── Bot UI 현황 (C5·CON-03) ───────────────────

    @app.get(f"{API}/bot-uis")
    def list_bot_uis(request: Request) -> Any:
        require_read(authenticate(request))
        return bot_ui.bot_ui_listing(app.state.store)

    @app.post(f"{API}/bot-uis/{{bot_ui_id}}/disable")
    def disable_bot_ui(request: Request, bot_ui_id: str) -> Any:
        require_admin(authenticate(request))
        if not bot_ui.set_disabled(app.state.store, bot_ui_id, disabled=True):
            raise ApiError(404, "not_found", f"Bot UI {bot_ui_id}가 없다")
        return {"bot_ui_id": bot_ui_id, "disabled": True}

    @app.post(f"{API}/bot-uis/{{bot_ui_id}}/enable")
    def enable_bot_ui(request: Request, bot_ui_id: str) -> Any:
        require_admin(authenticate(request))
        if not bot_ui.set_disabled(app.state.store, bot_ui_id, disabled=False):
            raise ApiError(404, "not_found", f"Bot UI {bot_ui_id}가 없다")
        return {"bot_ui_id": bot_ui_id, "disabled": False}

    # ─────────────────── 패키지 (C5) ───────────────────

    @app.post(f"{API}/packages")
    async def upload_package(request: Request) -> Any:
        found = require_admin(authenticate(request))
        form = await request.form()
        uploaded = form.get("file")
        if uploaded is None or isinstance(uploaded, str):
            raise ApiError(422, "input_invalid", "multipart 칸 `file`에 zip을 보내세요")
        raw = await uploaded.read()
        info, created = packages.upload(
            app.state.store, package_dir=settings.package_dir, raw=raw, actor=found.actor
        )
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.get(f"{API}/packages")
    def list_packages(
        request: Request, kind: str | None = None, status: str | None = None, id: str | None = None
    ) -> Any:
        require_read(authenticate(request))
        return packages.listing(app.state.store, kind=kind, status=status, package_id=id)

    @app.get(f"{API}/packages/{{package_id}}/{{version}}/info")
    def package_info(request: Request, package_id: str, version: str) -> Any:
        require_read(authenticate(request))
        return packages.info_of(app.state.store, package_id, version)

    @app.get(f"{API}/packages/{{package_id}}/{{version}}")
    def download_package(request: Request, package_id: str, version: str) -> Any:
        require_read(authenticate(request))
        path, content_hash = packages.file_path(
            app.state.store, package_dir=settings.package_dir, package_id=package_id, version=version
        )
        # 승인된 패키지는 **`SIGNATURE`를 넣어** 준다 (C2). `content_hash`는 그 파일을 빼고
        # 세므로 해시는 그대로다 — 받는 쪽이 다시 세어도 같다.
        found = signing.signature_of(app.state.store, package_id, version)
        if found is None:
            return FileResponse(
                path,
                media_type="application/zip",
                filename=path.name,
                headers={"X-Content-Hash": content_hash},
            )
        return Response(
            content=packages.with_signature(path, found),
            media_type="application/zip",
            headers={
                "X-Content-Hash": content_hash,
                "content-disposition": f'attachment; filename="{path.name}"',
            },
        )

    # ─────────────────── 서명 (C2·C5) ───────────────────

    @app.put(f"{API}/packages/{{package_id}}/{{version}}/signature")
    async def approve_package(request: Request, package_id: str, version: str) -> Any:
        """승인 봉투. **토큰만으로는 아무것도 바뀌지 않는다** — 서명이 관문이다 (C2)."""
        require_admin(authenticate(request))
        return signing.approve_package(app.state.store, package_id, version, await _json(request))

    @app.post(f"{API}/packages/{{package_id}}/{{version}}/revoke")
    async def revoke_package(request: Request, package_id: str, version: str) -> Any:
        require_admin(authenticate(request))
        return signing.revoke_package(app.state.store, package_id, version, await _json(request))

    @app.post(f"{API}/deployments")
    async def create_deployment(request: Request) -> Any:
        """배포 봉투 (C5). Center는 배포를 **짓지 않는다** — 받아 두었다가 그대로 내려 준다."""
        require_admin(authenticate(request))
        return deployments.create(app.state.store, await _json(request))

    @app.delete(f"{API}/deployments")
    async def revoke_deployment(request: Request) -> Any:
        require_admin(authenticate(request))
        return deployments.revoke(app.state.store, await _json(request))

    @app.get(f"{API}/deployments")
    def list_deployments(request: Request, bot_ui: str | None = None, active: bool = False) -> Any:
        require_read(authenticate(request))
        return deployments.listing(app.state.store, target_id=bot_ui, active_only=active)

    # ─────────────────── 작업 (C5·CON-05) ───────────────────

    @app.post(f"{API}/jobs")
    async def create_job(request: Request) -> Any:
        """작업 지시. **서명이 없다** — 배포와 달리 「언제 돌려라」일 뿐이다 (C5 권한표)."""
        info, created = jobs.create(app.state.store, authenticate(request), await _json(request))
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.get(f"{API}/jobs")
    def list_jobs(
        request: Request,
        state: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        bpm_process_id: str | None = None,
        limit: int = LIST_LIMIT_DEFAULT,
        offset: int = 0,
    ) -> Any:
        return jobs.listing(
            app.state.store,
            authenticate(request),
            state=state,
            target_type=target_type,
            target_id=target_id,
            bpm_process_id=bpm_process_id,
            limit=limit,
            offset=offset,
        )

    @app.get(f"{API}/jobs/{{job_id}}")
    def get_job(request: Request, job_id: str) -> Any:
        return jobs.get(app.state.store, authenticate(request), job_id)

    @app.delete(f"{API}/jobs/{{job_id}}")
    def cancel_job(request: Request, job_id: str) -> Any:
        """취소. **202면 아직 끝난 것이 아니다** — 현장의 ack를 기다린다 (C5 「취소」 표)."""
        info, status = jobs.cancel(app.state.store, authenticate(request), job_id)
        return Utf8JSONResponse(status_code=status, content=info.to_json_dict())

    @app.get(f"{API}/admin-keys")
    def list_admin_keys(request: Request) -> Any:
        require_read(authenticate(request))
        return [one.to_json_dict() for one in signing.admin_keys(app.state.store)]

    @app.post(f"{API}/admin-keys")
    async def add_admin_key(request: Request) -> Any:
        require_admin(authenticate(request))
        return signing.add_admin_key(app.state.store, await _json(request)).to_json_dict()

    @app.delete(f"{API}/admin-keys")
    async def revoke_admin_key(request: Request) -> Any:
        require_admin(authenticate(request))
        return signing.revoke_admin_key(app.state.store, await _json(request)).to_json_dict()

    return app


async def _json(request: Request) -> dict[str, Any]:
    import json

    from chaeksas.center.settings import MAX_REQUEST_KB

    raw = await request.body()
    if len(raw) > MAX_REQUEST_KB * 1024:
        raise ApiError(413, "too_large", f"요청이 {MAX_REQUEST_KB} KB를 넘는다")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as e:
        raise ApiError(422, "input_invalid", "본문이 JSON이 아니다") from e
    if not isinstance(body, dict):
        raise ApiError(422, "input_invalid", "본문의 최상위가 객체가 아니다")
    return body
