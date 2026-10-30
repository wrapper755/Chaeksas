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

from chaeksas.center import accounts, keys, signer
from chaeksas.center.api import (
    approvals,
    bot_ui,
    delegations,
    deployments,
    enrollments,
    external_tasks,
    jobs,
    messages,
    package_access,
    packages,
    resources,
    runs,
    server_runner,
    signing,
    timers,
    virtual_workers,
)
from chaeksas.center.auth import (
    Caller,
    bearer,
    caller,
    require_admin,
    require_approval_read,
    require_console,
    require_package_read,
    require_read,
    require_upload,
)
from chaeksas.center.errors import ApiError, handle
from chaeksas.center.responses import Utf8JSONResponse
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.accounts import (
    AccountCreateRequest,
    AccountUpdateRequest,
    LoginRequest,
    PasswordChangeRequest,
    WhoAmI,
)
from chaeksas.contracts.center_api import (
    LIST_LIMIT_DEFAULT,
    DeploymentRequest,
    DeploymentRevokeRequest,
    ExtensionRevokeRequest,
    RevokeRequest,
)
from chaeksas.contracts.center_keys import CenterKeyCreated, CenterKeyCreateRequest
from chaeksas.contracts.center_keys import validate_create as validate_key_create

API = "/api/v1"


def create_app(settings: Settings, *, store: Store | None = None) -> FastAPI:
    """Center 앱 하나. `store`를 주면 그것을 쓴다 (시험은 메모리 DB를 준다)."""
    # 모든 JSON 응답에 charset=utf-8 (PowerShell 5.1이 한글을 깨뜨리지 않게, 이슈 #3)
    app = FastAPI(title="Chaeksas Center", version="0.1.0", default_response_class=Utf8JSONResponse)
    app.state.settings = settings
    # 일정의 시간대는 **뜰 때** 푼다 (ADR-0110 §3) — 틀린 이름으로 뜬 Center의 일정이 하트비트마다 터지지 않게.
    settings.zone()
    app.state.store = store or Store(settings.db_path)
    # 첫 비밀번호 파일을 두는 곳 — **DB를 제가 열었을 때만**. 저장소를 받았으면(시험) 설정의
    # 기본 경로가 이 PC의 진짜 데이터 폴더일 수 있다.
    data_folder = settings.data_folder() if store is None else None
    # 서명 키와 첫 관리자는 **뜰 때** 갖춘다 (ADR-0090 §2·§5) — 처음 누를 때 만들면 그 사이에
    # 하트비트가 Center 키 없는 목록을 내려 준다.
    signer.active(app.state.store)
    if store is None or settings.first_admin_password:
        # 받은 저장소(시험)에는 적어 준 것만 만든다 — 비밀번호를 지어 찍을 까닭이 없다.
        accounts.ensure_first_admin(
            app.state.store,
            username=settings.first_admin_username,
            password=settings.first_admin_password,
            data_dir=data_folder,
        )

    def authenticate(request: Request) -> Caller:
        return caller(
            request,
            app.state.store,
            admin_token=settings.admin_token,
            read_token=settings.read_token,
        )

    app.state.authenticate = authenticate
    app.state.external_waiters = external_tasks.Waiters(settings.external_task_max_waiters)
    app.add_exception_handler(ApiError, handle)
    app.include_router(bot_ui.router)
    app.include_router(enrollments.router)
    app.include_router(server_runner.router)
    app.include_router(delegations.router)
    app.include_router(external_tasks.router)
    app.include_router(runs.router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """인증 없음 — 비밀이 없다. 컨테이너 상태 확인이 쓴다."""
        return {"status": "ok", "server_time": now_iso()}

    # ─────────────────── 로그인·관리자 계정 (C5, ADR-0090) ───────────────────

    @app.post(f"{API}/auth/login")
    async def login(request: Request) -> Any:
        """인증 없이 부른다. 세션 토큰은 **이 응답에만** 실린다."""
        wanted = _model(LoginRequest, await _json(request))
        return accounts.login(app.state.store, username=wanted.username.strip(), password=wanted.password)

    @app.post(f"{API}/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        token = bearer(request)
        if token:
            accounts.logout(app.state.store, token)
        return Response(status_code=204)

    @app.get(f"{API}/auth/me")
    def whoami(request: Request) -> Any:
        found = authenticate(request)
        if found.kind not in ("admin", "read"):
            raise ApiError(403, "forbidden", "콘솔 계정·토큰으로만 묻는다")
        return WhoAmI(
            actor=found.actor, role="admin" if found.is_admin else "viewer", account=found.account
        )

    @app.put(f"{API}/auth/password")
    async def change_password(request: Request) -> Any:
        """자기 비밀번호. **세션으로만** — 토큰에는 계정이 없다."""
        found = authenticate(request)
        if found.account is None:
            raise ApiError(403, "account_only", "로그인한 계정으로만 바꿀 수 있다")
        wanted = _model(PasswordChangeRequest, await _json(request))
        return accounts.change_own_password(
            app.state.store,
            found.account,
            current=wanted.current_password,
            new=wanted.new_password,
            data_dir=data_folder,
        )

    @app.get(f"{API}/accounts")
    def list_accounts(request: Request) -> Any:
        require_admin(authenticate(request))
        return accounts.listing(app.state.store)

    @app.post(f"{API}/accounts", status_code=201)
    async def create_account(request: Request) -> Any:
        found = require_admin(authenticate(request))
        wanted = _model(AccountCreateRequest, await _json(request))
        return accounts.create(
            app.state.store,
            username=wanted.username.strip(),
            password=wanted.password,
            role=wanted.role,
            by=found.actor,
        )

    @app.put(f"{API}/accounts/{{username}}")
    async def update_account(request: Request, username: str) -> Any:
        require_admin(authenticate(request))
        wanted = _model(AccountUpdateRequest, await _json(request))
        return accounts.update(
            app.state.store,
            username,
            role=wanted.role,
            disabled=wanted.disabled,
            password=wanted.password,
            data_dir=data_folder,
        )

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

    @app.post(f"{API}/center-keys/{{key_id}}/purge", status_code=204)
    def purge_center_key(request: Request, key_id: str) -> None:
        """삭제 (CON-11, ADR-0095). **폐기된 키만** — 폐기 → 삭제 두 걸음이다."""
        require_admin(authenticate(request))
        if keys.get(app.state.store, key_id) is None:
            raise ApiError(404, "not_found", f"키 {key_id}가 없다")
        if not keys.purge(app.state.store, key_id):
            raise ApiError(409, "not_revoked", "폐기된 키만 지울 수 있다 — 먼저 폐기하세요")

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
        # **콘솔 토큰만** (C5 권한표) — 현장 키로 남의 PC 현황을 읽지 못한다.
        require_console(authenticate(request))
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

    @app.put(f"{API}/bot-uis/{{bot_ui_id}}/utility")
    async def set_bot_ui_utility(request: Request, bot_ui_id: str) -> Any:
        """CON-03 「셀렉터 등록」 (C5). 켠 PC만 등록 세션(`reg_…`)의 외부 작업을 올린다 (C15)."""
        require_admin(authenticate(request))
        body = await _json(request)
        on = body.get("selector_registration")
        if not isinstance(on, bool):
            raise ApiError(422, "input_invalid", "selector_registration은 참·거짓이어야 한다")
        if not bot_ui.set_selector_registration(app.state.store, bot_ui_id, on=on):
            raise ApiError(404, "not_found", f"Bot UI {bot_ui_id}가 없다")
        return {"bot_ui_id": bot_ui_id, "selector_registration": on}

    # ─────────────────── 서버 실행기 (C12·CON-12) ───────────────────

    @app.get(f"{API}/server-runners")
    def list_server_runners(request: Request) -> Any:
        require_console(authenticate(request))  # 위와 같다 (C5 권한표)
        return server_runner.runner_listing(app.state.store)

    @app.post(f"{API}/server-runners/{{runner_id}}/pause")
    def pause_runner(request: Request, runner_id: str) -> Any:
        require_admin(authenticate(request))
        if not server_runner.set_paused(app.state.store, runner_id, paused=True):
            raise ApiError(404, "not_found", f"서버 실행기 {runner_id}가 없다")
        return {"server_runner_id": runner_id, "paused": True}

    @app.post(f"{API}/server-runners/{{runner_id}}/resume")
    def resume_runner(request: Request, runner_id: str) -> Any:
        require_admin(authenticate(request))
        if not server_runner.set_paused(app.state.store, runner_id, paused=False):
            raise ApiError(404, "not_found", f"서버 실행기 {runner_id}가 없다")
        return {"server_runner_id": runner_id, "paused": False}

    @app.post(f"{API}/server-runners/{{runner_id}}/mark-lost")
    def mark_runner_lost(request: Request, runner_id: str) -> Any:
        require_admin(authenticate(request))
        found = server_runner.mark_lost(app.state.store, runner_id)
        return found

    # ─────────────────── 패키지 (C5) ───────────────────

    @app.post(f"{API}/packages")
    async def upload_package(request: Request) -> Any:
        """업로드 (C5). **Studio용 키로도 된다** — 올리는 쪽이 Studio다 (ADR-0013).

        올라간 것은 **후보**다. 승인·배포는 관리자의 일이라 키로는 할 수 없다.
        """
        found = require_upload(authenticate(request))
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
        require_package_read(authenticate(request))
        # 누락 리소스는 **읽을 때** 리소스 목록과 대조해 센다 (C5 `missing_resources`).
        return packages.listing(
            app.state.store,
            kind=kind,
            status=status,
            package_id=id,
            index=resources.index(app.state.store),
        )

    @app.get(f"{API}/packages/{{package_id}}/{{version}}/info")
    def package_info(request: Request, package_id: str, version: str) -> Any:
        require_package_read(authenticate(request))
        return packages.info_of(
            app.state.store, package_id, version, index=resources.index(app.state.store)
        )

    @app.get(f"{API}/packages/{{package_id}}/{{version}}/dependents")
    def package_dependents(request: Request, package_id: str, version: str) -> Any:
        """이 패키지를 쓰는 패키지 (C5·CON-06 「이 패키지를 쓰는 패키지」)."""
        require_package_read(authenticate(request))
        return packages.dependents(app.state.store, package_id, version)

    @app.delete(f"{API}/packages/{{package_id}}/{{version}}")
    def delete_package(request: Request, package_id: str, version: str) -> Any:
        """삭제 (C5). 서명이 필요 없다 — 막는 쪽이라서 관리자가 관문이다."""
        require_admin(authenticate(request))
        packages.remove(
            app.state.store, package_dir=settings.package_dir, package_id=package_id, version=version
        )
        return Response(status_code=204)

    @app.get(f"{API}/packages/{{package_id}}/{{version}}")
    def download_package(request: Request, package_id: str, version: str) -> Any:
        """내려받기 (C5). **실행하는 쪽은 자기 배포분만** — 관문은 `package_access`다."""
        package_access.guard_download(
            app.state.store, authenticate(request), package_id=package_id, version=version
        )
        path, content_hash = packages.file_path(
            app.state.store, package_dir=settings.package_dir, package_id=package_id, version=version
        )
        packages.count_download(app.state.store, package_id=package_id, version=version)
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

    @app.put(f"{API}/packages/{{package_id}}/{{version}}/status")
    async def set_package_status(request: Request, package_id: str, version: str) -> Any:
        """지원 종료 표시 (C5). **서명이 없다** — 허용하는 쪽이 아니라 막는 쪽이라서다."""
        require_admin(authenticate(request))
        return packages.set_status(app.state.store, package_id, version, await _json(request))

    # ─────────────────── 승인·배포 — Center가 서명한다 (C2·C5, ADR-0090) ───────────────────

    @app.put(f"{API}/packages/{{package_id}}/{{version}}/signature")
    def approve_package(request: Request, package_id: str, version: str) -> Any:
        """승인. 본문 없음 — Center가 `package` 봉투를 지어 서명한다."""
        found = require_admin(authenticate(request))
        return signing.approve_package(app.state.store, package_id, version, by=found.actor)

    @app.post(f"{API}/packages/{{package_id}}/{{version}}/revoke")
    async def revoke_package(request: Request, package_id: str, version: str) -> Any:
        found = require_admin(authenticate(request))
        wanted = _model(RevokeRequest, await _json(request))
        return signing.revoke_package(
            app.state.store, package_id, version, reason=wanted.reason, by=found.actor
        )

    @app.post(f"{API}/deployments")
    async def create_deployment(request: Request) -> Any:
        """배포 (C5). Center가 `deployment` 봉투를 지어 서명하고 받아 두었다가 그대로 내려 준다."""
        found = require_admin(authenticate(request))
        wanted = _model(DeploymentRequest, await _json(request))
        made = deployments.create(app.state.store, wanted, by=found.actor, package_dir=settings.package_dir)
        return made

    @app.delete(f"{API}/deployments")
    async def revoke_deployment(request: Request) -> Any:
        found = require_admin(authenticate(request))
        wanted = _model(DeploymentRevokeRequest, await _json(request))
        made = deployments.revoke(app.state.store, wanted.deployment_id, reason=wanted.reason, by=found.actor)
        return made

    @app.get(f"{API}/deployments")
    def list_deployments(request: Request, bot_ui: str | None = None, active: bool = False) -> Any:
        require_read(authenticate(request))
        return deployments.listing(app.state.store, target_id=bot_ui, active_only=active)

    # ─────────────────── 리소스 (C7·CON-07) ───────────────────

    @app.get(f"{API}/resources")
    def list_resources(
        request: Request, type: str | None = None, resource_type: str | None = None
    ) -> Any:
        """리소스 목록. 읽기·관리자 토큰과 Studio·Bot UI·서버 실행기 키가 읽는다 (C7)."""
        require_read(authenticate(request))
        return resources.listing(app.state.store, type=type, resource_type=resource_type)

    @app.get(f"{API}/resources/contributed-kinds")
    def list_contributed_kinds(request: Request) -> Any:
        """확장이 기여한 자원 **종류** 목록 (CON-07 탭 하나씩). 읽기 실패도 함께 온다."""
        require_read(authenticate(request))
        return {"items": resources.catalog_kinds(app.state.store), "fetched_at": now_iso()}

    @app.get(f"{API}/resources/contributed/{{resource_type}}/{{resource_id}}")
    def get_contributed(request: Request, resource_type: str, resource_id: str) -> Any:
        require_read(authenticate(request))
        return resources.contributed_resource(app.state.store, resource_type, resource_id)

    @app.get(f"{API}/resources/extensions/{{extension_id}}")
    def get_extension(request: Request, extension_id: str) -> Any:
        require_read(authenticate(request))
        return resources.extension(app.state.store, extension_id)

    @app.get(f"{API}/resources/service-apps/{{app_id}}")
    def get_service_app(request: Request, app_id: str) -> Any:
        require_read(authenticate(request))
        return resources.service_app(app.state.store, app_id)

    @app.post(f"{API}/resources/extensions")
    async def register_extension(request: Request) -> Any:
        """외부 확장 등록. 검사를 지나면 Center가 `extension` 봉투로 서명한다 (C13 E6, ADR-0090)."""
        found = require_admin(authenticate(request))
        info, created = resources.register_extension(app.state.store, found, await _json(request))
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.delete(f"{API}/resources/extensions")
    async def revoke_extension(request: Request) -> Any:
        """등록 해제 (C13). Center가 `extension_revoke` 봉투로 서명한다. **되살릴 수 없다.**"""
        found = require_admin(authenticate(request))
        wanted = _model(ExtensionRevokeRequest, await _json(request))
        return resources.revoke_extension(
            app.state.store, wanted.id, wanted.version, reason=wanted.reason, by=found.actor
        )

    @app.get(f"{API}/signing-keys")
    def public_signing_keys() -> Any:
        """믿는 키 목록 — **인증 없음**(공개키다). 어댑터 일꾼이 외부 확장 봉투를 다시 검증하려고 받는다 (C7)."""
        return [one.to_json_dict() for one in signing.admin_keys(app.state.store)]

    # ─────────────────── 결재 (C6·CON-04) ───────────────────

    @app.post(f"{API}/approvals")
    async def create_approval(request: Request) -> Any:
        """실행하는 쪽이 결재를 올린다. **확인(`confirmation`)은 올라오지 않는다** (C6)."""
        info, created = approvals.create(app.state.store, authenticate(request), await _json(request))
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.get(f"{API}/approvals")
    def list_approvals(
        request: Request,
        state: str | None = None,
        bpm_process_id: str | None = None,
        host: str | None = None,
        assignee: str | None = None,
    ) -> Any:
        on_behalf = require_approval_read(authenticate(request))
        return approvals.listing(
            app.state.store,
            state=state,
            bpm_process_id=bpm_process_id,
            host=host,
            assignee=assignee,
            on_behalf=on_behalf,
        )

    @app.get(f"{API}/approvals/{{request_id}}")
    def get_approval(request: Request, request_id: str) -> Any:
        on_behalf = require_approval_read(authenticate(request))
        return approvals.get(app.state.store, request_id, on_behalf=on_behalf)

    @app.post(f"{API}/approvals/{{request_id}}/answer")
    async def answer_approval(request: Request, request_id: str) -> Any:
        """답하기. **Center가 폼으로 검증한다** — 틀리면 422 `answer_invalid` (C6)."""
        return approvals.answer(
            app.state.store, authenticate(request), request_id, await _json(request)
        )

    @app.delete(f"{API}/approvals/{{request_id}}")
    async def withdraw_approval(request: Request, request_id: str, reason: str = "") -> Any:
        """회수. 올린 쪽은 현장·실행 사유로, 관리자는 `admin_withdraw`로 (C6)."""
        return approvals.withdraw(app.state.store, authenticate(request), request_id, reason)

    # ─────────────────── 작업 (C5·CON-05) ───────────────────

    @app.post(f"{API}/jobs")
    async def create_job(request: Request) -> Any:
        """작업 지시. **서명이 없다** — 배포와 달리 「언제 돌려라」일 뿐이다 (C5 권한표)."""
        info, created = jobs.create(app.state.store, authenticate(request), await _json(request))
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.get(f"{API}/schedules")
    def list_schedules(request: Request) -> Any:
        # 일정은 콘솔이 본다 (C5 §일정, CON-02) — 현장 키로 남의 일정을 읽지 못한다.
        require_console(authenticate(request))
        return [one.to_json_dict() for one in timers.schedules(app.state.store, tz=settings.zone())]

    @app.get(f"{API}/jobs")
    def list_jobs(
        request: Request,
        state: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        bpm_process_id: str | None = None,
        virtual_worker: str | None = None,
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
            virtual_worker=virtual_worker,
            limit=limit,
            offset=offset,
        )

    # ─────────────────── 가상 직원 (C5 §가상 직원·CON-13, ADR-0085) ───────────────────

    @app.post(f"{API}/virtual-workers")
    async def create_virtual_worker(request: Request) -> Any:
        """등록 — **접수 Bot에 결재 없는 일괄 기동이 없어야** 묶인다 (C14 B16)."""
        require_admin(authenticate(request))
        made = virtual_workers.create(app.state.store, settings.package_dir, await _json(request))
        return Utf8JSONResponse(status_code=201, content=made.to_json_dict())

    @app.get(f"{API}/virtual-workers")
    def list_virtual_workers(request: Request, supervisor: str | None = None) -> Any:
        on_behalf = virtual_workers.reader(authenticate(request))
        return virtual_workers.listing(app.state.store, supervisor=supervisor, on_behalf=on_behalf)

    @app.get(f"{API}/virtual-workers/{{worker_id}}")
    def get_virtual_worker(request: Request, worker_id: str) -> Any:
        on_behalf = virtual_workers.reader(authenticate(request))
        return virtual_workers.get(app.state.store, worker_id, on_behalf=on_behalf)

    @app.put(f"{API}/virtual-workers/{{worker_id}}")
    async def update_virtual_worker(request: Request, worker_id: str) -> Any:
        require_admin(authenticate(request))
        return virtual_workers.update(app.state.store, settings.package_dir, worker_id, await _json(request))

    @app.delete(f"{API}/virtual-workers/{{worker_id}}")
    def delete_virtual_worker(request: Request, worker_id: str) -> Any:
        require_admin(authenticate(request))
        virtual_workers.remove(app.state.store, worker_id)
        return {"deleted": worker_id}

    @app.get(f"{API}/jobs/{{job_id}}")
    def get_job(request: Request, job_id: str) -> Any:
        return jobs.get(app.state.store, authenticate(request), job_id)

    @app.delete(f"{API}/jobs/{{job_id}}")
    def cancel_job(request: Request, job_id: str) -> Any:
        """취소. **202면 아직 끝난 것이 아니다** — 현장의 ack를 기다린다 (C5 「취소」 표)."""
        info, status = jobs.cancel(app.state.store, authenticate(request), job_id)
        return Utf8JSONResponse(status_code=status, content=info.to_json_dict())

    # ─────────────────── 메시지 (C12 §메시지) ───────────────────

    @app.post(f"{API}/messages")
    async def post_message(request: Request) -> Any:
        """메시지 넣기. **서명이 없다** — 작업과 같은 관문이다 (C5 권한표).

        기다리는 실행이 있으면 그 실행기에게, 없고 메시지 시작 트리거면 **작업으로** 간다.
        """
        info, created = messages.create(
            app.state.store, authenticate(request), await _json(request)
        )
        return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())

    @app.get(f"{API}/admin-keys")
    def list_admin_keys(request: Request) -> Any:
        require_read(authenticate(request))
        return [one.to_json_dict() for one in signing.admin_keys(app.state.store)]

    return app


def _model(cls: Any, body: dict[str, Any]) -> Any:
    """본문을 계약 모델로 — 맞지 않으면 422 `input_invalid`."""
    try:
        return cls.model_validate(body)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e


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
