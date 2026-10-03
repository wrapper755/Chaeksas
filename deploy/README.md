# 서버 구성 (docker compose)

```bash
cd deploy
cp .env.example .env            # 토큰을 채운다
docker compose up -d --build
curl http://localhost:8800/healthz
```

| 서비스 | 포트 | 데이터 |
| --- | --- | --- |
| Center API | 8800 | 볼륨 `center-data` → `/data` (DB `center.sqlite3`, 패키지 zip) |

- 포트·환경변수의 원본은 [`docs/04-setup.md`](../docs/04-setup.md) §6이다.
- **관리자 토큰이 없으면 쓰기 API를 부를 수 없다** (읽기만 된다). 콘솔 BFF가 이 토큰을 들고 부른다 (ADR-0017).
- 아직 없는 것: Center 콘솔(`web/apps/center-console`), Neo4j·LLM 게이트웨이(M4), 역방향 프록시·TLS.
- 컨테이너는 비관리자(uid 10001)로 돈다. 볼륨 권한이 안 맞으면 `docker compose down -v`로 지우고 다시 올린다.
