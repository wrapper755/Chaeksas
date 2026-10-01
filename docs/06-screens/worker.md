# Worker 화면 설계

> Worker 프로세스는 **UI 자동화 확장의 로컬 런타임**이다 ([ADR-0018](../decisions/0018-extensions.md)). 코드는 `extensions/ui_automation/worker/`.

**Worker는 화면이 없는 서버 프로세스다** ([ADR-0012](../decisions/0012-bot-ui.md)). Bot UI가 띄우고 감시하며, 실행 중인 Bot·Studio가 127.0.0.1의 REST API(계약 C10)로 UI 자동화를 요청한다.

Worker에 관한 화면은 모두 Bot UI에 있다.

| 하던 일 | 이제 어디서 |
| --- | --- |
| Worker 상태·재시작·로그 | [Bot UI BUI-09 「로컬 런타임」 탭](bot-ui.md#bui-09-로컬-런타임-탭-worker-프로세스-등) |
| 화면 등록 (요소 담기·검증·등록·삭제) | [Bot UI BUI-06 「UI 셀렉터 등록」](bot-ui.md#bui-06-ui-셀렉터-등록) |
| 요소 계획 정보 | [BUI-07](bot-ui.md#bui-07-요소-계획-정보) |
| 실행 / 시험 | [BUI-08](bot-ui.md#bui-08-셀렉터-시험) |
| 트레이 | Bot UI 트레이 하나로 합침 ([BUI-01](bot-ui.md#bui-01-트레이)) |

## 폐기된 화면 ID

| 옛 ID | 옛 화면 | 대체 |
| --- | --- | --- |
| WRK-01 | Worker 메인 창 | BUI-02 |
| WRK-02 | 화면 등록 | BUI-06 |
| WRK-03 | 요소 계획 정보 | BUI-07 |
| WRK-04 | 실행 / 시험 | BUI-08 |
| WRK-05 | Worker 트레이 | BUI-01, BUI-09 |
