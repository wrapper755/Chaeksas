"""어느 시험이 **서버 쪽**인가 — CI의 Windows 잡이 빼는 것 (ADR-0104).

서버(Center·서버 실행기·일꾼·서비스 앱)는 Linux에서만 돈다. 여기 적은 파일의 시험에는 `conftest.py`가
`server` 표시를 붙이고, Windows 잡은 `pytest -m "not server"`로 돈다. **기본은 양쪽이다** — 적지 않은
파일은 Windows에서도 돈다(빠뜨리면 더 보는 쪽으로 틀린다).

**엔진(`core`)은 적지 않는다** — PC Bot은 Bot UI의 실행기 자식으로 Windows에서 엔진을 돌린다.
**PC 쪽 코드가 걸린 파일도 적지 않는다** (`test_ci_scope.py`가 import로 본다): 서버 실행기 위임
시험은 PC를 진짜 자식 프로세스로 돌리고, UI 자동화 앱 시험은 Worker의 부르는 쪽을 함께 본다.
"""

from __future__ import annotations

#: 서버 쪽 시험 파일 (모듈 이름).
SERVER_SIDE = frozenset({
    # Center
    "test_center_accounts",
    "test_center_api",
    "test_center_app",
    "test_center_delegations",
    "test_center_enrollment",
    "test_center_external_tasks",
    "test_center_keys",
    "test_center_messages",
    "test_center_migrations",
    "test_center_runs",
    "test_center_server_runner",
    "test_center_sql_portable",
    "test_center_storage_threads",
    "test_center_virtual_workers",
    # 서버 실행기 (`test_server_runner_delegation`은 PC를 자식 프로세스로 돌려 양쪽이다)
    "test_server_runner_agent",
    "test_server_runner_deploy",
    "test_server_runner_extension_run",
    "test_server_runner_extensions",
    "test_server_runner_messages",
    "test_server_runner_resume",
    "test_server_runner_run",
    "test_server_runner_secret_file",
    "test_server_runner_seen",
    "test_m7_server_rerun",
    # 일꾼 — 서비스 앱·어댑터·모의 앱
    "test_service_kit",
    "test_service_kit_admin",
    "test_service_kit_consumer",
    "test_service_kit_llm",
    "test_adapter_consumer",
    "test_mock_apps",
    # UI 자동화 앱의 서버 부분 (`test_ui_service_app`은 Worker의 부르는 쪽을 함께 봐 양쪽이다)
    "test_ui_registry",
    "test_ui_console",
})

#: 서버 파일이 import하면 안 되는 것 — PC에서 도는 코드다.
CLIENT_MODULES = (
    "chaeksas.bot_ui",
    "chaeksas.tool_ui",
    "chaeksas.qt",
    "PySide6",
    "chaeksas.ext.ui_automation.worker",
    "chaeksas.ext.ui_automation.client",
)
