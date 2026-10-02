# S1 데스크톱 조작 — Windows UIA

결론 → [ADR-0020](../../docs/decisions/0020-windows-desktop-backend.md) (제안)

## 확인하려 한 것

Windows UIA로 메모장·엑셀의 버튼·입력칸·셀을 찾고 조작할 수 있는가. `pywinauto`(backend="uia")와 `uiautomation` 중 무엇을 Worker의 Windows 데스크톱 백엔드로 쓸 것인가. C8 데스크톱 로케이터(`automation_id`, `control_name`)로 충분한가.

## 환경

| 항목 | 값 |
| --- | --- |
| OS | Windows 11 Education 10.0.26200, 한국어 UI |
| 화면 | 1920×1080 한 대, 배율 100% (배율·다중 모니터는 S2) |
| 대상 | 메모장 11.2607 (Win11 새 메모장, WinUI/XAML + RichEdit), Excel (Microsoft 365, Office16) |
| Python | 3.12 (uv 관리), 스크립트마다 PEP 723 인라인 의존 |
| 라이브러리 | `uiautomation` 2.0.29 (+comtypes) / `pywinauto` 0.6.9 (+pywin32, comtypes, six) |

## 파일

| 파일 | 하는 일 |
| --- | --- |
| `dump_tree.py` | 앱을 띄우고 UIA 트리를 덤프 → `outputs/tree-*.txt` |
| `probe_uiautomation.py` | 시나리오를 `uiautomation`으로 → `outputs/result-uiautomation-*.json` |
| `probe_pywinauto.py` | 같은 시나리오를 `pywinauto`로 → `outputs/result-pywinauto-*.json` |

```bash
uv run spikes/S1-windows-uia/dump_tree.py notepad
uv run spikes/S1-windows-uia/probe_uiautomation.py notepad
uv run spikes/S1-windows-uia/probe_pywinauto.py excel
```

`outputs/`는 gitignore 대상이다 (사용자 탭 제목 등 개인 내용이 트리 덤프에 들어간다).

**안전장치:** 메모장은 새 탭 하나만 만들고, 입력·닫기 전에 선택된 탭이 실험 탭인지 확인해 아니면 멈춘다. 엑셀은 새 통합 문서만 만들고 창 제목이 `통합 문서N`이 아니면 멈춘다. 두 앱 창 자체는 닫지 않는다 (메모장 세션 복원 탭, 엑셀 문서 복구 창을 건드리지 않기 위해).

## 시나리오

- **메모장:** 창 붙기 → `AddButton`으로 새 탭 → 편집기 찾기(클래스·이름) → 한글 포함 두 줄 입력 → TextPattern으로 읽어 비교 → `File` 메뉴 펼치기·항목 읽기 → Esc → Ctrl+W → 저장 확인에서 「저장하지 않음」 → 탭 수 원상 복구 확인.
- **엑셀:** 창 붙기 → Ctrl+N → 이름 상자(`aid=1001`)로 B2 이동 → `123`, `456`, `=B2+B3`, `한글값` 입력 → 셀을 이름(`B4`)으로 찾아 값 읽기 → GridPattern → ValuePattern.SetValue로 쓰기 → Ctrl+W → 「저장 안 함」.

## 본 것

### 결과 요약

| | uiautomation | pywinauto |
| --- | --- | --- |
| 메모장 | 16/16, 5.95초 | 14/15, 8.84초 — 이름 검색 실패, 괄호 입력 누락 |
| 엑셀 | 17/17, 9.61초 | 17/19, 22.03초 — 셀 이름 검색 실패 (우회책으로 통과) |
| 셀 하나 찾기 (`B4`) | 82ms (`Name="B4"`) | 494ms (children 전체를 가져와 이름 비교) |
| 의존 | comtypes | pywin32, comtypes, six |

### 식별자 (C8 로케이터 관점)

| 대상 | 잡힌 방법 | 메모 |
| --- | --- | --- |
| 메모장 새 탭 버튼 | `automation_id=AddButton` | XAML, 언어 무관 |
| 메모장 파일 메뉴 | `automation_id=File` | 이름은 「파일」 |
| 메모장 편집기 | **aid 없음.** `control_name=텍스트 편집기` 또는 클래스 `RichEditD2DPT` | Win32 RichEdit |
| 메모장 저장 확인 | `automation_id=SecondaryButton` (저장하지 않음), `PrimaryButton`(저장), `CloseButton`(취소) | XAML ContentDialog. 같은 창 안에 뜬다 (최상위 창 아님) |
| 엑셀 이름 상자 | `automation_id=1001` (Edit), 부모 ComboBox `13` | Win32 컨트롤 ID. 버전에 따라 바뀔 수 있음 |
| 엑셀 시트 | DataGrid `automation_id=Grid`, 클래스 `XLSpreadsheetGrid`, 이름 「눈금」 | |
| 엑셀 셀 | DataItem, 이름 = 셀 주소(`B4`), ValuePattern = 표시 값 | |
| 엑셀 저장 확인 | 이름 「저장 안 함」 (aid 없음) | 메모장과 문구가 다르다 → 이름 로케이터는 앱·언어마다 다름 |

### 발견

1. **pywinauto의 `title`은 UIA `Name`이 아니다.** `child_window(title=...)`는 `element_info.rich_text`와 비교하는데, TextPattern·ValuePattern이 있는 컨트롤은 rich_text가 **내용**이다. 그래서 메모장 편집기를 `title="텍스트 편집기"`로, 엑셀 셀을 `title="B4"`로 찾지 못하고, 오히려 `title="579"`(셀 값)로 B4가 찾힌다. C8 `control_name`을 pywinauto로 구현하면 입력칸·셀에서 틀린다. 우회하려면 자식을 다 가져와 이름을 직접 비교해야 하고 6배 느리다.
2. **pywinauto `type_keys`는 `( ) + ^ % { } ~`를 문법으로 먹는다.** `(S1)`이 `S1`로 입력됐다. 업무 값을 넣으려면 매번 이스케이프해야 한다. `uiautomation.SendKeys`는 `{Ctrl}`처럼 중괄호만 문법이라 그대로 들어갔다 (한글 포함).
3. **엑셀 셀의 ValuePattern.SetValue는 쓰기로 쓸 수 없다.** 두 라이브러리 모두 예외 없이 끝나고 UIA로 다시 읽으면 B2가 `999`인데, B4(`=B2+B3`)는 `579` 그대로다. 실제 셀 값이 바뀌지 않았거나 재계산되지 않았다. 쓰기는 이름 상자로 이동 + 키 입력으로 한다.
4. **엑셀 그리드는 화면에 보이는 영역만 노출한다.** GridPattern 크기가 (30, 16)이고 `GetItem(3, 1)`이 `B4`가 아니라 `A3`을 돌려줬다. 셀은 좌표가 아니라 이름으로 찾고, 화면 밖 셀은 이름 상자로 먼저 이동해야 트리에 나온다. 대량 읽기는 UIA에 맞지 않는다.
5. **포커스.** 메뉴를 Esc로 닫으면 포커스가 메뉴 막대에 남아 다음 Ctrl+W가 무시됐다 (첫 실행에서 실패). 단축키 전에 대상 컨트롤에 포커스를 주어야 한다.
6. **Win11 메모장은 이전 탭을 복원한다.** 새로 띄운 메모장에 사용자의 저장 안 된 탭이 이미 있었다. 「새 창을 띄웠으니 내 것」이라고 가정하면 사용자 내용에 입력하거나 저장 없이 닫을 수 있다. 엑셀도 문서 복구 창과 함께 떴다.
7. `uiautomation`은 찾기 시간 초과 같은 로그를 **현재 폴더의 `@AutomationLog.txt`**에 기본으로 쓴다. 제품 코드에서는 로그 위치를 `platformdirs` 아래로 돌리거나 끈다.
8. 트리 크기: 메모장 70개 노드 0.25초, 엑셀(리본 포함, 깊이 9) 107개 노드 0.53초.

### 하지 않은 것 (다음에)

- 사내 앱(Win32 MFC·.NET WinForms·Java Swing 등) — 이 PC에 없다. Java는 Access Bridge가 필요할 수 있다.
- 배율 125%·150%, 다중 모니터 (S2).
- 잠금 화면·RDP 최소화 상태에서의 동작 (S4).
- 엑셀 COM(`win32com`) 비교 — 대량 읽기·쓰기는 UIA 대신 COM이나 파일(openpyxl)이 맞아 보이나 이 스파이크 범위 밖.
- 영어 UI에서의 이름 차이 측정.
