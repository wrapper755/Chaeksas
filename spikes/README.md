# spikes/ — 실험 공간

모르는 것을 빨리 확인하는 곳. 여기서는 규칙을 느슨하게 둔다 (테스트·타입·문서 규칙 면제).

규칙은 세 가지뿐:

1. 실험 하나당 폴더 하나: `spikes/S<번호>-<주제>/` (예: `S1-windows-uia/`)
2. 폴더 안에 `NOTES.md` — 무엇을 확인하려 했고, 무엇을 봤는지 (실패도 기록)
3. 끝나면 `docs/decisions/`에 ADR을 쓰고, `NOTES.md` 맨 위에 그 ADR 번호를 적는다

제품 코드(`packages/`, `apps/`)는 이 폴더를 import하지 않는다.

끝난 스파이크: S1~S5 → [ADR-0020](../docs/decisions/0020-windows-desktop-backend.md)~[0024](../docs/decisions/0024-desktop-packaging-extensions.md) (모두 「제안」).
S1~S4는 Windows 11 실기에서, S5는 Windows(묶기·크기·기동)와 Linux(`linux-core-hook/`, 확장 호스트와 훅)에서 나눠 봤다.
