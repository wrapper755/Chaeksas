# 앱에 포함한 글꼴

`chaeksas.qt.theme.load_fonts()`가 이 폴더의 `.otf`·`.ttf`를 모두 등록한다. **Windows 현장 PC에
Pretendard가 없기 때문에** 저장소에 넣는다 (스타일 가이드 §2-3). 설치 파일이 신뢰의 근거라
(ADR-0024) 글꼴도 거기 함께 들어가야 한다.

| 파일 | 글꼴 | 버전·출처 | 쓰임 |
| --- | --- | --- | --- |
| `Pretendard-{Regular,Medium,SemiBold,Bold}.otf` | Pretendard | v1.3.9, [orioncactus/pretendard](https://github.com/orioncactus/pretendard) 릴리스의 `public/static/` | 모든 글자 (400·500·600·700) |
| `JetBrainsMono-Regular.ttf` | JetBrains Mono | v2.304, [JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono) 릴리스의 `fonts/ttf/` | id·키·로그·JSON (mono) |
| `OFL-Pretendard.txt`, `OFL-JetBrainsMono.txt` | 라이선스 | SIL Open Font License 1.1 | 재배포 조건 |

- **굵기별 정적 파일을 넣는다.** Qt는 가변 글꼴의 굵기 축을 아직 고르게 다루지 못한다.
  (웹은 반대로 가변 woff2 하나를 쓴다 — `web/packages/ui/src/fonts/`.)
- 등록되면 패밀리 이름이 `Pretendard`·`JetBrains Mono`로 잡힌다. QSS의 글꼴 스택
  (`tokens.json` → 생성물)이 이 이름을 가리킨다.
- **없어도 멈추지 않는다.** 지우면 시스템 글꼴(맑은 고딕 → …)로 보인다.
- 올릴 때는 위 표의 버전·출처를 함께 고친다.
