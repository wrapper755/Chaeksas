# 결정 기록 (ADR)

결정 하나당 파일 하나. 형식은 [template.md](template.md).

- 번호는 순서대로 붙이고 재사용하지 않는다.
- 수락된 ADR은 고치지 않는다. 뒤집을 때는 새 ADR을 쓰고 옛 것의 상태를 `대체됨(ADR-XXXX)`으로 바꾼다.
- 스파이크가 끝나면 결론이 "안 된다"여도 ADR을 쓴다.
- "제안" 상태를 "수락"으로 바꿀 때는 이 표와 해당 파일의 상태 칸을 함께 고친다.

| # | 결정 | 상태 |
| --- | --- | --- |
| [0001](0001-new-repo-prototypes-as-reference.md) | 새 저장소로 다시 만들고 프로토타입 4개는 참고용으로 동결한다 | 수락 |
| [0002](0002-docs-first-and-adr.md) | 문서를 먼저 쓰고, 문서는 저장소 안 Markdown으로 둔다 | 수락 |
| [0003](0003-target-platforms.md) | 서버는 Linux 주, 클라이언트는 Windows 주 | 수락 |
| [0004](0004-monorepo-uv-workspace.md) | 저장소 하나, uv 워크스페이스 | 수락 |
| [0005](0005-python-version.md) | Python 3.12로 통일 | 수락 |
| [0006](0006-single-contracts-package.md) | 계약은 패키지 하나, 스키마 버전 정수 | 수락 |
| [0007](0007-client-initiated-communication.md) | 통신은 항상 현장 PC → 서버 | 수락 |
| [0008](0008-map-driver-hands-boundary.md) | 역할 경계: BPMN = 지도, AI = 운전사, 실행, 손 | 수락 · 역할 이름 일부 대체됨(0012) |
| [0009](0009-worker-deployment-form.md) | Worker는 미리 떠 있는 트레이 앱 | 대체됨(0012) |
| [0010](0010-service-apps.md) | 서버 앱은 "서비스 앱"으로 통일 (자율/결정 수행 모드) | 수락 · 인증 부분 대체됨(0013) |
| [0011](0011-config-ports-env.md) | 포트는 기본값 + 설정 변경, 환경변수 접두사는 CHK_ | 수락 |
| [0012](0012-bot-ui.md) | 현장 PC의 프로그램은 Bot UI 하나: Bot(BPM 프로세스) 실행, Worker 실행 관리, UI 셀렉터 등록 | 수락 · 실행기 동시 실행 제안은 대체됨(0014) |
| [0013](0013-api-keys.md) | Center 키는 Bot UI에 등록, 서비스 앱 키는 각 앱 관리 콘솔 발급, BPM 프로세스 단위 키 참조 | 수락 (키 지정 위치 안 C 확정) |
| [0014](0014-one-bot-per-pc.md) | PC 한 대에서 실행 중인 Bot은 하나, 나머지는 Bot UI 대기열, 결재 대기 중에도 끝까지 | 수락 (결재 대기 중에도 끝까지 자리를 쥔다) |
| [0015](0015-run-location.md) | BPM 프로세스의 실행 위치: PC(Bot UI, 하나씩) 또는 서버(Center 관리 서버 실행기, 동시 실행) | 수락 · 기본값은 대체됨(0016) |
| [0016](0016-server-first.md) | 서버 우선: 업무 대부분은 서버 BPM 프로세스(기본값 서버), PC Bot은 사람·화면이 필요할 때만. 서버 Bot 이름·상한 10/5·M7 확정 | 수락 (PC 위임은 제안) |
| [0017](0017-web-nextjs-design-system.md) | 웹 화면은 Next.js(BFF), 모든 화면은 디자인 토큰 하나(`design/tokens.json`)와 스타일 가이드를 따른다. Streamlit 폐기 | 수락 (버전은 M1에서 고정) |
| [0018](0018-extensions.md) | 확장(Extension): BPM 프로세스의 공통 기능은 확장으로 붙인다. 내장·사내·외부 등급, 기여 지점, 외부 앱은 HTTP 어댑터, UI 자동화는 첫 내장 확장 | 수락 (사내 확장 코드 배포·어댑터 세부는 제안) |
| [0019](0019-package-names.md) | 패키지 이름은 `chaeksas.*` PEP 420 네임스페이스, 폴더 이름은 문서 그대로. 확장은 `chaeksas.ext.<id>` | 수락 |
