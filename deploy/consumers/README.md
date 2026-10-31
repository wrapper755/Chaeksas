# 일꾼 폴더

`deploy/compose.yaml`의 Center가 이 폴더를 `/consumers`(읽기 전용)로 붙여, **뜰 때** 여기의 `<이름>.consumer.json`으로
일꾼을 들인다 ([ADR-0121](../../docs/decisions/0121-extension-folder.md), C15 §일꾼 들이기). **일꾼이 들어오는 길은
이것 하나다** — 요청 코드·승인이 없다.

```bash
uv run chk-center consumer-file worker --topics external --dir deploy/consumers
```

파일에는 `{"name", "topics", "token_sha256"}`만 있고 토큰 원문은 **명령이 한 번만** 찍는다 — 그 값을 일꾼의
`…CENTER__TOKEN`에 넣는다. 원문은 이 폴더에 두지 않는다. 외부 확장 정의는 일꾼이 뜰 때 Center에 올린다.

**폴더가 원본이다** — 파일을 빼고 Center를 다시 띄우면 일꾼 키가 폐기되고, 그 일꾼만 맡던 외부 확장은 철회된다.
결과와 사유는 콘솔 CON-07 「일꾼 폴더」와 Center 로그에 보인다. 자리를 바꾸려면 `.env`에
`CHK_CENTER__CONSUMERS_HOST_DIR`를 적는다. 이 README는 읽지 않는다(이름 꼴이 다르다).
