"""Center API 한 벌 (`create_app`).

경로는 C4·C5·C7이 정한 그대로다. 권한은 C5 「권한표」를 `auth`가 한 곳에서 본다.

    app = create_app(Settings.from_env())
    uvicorn.run(app, ...)          # 또는 `chk-center`

**콘솔은 여기 없다** (ADR-0017 — `web/apps/center-console`). Center는 API만 가진다.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from chaeksas.center import keys
from chaeksas.center.api import bot_ui, packages
from chaeksas.center.auth import Caller, caller, require_admin, require_read
from chaeksas.center.errors import ApiError, handle
from chaeksas.center.responses import Utf8JSONResponse
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store, now_iso
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
        return FileResponse(
            path,
            media_type="application/zip",
            filename=path.name,
            headers={"X-Content-Hash": content_hash},
        )

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
