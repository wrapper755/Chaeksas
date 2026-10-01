# spikes/ — 실험 공간

모르는 것을 빨리 확인하는 곳. 여기서는 규칙을 느슨하게 둔다 (테스트·타입·문서 규칙 면제).

규칙은 세 가지뿐:

1. 실험 하나당 폴더 하나: `spikes/S<번호>-<주제>/` (예: `S1-windows-uia/`)
2. 폴더 안에 `NOTES.md` — 무엇을 확인하려 했고, 무엇을 봤는지 (실패도 기록)
3. 끝나면 `docs/decisions/`에 ADR을 쓰고, `NOTES.md` 맨 위에 그 ADR 번호를 적는다

제품 코드(`packages/`, `apps/`)는 이 폴더를 import하지 않는다.

예정된 스파이크: `docs/05-roadmap.md`의 M1 (S1 데스크톱 조작, S2 캡처·DPI, S3 Studio 셸, S4 상주·자동 시작).
