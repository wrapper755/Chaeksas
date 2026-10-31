# 확장 폴더

`deploy/compose.yaml`의 Center가 이 폴더를 `/extensions`(읽기 전용)로 붙여, **뜰 때** 여기의 `*.extension.json`을
외부 확장으로 등록한다 ([ADR-0121](../../docs/decisions/0121-extension-folder.md)). 함께 배포되는 프로그램이 제
확장 정의(C13 — 정의만, 봉투는 Center가 짓는다)를 여기에 복사한다. 결과와 사유는 콘솔 CON-07 「확장 폴더」에 보인다.

자리를 바꾸려면 `.env`에 `CHK_CENTER__EXTENSIONS_HOST_DIR`를 적는다. 이 README는 읽지 않는다(이름 꼴이 다르다).
