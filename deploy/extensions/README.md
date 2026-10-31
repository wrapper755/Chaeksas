# 확장 폴더

`deploy/compose.yaml`의 Center가 이 폴더를 `/extensions`(읽기 전용)로 붙여, **뜰 때** 여기의 파일을 들인다
([ADR-0121](../../docs/decisions/0121-extension-folder.md)).

- `<이름>.extension.json` — **기본 확장**. C13 정의만 둔다(봉투는 Center가 짓는다).
- `<이름>.consumer.json` — **승인 없는 일꾼**. `{"name", "topics", "token_sha256"}` (C15 §승인 없는 일꾼).
  일꾼은 토큰 원문을 `Authorization: Bearer`로 싣는다. 원문은 이 폴더에 두지 않는다.

**폴더가 원본이다** — 파일을 빼고 Center를 다시 띄우면 확장은 철회되고 일꾼 키는 폐기된다. 결과와 사유는 콘솔
CON-07 「확장 폴더」와 Center 로그에 보인다. 자리를 바꾸려면 `.env`에 `CHK_CENTER__EXTENSIONS_HOST_DIR`를 적는다.
이 README는 읽지 않는다(이름 꼴이 다르다).
