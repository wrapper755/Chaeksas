# 글꼴 파일 두는 곳

`chaeksas.qt.theme.load_fonts()`가 이 폴더의 `.otf`·`.ttf`를 모두 등록한다. 지금은 **비어 있다** —
없으면 시스템 글꼴로 보이고, 화면은 그대로 뜬다.

## 넣을 것

| 글꼴 | 라이선스 | 어디서 | 왜 |
| --- | --- | --- | --- |
| Pretendard (Regular 400, Medium 500, SemiBold 600, Bold 700) | SIL Open Font License 1.1 | [orioncactus/pretendard](https://github.com/orioncactus/pretendard) 릴리스의 `public/static/*.otf` | 모든 글자 (스타일 가이드 §2-3). **Windows 현장 PC에 없다** |
| JetBrains Mono (Regular 400) | SIL Open Font License 1.1 | [JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono) | id·키·로그·JSON (mono) |

- 웹은 같은 글꼴을 `next/font`로 자체 호스팅한다 (woff2). **외부 CDN은 쓰지 않는다** — 사내망이다.
- 라이선스 파일(`OFL.txt`)을 글꼴과 함께 둔다.
- Qt는 가변 글꼴의 굵기 축을 아직 고르게 다루지 못한다. **굵기별 정적 파일**을 넣는다.

> 이 저장소에는 글꼴 바이너리를 아직 커밋하지 않았다. 설치 파일을 만들 때 반드시 들어가야 하므로
> (ADR-0024 — 설치 파일이 신뢰의 근거다), 넣을 때 커밋 메시지에 출처와 버전을 남긴다.
