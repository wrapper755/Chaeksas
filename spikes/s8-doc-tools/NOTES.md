# S8 — AI 태스크의 도구 4종을 무엇으로 만드나

**물음:** M3 인수 묶음이 요구하는 도구 4종(`pdf_text_tool`·`excel_parser_tool`·`csv_parser_tool`·`http_request_tool`)을 무엇으로 만드나. 특히 **PDF에서 글자 뽑기**는 우리에게 없는 의존성이 필요하다 — 무엇을 들이나, 아니면 안 들이나.

**결론:** PDF는 `pypdf`, 엑셀은 이미 있는 `openpyxl`, CSV는 표준 라이브러리, HTTP는 이미 있는 `httpx`. 결정과 이유는 [ADR-0030](../../docs/decisions/0030-ai-task-tools.md).

## 1. 무엇이 필요한지 먼저 세었다

S7에서 이미 쟀다 — 업무 예제 50개의 AI 태스크 31곳이 쓰는 도구는 **6종, 12자리**뿐이다. 그중 **M3 인수 묶음 24개**가 요구하는 것만 추리면 넷이다.

| 도구 | 쓰는 예제 |
| --- | --- |
| `pdf_text_tool` | BX-01, BX-30, FX-06 |
| `http_request_tool` | BX-02, FX-01, FX-08 |
| `excel_parser_tool` | BX-01 |
| `csv_parser_tool` | BX-07 |

나머지 둘(`image_ocr_tool`·`excel_writer_tool`)은 M3 묶음에 없다 — 지금 만들지 않는다.

셋은 **이미 있는 것으로 된다**: 엑셀은 `openpyxl`(파일 출력이 이미 쓴다), CSV는 `csv`(표준), HTTP는 `httpx`(계약·서비스 앱 호출이 이미 쓴다). 재야 할 것은 **PDF 하나**뿐이다.

## 2. PDF 글자 뽑기 — 표본을 둘 두고 쟀다

업무 문서는 포털·회계 프로그램·한글 워드가 뽑아 준 것이라 **만든 쪽을 우리가 고를 수 없다.** 그래서 같은 글을 **생성기 둘**로 만들어 쟀다 (`make_pdf.py` — 한글이라 CID 글꼴을 심는다. ASCII PDF로 재면 진짜 문제를 못 본다).

재현:

```
uv run --no-project --with fpdf2 --with reportlab python spikes/s8-doc-tools/make_pdf.py
uv run --no-project --with pypdf --with pdfminer.six python spikes/s8-doc-tools/run.py
```

| 표본 | 후보 | 찾는 글 5개 | 뽑힌 길이 | 시간 |
| --- | --- | --- | --- | --- |
| fpdf2가 만든 것 | **pypdf** | 모두 나왔다 | 239자 | 108ms |
| fpdf2가 만든 것 | pdfminer.six | **0/5만 나왔다** | 2자 | 71ms |
| reportlab이 만든 것 | **pypdf** | 모두 나왔다 | 243자 | 5ms |
| reportlab이 만든 것 | pdfminer.six | 모두 나왔다 | 256자 | 45ms |

**읽은 것:** fpdf2가 만든 PDF에서 pdfminer.six는 **아무것도 못 뽑았다**(2자). 같은 파일에서 pypdf는 다 뽑았다. 생성기를 고를 수 없는 우리 자리에서는 이 차이가 크다.

**덤으로 안 것:** fpdf2가 만든 PDF는 뽑힌 글의 글자 사이에 `\x00`이 끼어 나온다 (ToUnicode CMap을 만든 쪽 문제다). 그대로 모델에게 주면 「세 금 계 산 서」처럼 쪼개져 보인다 — **제품 도구가 다듬어야 한다**는 뜻이다. `run.py`의 `clean()`이 그 자리다.

## 3. 무게 (설치 파일이 걸린 문제다 — ADR-0024는 PyInstaller onedir)

빈 폴더에 그것만 깔아 보았다 (`uv pip install --target`).

| 후보 | 크기 |
| --- | --- |
| **pypdf** | **1.7 MB** (딸려 오는 것 없음) |
| pdfminer.six | 24.7 MB (`cryptography`·`cffi`·`pycparser`·`charset_normalizer`가 딸려 온다) |

pdfminer.six는 **14배**다. 게다가 `cryptography`는 네이티브 바퀴라 OS·아키텍처마다 다른 것이 들어간다 — 우리 CI는 Windows·Linux 둘이고 개발 PC는 aarch64다.

## 4. 재지 않은 것

- **스캔 PDF(그림만 있는 것)** — 어느 후보도 글자가 없으면 못 뽑는다. 그것은 `image_ocr_tool`의 일이고 M3 묶음에 없다. 도구는 「글자가 없다」를 **업무 실패**로 올려 오류 경계가 받게 한다.
- **pymupdf** — 라이선스가 AGPL이라 후보에서 뺐다 (상용 배포가 걸린다).
- 표 구조 복원(셀 격자) — PDF는 표 정보를 남기지 않는다. 격자가 필요한 자리는 엑셀·CSV로 받는다.
