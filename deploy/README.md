# 서버 구성 (docker compose)

```bash
cd deploy
cp .env.example .env            # 토큰과 세션 비밀을 채운다
docker compose up -d --build
curl http://localhost:8800/healthz
```

그다음 브라우저로 <http://localhost:8501>에 들어가 `.env`의 관리자 토큰으로 로그인한다.

| 서비스 | 포트 | 데이터 |
| --- | --- | --- |
| Center API | 8800 | 볼륨 `center-data` → `/data` (DB `center.sqlite3`, 패키지 zip) |
| Center 콘솔 (Next.js) | 8501 | 없음 (상태를 들고 있지 않다) |

- 포트·환경변수의 원본은 [`docs/04-setup.md`](../docs/04-setup.md) §6이다.
- **관리자 토큰이 없으면 쓰기 API를 부를 수 없다** (읽기만 된다). 콘솔 BFF가 이 토큰을 들고 부른다 ([ADR-0017](../docs/decisions/0017-web-nextjs-design-system.md)).
- 콘솔은 `http://center:8800`으로 Center를 부른다 — **브라우저가 아니라 콘솔 서버가** 부르기 때문에 `localhost`가 아니다.
- 그 포트를 이미 쓰는 것이 있으면 `.env`의 `CHK_CENTER__HOST_PORT`·`CHK_CONSOLE__HOST_PORT`로 **호스트 쪽만** 옮긴다 (컨테이너 안의 포트는 그대로다).
- 두 컨테이너 모두 비관리자로 돈다 (Center uid 10001, 콘솔은 node 이미지의 `node`). 볼륨 권한이 안 맞으면 `docker compose down -v`로 지우고 다시 올린다.
- 콘솔 이미지는 **`Dockerfile.console` 하나**로 만든다 — 어느 콘솔인지는 빌드 인자 `APP`이 정한다.
- 아직 없는 것: 서비스 앱과 그 관리 콘솔(`svc-console`, 서비스 앱마다 하나 — M4), Neo4j·LLM 게이트웨이(M4), 역방향 프록시·TLS.
