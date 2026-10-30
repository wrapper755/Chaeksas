# Worker 화면 설계

> Worker 프로세스는 **UI 자동화 확장의 로컬 런타임**이다 ([ADR-0018](../decisions/0018-extensions.md)). 코드는 `extensions/ui_automation/src/chaeksas/ext/ui_automation/worker/`.

**Worker는 화면이 없는 서버 프로세스다** ([ADR-0012](../decisions/0012-bot-ui.md)). PC 실행기가 띄우고 감시하며, 실행 중인 BPM 프로세스·Studio가 127.0.0.1의 REST API(계약 C10)로 UI 자동화를 요청한다.

Worker에 관한 화면은 PC 실행기(상태·재시작)와 Tool UI(셀렉터 등록)에 있다 — 둘 다 Worker를 쓰지만 띄우는 것은 PC 실행기뿐이다.

| 하던 일 | 이제 어디서 |
| --- | --- |
| Worker 상태·재시작·로그 | [PC 실행기 BUI-09 「로컬 런타임」 탭](bot-ui.md#bui-09-로컬-런타임-탭-worker-프로세스-등) |
| 화면 등록 (요소 담기·검증·등록·삭제) | [Tool UI TOL-03 「UI 셀렉터 등록」](tool-ui.md#tol-03-ui-셀렉터-등록-구-bui-06) |
| 요소 계획 정보 | [TOL-04](tool-ui.md#tol-04-요소-계획-정보-구-bui-07) |
| 실행 / 시험 | [TOL-05](tool-ui.md#tol-05-셀렉터-시험-구-bui-08) |
| 트레이 | PC 실행기 트레이 하나로 합침 ([BUI-01](bot-ui.md#bui-01-트레이)) |

## 폐기된 화면 ID

| 옛 ID | 옛 화면 | 대체 |
| --- | --- | --- |
| WRK-01 | Worker 메인 창 | BUI-02 |
| WRK-02 | 화면 등록 | TOL-03 (구 BUI-06) |
| WRK-03 | 요소 계획 정보 | TOL-04 (구 BUI-07) |
| WRK-04 | 실행 / 시험 | TOL-05 (구 BUI-08) |
| WRK-05 | Worker 트레이 | BUI-01, BUI-09 |
