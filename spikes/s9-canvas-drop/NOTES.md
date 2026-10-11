# s9 — Qt 트리 → QtWebEngine 캔버스 드래그

**결론: [ADR-0044](../../docs/decisions/0044-canvas-drag-and-drop.md) (수락).**

`docs/09-gaps.md` §4-4의 「없는 것 하나」(끌어다 놓기)를 붙이기 전에, **드롭이 우리 쪽에
오기는 하는가**를 먼저 봤다. 캔버스는 `QWebEngineView`이고 그 안은 Chromium이라 드래그를
스스로 처리할 수 있다 — 우리가 가로채지 못하면 이 조각은 서지 않는다.

Linux aarch64 / offscreen에서 봤다 (`drop.py`, `geometry.py`). Windows 실기 확인은 CI와
STU-03 시험이 한다 (제품 쪽 시험이 같은 길을 쓴다).

## 본 것

| | 물음 | 본 것 |
| --- | --- | --- |
| ① | 뷰의 `dropEvent`가 불리나 | **아니다.** 「본 것」에 `on view`가 한 번도 없다 |
| ② | 그럼 어디로 가나 | 내부 자식 `QWidget` 하나 — `focusProxy()`가 그것이다 |
| ③ | 그 자식이 `__init__`에 있나 | **없다.** 그때는 `QVBoxLayout`뿐이고 자식은 **뒤에 생긴다** |
| ④ | 가로채지나 | 된다 — 그 자식에 이벤트 필터를 달고 `DragEnter`에서 받으면 `Drop`도 온다 |
| ⑤ | 좌표가 페이지와 맞나 | 내부 위젯이 뷰를 **꽉 채운다** (640×480 ↔ 640×480, 왼쪽 위 (0,0)) |

```
① __init__ 때의 자식: ['QVBoxLayout']
② 뒤에 생겨 이벤트 필터를 단 자식: ['QWidget']
   focusProxy(): QWidget
③ enter: isAccepted=True
③ drop: isAccepted=True
④ 본 것: ['DragEnter on QWidget', 'Drop on QWidget']
⑤ devicePixelRatio: 1.0
뷰: (640, 480) | 내부 위젯: (640, 480) | 왼쪽 위: (0, 0) | DPR: 1.0
```

## 그래서 정한 것

- **이벤트 필터는 뷰가 아니라 내부 렌더 위젯에 단다.** 그 위젯이 `__init__`에 없으므로
  `ChildAdded`를 보고 **생길 때 단다**. 뷰에 `dropEvent`를 써 두면 **영원히 불리지 않는다** —
  이것이 이 스파이크의 값이다 (그렇게 짰다가 「드롭이 안 된다」를 한참 쫓을 자리였다).
- **좌표 변환에 `devicePixelRatio`를 넣지 않는다.** Qt의 드롭 위치도, 페이지의 CSS 픽셀도
  장치 독립 픽셀이고 내부 위젯이 뷰를 꽉 채우므로 **그대로 쓴다**. 넣으면 고해상도 화면에서
  놓은 자리와 생기는 자리가 어긋난다.
- **우리 MIME 형식일 때만 받는다.** 그래야 페이지 안의 HTML5 드래그(bpmn-js 팔레트)와
  바깥에서 끌어 온 파일이 그대로 Chromium으로 간다 — 받지 않으면 `eventFilter`가 `False`를
  돌려주고 원래 가던 길로 간다.
